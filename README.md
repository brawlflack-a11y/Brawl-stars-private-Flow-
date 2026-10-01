# Brawl-stars-private-Flow-

Telegram-канал **«Бравл Тактика»**: фан-канал с гайдами и тактикой Brawl Stars.

- [`channel/README.md`](channel/README.md): концепция, оформление, рубрики, план продвижения и монетизации
- [`channel/posts/`](channel/posts/): готовые посты (`.html` — текст, `.json` — опрос или викторина)
- [`bot/post.py`](bot/post.py): автопостинг следующего поста через Telegram-бота

## Запуск автопостинга

1. Создать канал и бота через @BotFather, добавить бота администратором канала.
2. Задать переменные окружения `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHANNEL_ID` (например, `@brawl_taktika`).
3. `python3 bot/post.py --dry-run` — проверить, `python3 bot/post.py` — опубликовать.

Зависимости не нужны, только Python 3.8+.
