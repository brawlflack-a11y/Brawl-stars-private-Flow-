"""Тестовый консольный клиент.

Запуск:  python -m client.client --port 7777
Логин сохраняется в account.json, при следующем запуске войдёт в тот же аккаунт.
"""
import argparse
import asyncio
import json
import math
import os
import random

from server import battle as b
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

    async def expect(self, msg_id: int) -> Reader:
        got, r = await self.recv()
        assert got == msg_id, f"expected {msg_id}, got {got}"
        return r

    async def start_matchmaking(self) -> int:
        """Встаёт в очередь. Возвращает статус (MM_SEARCHING / MM_ALREADY_BUSY)."""
        await self.send(m.START_MATCHMAKING)
        return (await self.expect(m.MATCHMAKING_STATUS)).read_int()

    async def cancel_matchmaking(self) -> int:
        await self.send(m.CANCEL_MATCHMAKING)
        return (await self.expect(m.MATCHMAKING_STATUS)).read_int()

    async def wait_match(self) -> dict:
        r = await self.expect(m.MATCH_FOUND)
        return {"room": r.read_int(), "host": r.read_string(), "port": r.read_int(),
                "ticket": r.read_string(), "slot": r.read_int(), "team": r.read_int()}

    async def wait_battle_result(self) -> dict:
        r = await self.expect(m.BATTLE_RESULT)
        return {"room": r.read_int(), "result": r.read_int(),
                "delta": r.read_int(), "trophies": r.read_int()}

    async def buy(self, item_id: int) -> tuple[int, dict]:
        await self.send(m.BUY_ITEM, Writer().write_int(item_id))
        msg_id, r = await self.recv()
        assert msg_id == m.BUY_RESULT
        r.read_int()
        result = r.read_int()
        return result, await self.expect_profile()


class BattleClient(asyncio.DatagramProtocol):
    """UDP-клиент боевого сервера."""

    def __init__(self, ticket: str):
        self.ticket = ticket
        self.packets: asyncio.Queue = asyncio.Queue()
        self.transport = None
        self.seq = 0

    @classmethod
    async def connect(cls, host: str, port: int, ticket: str) -> "BattleClient":
        loop = asyncio.get_running_loop()
        _, proto = await loop.create_datagram_endpoint(lambda: cls(ticket), remote_addr=(host, port))
        return proto

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        self.packets.put_nowait(data)

    def close(self):
        self.transport.close()

    async def join(self, retries: int = 5) -> tuple[int, int]:
        """UDP может терять пакеты, поэтому JOIN повторяется. Возвращает (слот, команда)."""
        for _ in range(retries):
            self.transport.sendto(Writer().write_int(b.JOIN).write_string(self.ticket).bytes())
            try:
                while True:
                    r = Reader(await asyncio.wait_for(self.packets.get(), 1.0))
                    if r.read_int() == b.JOINED:
                        return r.read_int(), r.read_int()
            except asyncio.TimeoutError:
                continue
        raise RuntimeError("battle server did not answer")

    def send_input(self, dx: int = 0, dy: int = 0, shoot: bool = False, angle: int = 0):
        self.seq += 1
        self.transport.sendto(Writer().write_int(b.INPUT).write_string(self.ticket)
                              .write_int(self.seq).write_int(dx).write_int(dy)
                              .write_bool(shoot).write_int(angle).bytes())

    async def next_event(self) -> tuple[str, dict | int]:
        """Ждёт ("state", состояние) или ("end", победившая команда)."""
        while True:
            r = Reader(await self.packets.get())
            kind = r.read_int()
            if kind == b.STATE:
                return "state", b.parse_state(r)
            if kind == b.END:
                return "end", r.read_int()


async def play_bot(battle: BattleClient, slot: int, team: int) -> int:
    """Простой бот: идёт к ближайшему врагу и стреляет, когда тот в зоне досягаемости."""
    while True:
        kind, data = await battle.next_event()
        if kind == "end":
            return data
        me = data["players"][slot]
        enemies = [p for p in data["players"] if p["team"] != team and p["hp"] > 0]
        if me["hp"] <= 0 or not enemies:
            continue
        target = min(enemies, key=lambda p: math.hypot(p["x"] - me["x"], p["y"] - me["y"]))
        dist = math.hypot(target["x"] - me["x"], target["y"] - me["y"])
        angle = round(math.degrees(math.atan2(target["y"] - me["y"], target["x"] - me["x"])))
        step = lambda d: (d > 5) - (d < -5)
        dx, dy = step(target["x"] - me["x"]), step(target["y"] - me["y"])
        if dist < b.BULLET_RANGE * 0.6:  # достаточно близко — стоим и стреляем, иногда шагаем вбок
            dx, dy = random.choice([(0, 0), (0, 1), (0, -1)])
        battle.send_input(dx, dy, dist < b.BULLET_RANGE * 0.9, angle)
        if data["tick"] % (b.TICK_RATE * 2) == 0:
            hp = " ".join(f"{'AB'[p['team']]}{p['slot']}:{p['hp']}" for p in data["players"])
            print(f"  {data['time_left_ms'] // 1000:>3} с | {hp}")


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


RESULT_TEXT = {m.RESULT_WIN: "Победа!", m.RESULT_LOSS: "Поражение", m.RESULT_DRAW: "Ничья"}

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
        print("\n1) Профиль  2) Сменить имя  3) Магазин  4) Бой (играет бот)  0) Выход")
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
        elif choice == "4":
            if await client.start_matchmaking() != m.MM_SEARCHING:
                print("Уже в поиске или в бою")
                continue
            print("Ищем соперников...")
            match = await client.wait_match()
            print(f"Матч #{match['room']}, команда {'AB'[match['team']]}")
            battle = await BattleClient.connect(match["host"], match["port"], match["ticket"])
            try:
                slot, team = await battle.join()
                await play_bot(battle, slot, team)
            finally:
                battle.close()
            res = await client.wait_battle_result()
            print(f"{RESULT_TEXT[res['result']]} Трофеи: {res['delta']:+d} (всего {res['trophies']})")
        elif choice == "0":
            break
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
