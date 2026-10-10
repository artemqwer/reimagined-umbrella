#!/bin/sh
# Запускає свій Bot API сервер (ліміт файлів 2 ГБ замість 20/50 МБ) і бота поруч.
set -e
D=${DATA_DIR:-/var/data}
mkdir -p "$D/server" "$D/tmp" "$D/work"

# Перевести бота з api.telegram.org на свій сервер. Якщо вже переведено — Telegram поверне помилку, це нормально.
python3 -c "import os,requests; requests.get(f'https://api.telegram.org/bot{os.environ[\"BOT_TOKEN\"]}/logOut', timeout=30)" || true

telegram-bot-api --local --api-id="$TELEGRAM_API_ID" --api-hash="$TELEGRAM_API_HASH" \
    --dir="$D/server" --temp-dir="$D/tmp" &

export API_URL=http://localhost:8081
export STATE_FILE="${STATE_FILE:-$D/bot_state.json}"
cd "$D/work"  # тут розпаковуються архіви — на постійному диску, не в RAM
exec python3 /app/bot.py
