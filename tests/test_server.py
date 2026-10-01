import asyncio
import os
import tempfile
import unittest

from client.client import Client
from server import messages as m
from server.database import START_COINS, START_GEMS
from server.protocol import HEADER, MAX_PAYLOAD, Writer


class ServerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from server.server import GameServer

        self.tmp = tempfile.TemporaryDirectory()
        self.server = GameServer(os.path.join(self.tmp.name, "test.db"))
        self.port = await self.server.start("127.0.0.1", 0)
        self.clients = []

    async def asyncTearDown(self):
        for c in self.clients:
            await c.close()
        await self.server.stop()
        self.tmp.cleanup()

    async def connect(self) -> Client:
        c = await Client.connect("127.0.0.1", self.port)
        self.clients.append(c)
        return c

    async def test_new_account_and_relogin(self):
        c = await self.connect()
        account_id, token, profile = await c.login()
        self.assertGreater(account_id, 0)
        self.assertEqual(profile["coins"], START_COINS)
        self.assertEqual(profile["gems"], START_GEMS)
        self.assertTrue(await c.set_name("Игрок"))
        await c.close()
        self.clients.remove(c)
        await asyncio.sleep(0.05)  # дать серверу обработать отключение

        c2 = await self.connect()
        same_id, _, profile = await c2.login(account_id, token)
        self.assertEqual(same_id, account_id)
        self.assertEqual(profile["name"], "Игрок")

    async def test_wrong_token_rejected(self):
        account_id, _, _ = await (await self.connect()).login()
        with self.assertRaises(RuntimeError):
            await (await self.connect()).login(account_id, "bad")

    async def test_double_login_rejected(self):
        account_id, token, _ = await (await self.connect()).login()
        with self.assertRaises(RuntimeError):
            await (await self.connect()).login(account_id, token)

    async def test_buy(self):
        c = await self.connect()
        await c.login()
        result, p = await c.buy(1)
        self.assertEqual(result, m.BUY_OK)
        self.assertEqual(p["coins"], START_COINS - 300)
        self.assertEqual(p["items"], [1])

        result, _ = await c.buy(1)
        self.assertEqual(result, m.BUY_ALREADY_OWNED)
        result, p = await c.buy(2)  # 450 при остатке 200
        self.assertEqual(result, m.BUY_NOT_ENOUGH)
        self.assertEqual(p["coins"], START_COINS - 300)
        result, _ = await c.buy(999)
        self.assertEqual(result, m.BUY_UNKNOWN_ITEM)

    async def test_bad_name(self):
        c = await self.connect()
        await c.login()
        self.assertFalse(await c.set_name("x"))
        self.assertFalse(await c.set_name("a" * 17))

    async def test_request_without_login_disconnects(self):
        c = await self.connect()
        await c.send(m.GET_PROFILE)
        with self.assertRaises(asyncio.IncompleteReadError):
            await c.recv()

    async def test_oversized_packet_disconnects(self):
        c = await self.connect()
        c.writer.write(HEADER.pack(m.LOGIN, MAX_PAYLOAD + 1, 1))
        await c.writer.drain()
        with self.assertRaises(asyncio.IncompleteReadError):
            await c.recv()

    async def test_truncated_payload_disconnects(self):
        c = await self.connect()
        await c.send(m.LOGIN, Writer().write_int(0))  # нет строки токена
        with self.assertRaises(asyncio.IncompleteReadError):
            await c.recv()


if __name__ == "__main__":
    unittest.main()
