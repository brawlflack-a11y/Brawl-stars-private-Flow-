"""Тестовый консольный клиент.

Запуск:  python -m client.client --port 7777
Логин сохраняется в account.json, при следующем запуске войдёт в тот же аккаунт.
"""
import argparse
import asyncio
import json
import os

from server import messages as m
from server.protocol import Reader, Writer, encode_packet, read_packet
from server.server import SHOP


class Client:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer

    @classmethod
    async def connect(cls, host: str, port: int) -> "Client":
        reader, writer = await asyncio.open_connection(host, port)
        return cls(reader, writer)

    async def send(self, msg_id: int, payload: Writer | None = None):
        self.writer.write(encode_packet(msg_id, payload.bytes() if payload else b""))
        await self.writer.drain()

    async def recv(self) -> tuple[int, Reader]:
        msg_id, _version, payload = await read_packet(self.reader)
        return msg_id, Reader(payload)

    async def close(self):
        self.writer.close()
        await self.writer.wait_closed()

    async def login(self, account_id: int = 0, token: str = ""):
        """Возвращает (id, token, профиль) или бросает RuntimeError."""
        await self.send(m.LOGIN, Writer().write_int(account_id).write_string(token))
        msg_id, r = await self.recv()
        if msg_id == m.LOGIN_FAILED:
            raise RuntimeError(r.read_string())
        assert msg_id == m.LOGIN_OK
        account_id, token = r.read_int(), r.read_string()
        profile = await self.expect_profile()
        return account_id, token, profile

    async def expect_profile(self) -> dict:
        msg_id, r = await self.recv()
        assert msg_id == m.PROFILE, msg_id
        return parse_profile(r)

    async def get_profile(self) -> dict:
        await self.send(m.GET_PROFILE)
        return await self.expect_profile()

    async def set_name(self, name: str) -> bool:
        await self.send(m.SET_NAME, Writer().write_string(name))
        msg_id, r = await self.recv()
        assert msg_id == m.SET_NAME_RESULT
        return r.read_bool()

    async def buy(self, item_id: int) -> tuple[int, dict]:
        await self.send(m.BUY_ITEM, Writer().write_int(item_id))
        msg_id, r = await self.recv()
        assert msg_id == m.BUY_RESULT
        r.read_int()
        result = r.read_int()
        return result, await self.expect_profile()


def parse_profile(r: Reader) -> dict:
    profile = {
        "id": r.read_int(),
        "name": r.read_string(),
        "coins": r.read_int(),
        "gems": r.read_int(),
        "trophies": r.read_int(),
    }
    profile["items"] = [r.read_int() for _ in range(r.read_int())]
    return profile


BUY_TEXT = {
    m.BUY_OK: "куплено",
    m.BUY_NOT_ENOUGH: "не хватает валюты",
    m.BUY_UNKNOWN_ITEM: "нет такого предмета",
    m.BUY_ALREADY_OWNED: "уже есть",
}


def show(p: dict):
    items = ", ".join(SHOP[i][0] for i in p["items"] if i in SHOP) or "—"
    print(f"[#{p['id']}] {p['name'] or '(без имени)'} | монеты: {p['coins']} | "
          f"гемы: {p['gems']} | трофеи: {p['trophies']}\nПредметы: {items}")


async def main():
    parser = argparse.ArgumentParser(description="Тестовый клиент")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7777)
    parser.add_argument("--save", default="account.json")
    args = parser.parse_args()

    saved = {"id": 0, "token": ""}
    if os.path.exists(args.save):
        with open(args.save) as f:
            saved = json.load(f)

    client = await Client.connect(args.host, args.port)
    account_id, token, profile = await client.login(saved["id"], saved["token"])
    with open(args.save, "w") as f:
        json.dump({"id": account_id, "token": token}, f)
    show(profile)

    loop = asyncio.get_running_loop()
    while True:
        print("\n1) Профиль  2) Сменить имя  3) Магазин  0) Выход")
        choice = (await loop.run_in_executor(None, input, "> ")).strip()
        if choice == "1":
            show(await client.get_profile())
        elif choice == "2":
            name = await loop.run_in_executor(None, input, "Имя (2–16 символов): ")
            print("Готово" if await client.set_name(name) else "Недопустимое имя")
        elif choice == "3":
            for item_id, (title, cur, price) in SHOP.items():
                print(f"  {item_id}) {title} — {price} {'монет' if cur == 'coins' else 'гемов'}")
            raw = await loop.run_in_executor(None, input, "Номер предмета: ")
            if raw.strip().isdigit():
                result, p = await client.buy(int(raw))
                print(BUY_TEXT.get(result, result))
                show(p)
        elif choice == "0":
            break
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
