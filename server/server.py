"""Лобби-сервер: принимает TCP-подключения, обрабатывает логин, профиль и магазин.

Запуск:  python -m server.server --port 7777 --db game.db
"""
import argparse
import asyncio
import logging
import secrets

from . import messages as m
from .database import Database
from .protocol import ProtocolError, Reader, Writer, encode_packet, read_packet

log = logging.getLogger("lobby")

IDLE_TIMEOUT = 60  # секунд без пакетов — отключаем

# Каталог магазина: id -> (название, валюта, цена). Цены знает только сервер.
SHOP = {
    1: ("Скин: Рыцарь", "coins", 300),
    2: ("Скин: Пират", "coins", 450),
    3: ("Скин: Робот", "gems", 30),
    4: ("Эмодзи: Смех", "coins", 100),
}


class Session:
    def __init__(self, server: "GameServer", reader, writer):
        self.server = server
        self.db = server.db
        self.reader = reader
        self.writer = writer
        self.account_id: int | None = None
        self.peer = writer.get_extra_info("peername")

    def send(self, msg_id: int, payload: Writer | None = None):
        self.writer.write(encode_packet(msg_id, payload.bytes() if payload else b""))

    async def run(self):
        log.info("connect %s", self.peer)
        try:
            while True:
                msg_id, _version, payload = await asyncio.wait_for(
                    read_packet(self.reader), IDLE_TIMEOUT
                )
                await self.dispatch(msg_id, Reader(payload))
                await self.writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError):
            pass
        except ProtocolError as e:
            log.warning("protocol error from %s: %s", self.peer, e)
        finally:
            self.server.online.discard(self.account_id)
            self.writer.close()
            log.info("disconnect %s (account %s)", self.peer, self.account_id)

    async def dispatch(self, msg_id: int, r: Reader):
        handler = HANDLERS.get(msg_id)
        if handler is None:
            raise ProtocolError(f"unknown message {msg_id}")
        if self.account_id is None and msg_id not in (m.LOGIN, m.KEEP_ALIVE):
            raise ProtocolError("not logged in")
        handler(self, r)

    # --- обработчики ---

    def on_login(self, r: Reader):
        account_id = r.read_int()
        token = r.read_string(max_len=64)
        if self.account_id is not None:
            raise ProtocolError("already logged in")

        if account_id == 0:
            account = self.db.create_account()
            log.info("new account %d", account.id)
        else:
            account = self.db.get_account(account_id)
            if account is None or not secrets.compare_digest(account.token, token):
                self.send(m.LOGIN_FAILED, Writer().write_string("Неверный аккаунт или токен"))
                return

        if account.id in self.server.online:
            self.send(m.LOGIN_FAILED, Writer().write_string("Аккаунт уже в игре"))
            return

        self.account_id = account.id
        self.server.online.add(account.id)
        self.send(m.LOGIN_OK, Writer().write_int(account.id).write_string(account.token))
        self.send_profile()

    def on_keep_alive(self, r: Reader):
        self.send(m.KEEP_ALIVE_OK)

    def on_get_profile(self, r: Reader):
        self.send_profile()

    def on_set_name(self, r: Reader):
        name = r.read_string(max_len=64).strip()
        ok = 2 <= len(name) <= 16 and name.isprintable()
        if ok:
            self.db.set_name(self.account_id, name)
        self.send(m.SET_NAME_RESULT, Writer().write_bool(ok).write_string(name if ok else ""))

    def on_buy_item(self, r: Reader):
        item_id = r.read_int()
        item = SHOP.get(item_id)
        if item is None:
            result = m.BUY_UNKNOWN_ITEM
        elif item_id in self.db.get_items(self.account_id):
            result = m.BUY_ALREADY_OWNED
        elif self.db.buy_item(self.account_id, item_id, item[1], item[2]):
            result = m.BUY_OK
        else:
            result = m.BUY_NOT_ENOUGH
        self.send(m.BUY_RESULT, Writer().write_int(item_id).write_int(result))
        self.send_profile()

    def send_profile(self):
        acc = self.db.get_account(self.account_id)
        items = self.db.get_items(self.account_id)
        w = (
            Writer()
            .write_int(acc.id)
            .write_string(acc.name)
            .write_int(acc.coins)
            .write_int(acc.gems)
            .write_int(acc.trophies)
            .write_int(len(items))
        )
        for item_id in items:
            w.write_int(item_id)
        self.send(m.PROFILE, w)


HANDLERS = {
    m.LOGIN: Session.on_login,
    m.KEEP_ALIVE: Session.on_keep_alive,
    m.GET_PROFILE: Session.on_get_profile,
    m.SET_NAME: Session.on_set_name,
    m.BUY_ITEM: Session.on_buy_item,
}


class GameServer:
    def __init__(self, db_path: str):
        self.db = Database(db_path)
        self.online: set[int] = set()
        self._server: asyncio.base_events.Server | None = None

    async def start(self, host: str, port: int) -> int:
        self._server = await asyncio.start_server(self._on_connect, host, port)
        return self._server.sockets[0].getsockname()[1]

    async def _on_connect(self, reader, writer):
        await Session(self, reader, writer).run()

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self.db.close()


async def main():
    parser = argparse.ArgumentParser(description="Лобби-сервер")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7777)
    parser.add_argument("--db", default="game.db")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = GameServer(args.db)
    port = await server.start(args.host, args.port)
    log.info("listening on %s:%d", args.host, port)
    try:
        await asyncio.Event().wait()
    finally:
        await server.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
