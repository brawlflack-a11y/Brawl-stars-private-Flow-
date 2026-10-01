import asyncio
import os
import tempfile
import unittest

from client.client import BattleClient, Client
from server import battle as b
from server import messages as m
from server.server import TROPHIES_WIN, GameServer

DT = 1 / b.TICK_RATE


class RoomTest(unittest.TestCase):
    def test_spawn_teams(self):
        room = b.Room(1, [10, 20, 30, 40])
        self.assertEqual([p.team for p in room.players], [0, 1, 0, 1])
        self.assertTrue(all(p.x < b.MAP_W / 2 for p in room.players if p.team == 0))
        self.assertTrue(all(p.x > b.MAP_W / 2 for p in room.players if p.team == 1))

    def test_movement_is_clamped_to_map_and_speed(self):
        room = b.Room(1, [1, 2])
        room.set_input(0, 1, dx=-5, dy=0, shoot=False, angle=0)  # dx обрежется до -1
        room.step(DT)
        self.assertAlmostEqual(room.players[0].x, 50 - b.PLAYER_SPEED * DT)
        for _ in range(100):
            room.step(DT)
        self.assertEqual(room.players[0].x, b.PLAYER_RADIUS)

    def test_old_input_ignored(self):
        room = b.Room(1, [1, 2])
        room.set_input(0, 5, 1, 0, False, 0)
        room.set_input(0, 4, -1, 0, False, 0)
        self.assertEqual(room.players[0].dx, 1)

    def test_shooting_kills_and_ends_match(self):
        room = b.Room(1, [1, 2])
        shooter, target = room.players
        shooter.x = target.x - 100
        room.set_input(0, 1, 0, 0, True, 0)
        for _ in range(b.TICK_RATE * 5):
            room.step(DT)
            if room.winner is not None:
                break
        self.assertEqual(target.hp, 0)
        self.assertEqual(room.winner, 0)

    def test_out_of_range_bullet_misses(self):
        room = b.Room(1, [1, 2])  # дистанция 500 > дальности 300
        room.set_input(0, 1, 0, 0, True, 0)
        for _ in range(b.TICK_RATE * 3):
            room.step(DT)
        self.assertEqual(room.players[1].hp, b.MAX_HP)

    def test_no_friendly_fire(self):
        room = b.Room(1, [1, 2, 3, 4])
        ally = room.players[2]
        shooter = room.players[0]
        ally.x, ally.y = shooter.x + 50, shooter.y
        room.set_input(0, 1, 0, 0, True, 0)
        for _ in range(b.TICK_RATE):
            room.step(DT)
        self.assertEqual(ally.hp, b.MAX_HP)

    def test_timeout_draw(self):
        room = b.Room(1, [1, 2], duration=0.2)
        for _ in range(10):
            room.step(DT)
        self.assertEqual(room.winner, b.DRAW)


class MatchTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = GameServer(os.path.join(self.tmp.name, "t.db"), match_size=2, match_duration=10)
        self.port = await self.server.start("127.0.0.1", 0)
        self.closers = []

    async def asyncTearDown(self):
        for close in self.closers:
            close()
        await self.server.stop()
        self.tmp.cleanup()

    async def player(self) -> Client:
        c = await Client.connect("127.0.0.1", self.port)
        self.closers.append(c.writer.close)
        await c.login()
        return c

    async def battle(self, match) -> BattleClient:
        bc = await BattleClient.connect(match["host"], match["port"], match["ticket"])
        self.closers.append(bc.close)
        return bc

    async def test_cancel_and_double_queue(self):
        c = await self.player()
        self.assertEqual(await c.start_matchmaking(), m.MM_SEARCHING)
        self.assertEqual(await c.start_matchmaking(), m.MM_ALREADY_BUSY)
        self.assertEqual(await c.cancel_matchmaking(), m.MM_CANCELLED)
        self.assertEqual(self.server.queue, [])

    async def test_disconnect_leaves_queue(self):
        c = await self.player()
        await c.start_matchmaking()
        c.writer.close()
        await asyncio.sleep(0.05)
        self.assertEqual(self.server.queue, [])

    async def test_full_match(self):
        a, d = await self.player(), await self.player()
        await a.start_matchmaking()
        await d.start_matchmaking()
        ma, md = await a.wait_match(), await d.wait_match()
        self.assertEqual(ma["room"], md["room"])
        self.assertNotEqual(ma["team"], md["team"])
        self.assertEqual(await a.start_matchmaking(), m.MM_ALREADY_BUSY)

        ba, bd = await self.battle(ma), await self.battle(md)
        self.assertEqual(await ba.join(), (ma["slot"], ma["team"]))
        await bd.join()

        # Атакующий идёт к противнику и стреляет, пока матч не закончится
        winner = None
        while winner is None:
            kind, data = await asyncio.wait_for(ba.next_event(), 5)
            if kind == "end":
                winner = data
                break
            me, enemy = data["players"][ma["slot"]], data["players"][md["slot"]]
            close = abs(enemy["x"] - me["x"]) < 150
            ba.send_input(0 if close else (1 if enemy["x"] > me["x"] else -1), 0, close,
                          0 if enemy["x"] > me["x"] else 180)
        self.assertEqual(winner, ma["team"])

        ra, rd = await a.wait_battle_result(), await d.wait_battle_result()
        self.assertEqual((ra["result"], ra["delta"], ra["trophies"]), (m.RESULT_WIN, TROPHIES_WIN, TROPHIES_WIN))
        self.assertEqual((rd["result"], rd["trophies"]), (m.RESULT_LOSS, 0))  # не уходит в минус
        self.assertEqual(self.server.in_battle, set())
        self.assertEqual(self.server.battle.tickets, {})

    async def test_input_from_foreign_address_ignored(self):
        a, d = await self.player(), await self.player()
        await a.start_matchmaking()
        await d.start_matchmaking()
        ma, _ = await a.wait_match(), await d.wait_match()
        owner = await self.battle(ma)
        await owner.join()
        intruder = await self.battle(ma)  # знает билет, но не делал JOIN со своего адреса
        intruder.send_input(1, 0, False, 0)
        await asyncio.sleep(0.2)
        room = self.server.battle.rooms[ma["room"]]
        self.assertEqual(room.players[ma["slot"]].dx, 0)


if __name__ == "__main__":
    unittest.main()
