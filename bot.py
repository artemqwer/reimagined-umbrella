#!/usr/bin/env python3
"""Telegram-бот: надішліть .zip — отримаєте фото й відео з нього альбомами.

BOT_TOKEN=... python3 bot.py                     # режим бота (архіви до 20 МБ)
BOT_TOKEN=... python3 bot.py архів.zip [CHAT_ID]  # великий архів з диска (без CHAT_ID — адміну)

Доступ: перший, хто напише боту /start, стає адміном.
Адмін: /invite — одноразове посилання-запрошення, /users — список, /kick ID — забрати доступ.
STATE_FILE=/var/data/bot_state.json — де зберігати адміна й користувачів (на хостингу — на постійному диску).
API_URL=http://localhost:8081 — свій Bot API сервер (ліміт 2 ГБ замість 20/50 МБ).
"""
import json, os, secrets, sys, tempfile, time, zipfile
import requests

TOKEN = os.environ['BOT_TOKEN']
API = os.environ.get('API_URL', 'https://api.telegram.org')
LOCAL = 'API_URL' in os.environ
STATE = os.environ.get('STATE_FILE') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot_state.json')
MB = 2**20
UPLOAD_LIMIT = (2000 if LOCAL else 50) * MB
DOWNLOAD_LIMIT = float('inf') if LOCAL else 20 * MB  # свій сервер з --local скачує без ліміту
PHOTO_LIMIT = 10 * MB  # більші фото йдуть документом
PHOTO = ('.jpg', '.jpeg', '.png', '.webp')
VIDEO = ('.mp4', '.mov', '.m4v')
WORKDIR = '.'  # не /tmp: там tmpfs у RAM, а архіви бувають по гігабайту


def call(method, files=None, **data):
    while True:
        handles = {k: open(p, 'rb') for k, p in (files or {}).items()}
        try:
            r = requests.post(f'{API}/bot{TOKEN}/{method}', data=data, files=handles or None, timeout=900).json()
        finally:
            for h in handles.values():
                h.close()
        if r.get('ok'):
            return r['result']
        wait = r.get('parameters', {}).get('retry_after')
        if not wait:
            raise RuntimeError(r.get('description'))
        time.sleep(wait)  # flood limit: Telegram сам каже, скільки чекати


def send_one(chat, kind, path):
    method = {'photo': 'sendPhoto', 'video': 'sendVideo', 'document': 'sendDocument'}[kind]
    call(method, chat_id=chat, files={kind: path})


def send_media(chat, paths):
    """Надсилає фото/відео альбомами по 10. Повертає імена файлів, що не пройшли."""
    skipped, album, docs = [], [], []
    for p in paths:
        size = os.path.getsize(p)
        if size > UPLOAD_LIMIT:
            skipped.append(os.path.basename(p))
        elif p.lower().endswith(VIDEO):
            album.append(('video', p))
        elif size <= PHOTO_LIMIT:
            album.append(('photo', p))
        else:
            docs.append(('document', p))

    batches = [album[i:i + 10] for i in range(0, len(album), 10)] + [[d] for d in docs]
    for batch in batches:
        try:
            if len(batch) == 1:
                send_one(chat, *batch[0])
            else:
                media = [{'type': k, 'media': f'attach://f{j}'} for j, (k, _) in enumerate(batch)]
                call('sendMediaGroup', chat_id=chat, media=json.dumps(media),
                     files={f'f{j}': p for j, (_, p) in enumerate(batch)})
        except RuntimeError:
            # один битий файл валить увесь альбом — шлемо по одному, а не прийнятий як фото — документом
            for kind, p in batch:
                try:
                    send_one(chat, kind, p)
                except RuntimeError:
                    try:
                        send_one(chat, 'document', p)
                    except RuntimeError:
                        skipped.append(os.path.basename(p))
    return skipped


def unpack_and_send(chat, zip_path):
    with tempfile.TemporaryDirectory(dir=WORKDIR) as tmp:
        with zipfile.ZipFile(zip_path) as z:
            # extract() сам відкидає '..' та абсолютні шляхи і повертає реальний шлях
            paths = sorted(z.extract(n, tmp) for n in z.namelist() if n.lower().endswith(PHOTO + VIDEO))
        call('sendMessage', chat_id=chat, text=f'Знайшов {len(paths)} фото/відео, надсилаю…')
        skipped = send_media(chat, paths)
    text = f'Готово: {len(paths) - len(skipped)} з {len(paths)}.'
    if skipped:
        text += f'\nНе вдалося ({len(skipped)}): ' + ', '.join(skipped)
    call('sendMessage', chat_id=chat, text=text[:4000])


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {'admin': None, 'users': {}, 'invites': []}


