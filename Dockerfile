# Офіційний Telegram Bot API сервер (Alpine) + бот в одному контейнері
FROM aiogram/telegram-bot-api:latest
RUN apk add --no-cache python3 py3-requests
WORKDIR /app
COPY bot.py start.sh ./
ENTRYPOINT ["sh", "/app/start.sh"]
