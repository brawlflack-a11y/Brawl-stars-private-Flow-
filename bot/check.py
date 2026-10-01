#!/usr/bin/env python3
"""Диагностика: показывает, от имени какого бота и в какой канал идёт публикация."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request


def call(token, method, **params):
    url = f"https://api.telegram.org/bot{token}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        return json.loads(error.read())


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHANNEL_ID", "@VirtualBiznesChannel").strip()

    me = call(token, "getMe").get("result", {})
    print(f"Бот: @{me.get('username')} (id {me.get('id')})")

    chat = call(token, "getChat", chat_id=chat_id)
    if not chat.get("ok"):
        print(f"Канал {chat_id} недоступен: {chat.get('description')}")
        return
    c = chat["result"]
    print(f"Канал: «{c.get('title')}» @{c.get('username')} (id {c.get('id')}, тип {c.get('type')})")
    count = call(token, "getChatMemberCount", chat_id=chat_id).get("result")
    print(f"Подписчиков: {count}")
    member = call(token, "getChatMember", chat_id=chat_id, user_id=me.get("id")).get("result", {})
    print(f"Статус бота в канале: {member.get('status')}, может публиковать: {member.get('can_post_messages')}")


if __name__ == "__main__":
    main()