def save_state(s):
    with open(STATE, 'w') as f:
        json.dump(s, f, ensure_ascii=False, indent=1)


def check_access(m, s):
    """Обробляє /start, запрошення й команди адміна. True — можна працювати з архівом."""
    uid, chat = m['from']['id'], m['chat']['id']
    name = m['from'].get('username') or m['from'].get('first_name', '')
    text = m.get('text', '')
    say = lambda t: call('sendMessage', chat_id=chat, text=t)

    if text.startswith('/start'):
        code = text[len('/start'):].strip()
        if s['admin'] is None:
            s['admin'] = uid
            save_state(s)
            return say('Ви адмін. /invite — запросити користувача, /users — список, /kick ID — забрати доступ.')
        if code in s['invites']:
            s['invites'].remove(code)  # одноразове
            s['users'][str(uid)] = name
            save_state(s)
            return say('Доступ відкрито. Надішліть .zip архів.')

    if uid == s['admin']:
        if text == '/invite':
            code = secrets.token_urlsafe(9)
            s['invites'].append(code)
            save_state(s)
            return say(f'Одноразове запрошення:\nhttps://t.me/{call("getMe")["username"]}?start={code}')
        if text == '/users':
            return say('\n'.join(f'{i} — {n}' for i, n in s['users'].items()) or 'Нікого не запрошено.')
        if text.startswith('/kick '):
            removed = s['users'].pop(text.split()[1], None)
            save_state(s)
            return say(f'Доступ забрано: {removed}' if removed is not None else 'Такого користувача немає.')
    elif str(uid) not in s['users']:
        return say('Немає доступу. Попросіть запрошення в адміна.')
    return True


def handle(m):
    if check_access(m, load_state()) is not True:
        return
    chat = m['chat']['id']
    doc = m.get('document')
    if not doc or not doc.get('file_name', '').lower().endswith('.zip'):
        call('sendMessage', chat_id=chat, text='Надішліть .zip архів — поверну з нього фото й відео.')
        return
    if doc.get('file_size', 0) > DOWNLOAD_LIMIT:
        call('sendMessage', chat_id=chat, text=(
            f'Архів більший за {DOWNLOAD_LIMIT // MB} МБ — Telegram не дає боту його скачати.\n'
            f'Адмін може надіслати його з комп’ютера: python3 bot.py архів.zip {chat}'))
        return
    path = call('getFile', file_id=doc['file_id'])['file_path']
    if os.path.isabs(path):  # свій Bot API сервер у режимі --local віддає шлях на диску
        try:
            return unpack_and_send(chat, path)
        finally:
            os.remove(path)  # інакше архіви копитимуться на диску сервера
    with tempfile.NamedTemporaryFile(dir=WORKDIR, suffix='.zip') as f:
        with requests.get(f'{API}/file/bot{TOKEN}/{path}', stream=True, timeout=900) as r:
            r.raise_for_status()
            for chunk in r.iter_content(MB):
                f.write(chunk)
        f.flush()
        unpack_and_send(chat, f.name)


def bot():
    offset = 0
    print('Бот запущено. Ctrl-C — зупинити.')
    while True:
        try:
            updates = call('getUpdates', offset=offset, timeout=50)
        except (requests.RequestException, RuntimeError) as e:
            print('getUpdates:', e)
            time.sleep(5)
            continue
        for u in updates:
            offset = u['update_id'] + 1
            m = u.get('message')
            if not m or 'from' not in m:
                continue
            try:
                handle(m)
            except Exception as e:
                print('Помилка:', e)
                try:
                    call('sendMessage', chat_id=m['chat']['id'], text=f'Помилка: {e}')
                except Exception:
                    pass


if __name__ == '__main__':
    if len(sys.argv) > 1:
        chat = int(sys.argv[2]) if len(sys.argv) > 2 else load_state()['admin']
        if chat is None:
            sys.exit('Спершу запустіть бота й напишіть йому /start — так з’явиться адмін.')
        unpack_and_send(chat, sys.argv[1])
    else:
        bot()
