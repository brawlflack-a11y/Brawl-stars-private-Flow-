#!/usr/bin/env python3
"""Публикует следующий неопубликованный пост из channel/posts в Telegram-канал.

Посты публикуются по алфавиту имён файлов:
  *.html — текстовый пост (Telegram HTML-разметка)
  *.json — опрос или викторина (поля как у метода sendPoll)

Переменные окружения:
  TELEGRAM_BOT_TOKEN  — токен бота от @BotFather
  TELEGRAM_CHANNEL_ID — @username канала или его числовой id

Использование:
  python3 bot/post.py            опубликовать следующий пост
  python3 bot/post.py --dry-run  показать, что будет опубликовано
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = ROOT / "channel" / "posts"
STATE_FILE = Path(__file__).resolve().parent / "state.json"


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"published": []}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def next_post(state):
    published = set(state["published"])
    for path in sorted(POSTS_DIR.iterdir()):
        if path.suffix in (".html", ".json") and path.name not in published:
            return path
    return None


def build_request(path, chat_id):
    if path.suffix == ".html":
        return "sendMessage", {
            "chat_id": chat_id,
            "text": path.read_text(encoding="utf-8").strip(),
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
    poll = json.loads(path.read_text(encoding="utf-8"))
    payload = {
        "chat_id": chat_id,
        "question": poll["question"],
        "options": [{"text": option} for option in poll["options"]],
        "type": poll.get("type", "regular"),
        "is_anonymous": True,
    }
    if payload["type"] == "quiz":
        payload["correct_option_id"] = poll["correct_option_id"]
        if "explanation" in poll:
            payload["explanation"] = poll["explanation"]
    return "sendPoll", payload


def call_api(token, method, payload):
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        return json.loads(error.read())


def main():
    dry_run = "--dry-run" in sys.argv
    state = load_state()
    path = next_post(state)
    if path is None:
        print("Все посты уже опубликованы. Добавьте новые в channel/posts.")
        return 0

    chat_id = os.environ.get("TELEGRAM_CHANNEL_ID", "@VirtualBiznesChannel").strip()
    method, payload = build_request(path, chat_id)

    if dry_run:
        print(f"[dry-run] {path.name} -> {method}")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Не задан TELEGRAM_BOT_TOKEN.", file=sys.stderr)
        return 1

    result = call_api(token, method, payload)
    if not result.get("ok"):
        print(f"Ошибка Telegram при публикации {path.name}: {result.get('description')}", file=sys.stderr)
        return 1

    state["published"].append(path.name)
    save_state(state)
    print(f"Опубликовано: {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
