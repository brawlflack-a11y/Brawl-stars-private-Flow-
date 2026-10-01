#!/usr/bin/env python3
"""Ставит channel/assets/avatar.png аватаром канала.

Боту нужно право администратора «Изменение профиля канала».
Переменные окружения те же, что у post.py: TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID.
"""

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

AVATAR = Path(__file__).resolve().parent.parent / "channel" / "assets" / "avatar.png"


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Не задан TELEGRAM_BOT_TOKEN.", file=sys.stderr)
        return 1
    chat_id = os.environ.get("TELEGRAM_CHANNEL_ID", "@VirtualBiznesChannel").strip()

    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="photo"; filename="avatar.png"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode("utf-8") + AVATAR.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/setChatPhoto",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as error:
        result = json.loads(error.read())

    if not result.get("ok"):
        print(f"Ошибка Telegram: {result.get('description')}", file=sys.stderr)
        return 1
    print("Аватар канала обновлён.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
