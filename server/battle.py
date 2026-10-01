"""Боевой сервер: симуляция матча и UDP-транспорт.

Сервер авторитетен: клиенты присылают только ввод (направление движения,
выстрел, угол прицела), а позиции, попадания и урон считает сервер.

UDP-пакеты (поля через Writer/Reader, первое поле — тип):
    клиент -> сервер
        JOIN   : тип, билет
        INPUT  : тип, билет, seq, dx (-1..1), dy (-1..1), выстрел, угол (градусы)
    сервер -> клиент
        JOINED : тип, слот, команда
        STATE  : тип, тик, осталось мс, кол-во игроков, [слот, команда, x, y, hp]...,
                 кол-во пуль, [x, y]...
        END    : тип, победившая команда (-1 — ничья)
"""
import asyncio
import logging
import math
import secrets
from dataclasses import dataclass, field
from typing import Callable

from .protocol import ProtocolError, Reader, Writer

log = logging.getLogger("battle")

TICK_RATE = 20
MAP_W, MAP_H = 600, 600
PLAYER_SPEED = 150       # единиц в секунду
PLAYER_RADIUS = 15
MAX_HP = 100
BULLET_SPEED = 400
BULLET_RADIUS = 5
BULLET_RANGE = 300
BULLET_DAMAGE = 25
SHOOT_COOLDOWN = 0.5     # секунд
MATCH_DURATION = 120.0   # секунд
MAX_DATAGRAM = 512

# Типы UDP-пакетов
JOIN, INPUT = 1, 2
JOINED, STATE, END = 11, 12, 13

DRAW = -1


@dataclass
class Player:
    account_id: int
    team: int
    x: float
    y: float
    hp: int = MAX_HP
    dx: int = 0
    dy: int = 0
    shoot: bool = False
    angle: int = 0
    last_seq: int = -1
    cooldown: float = 0.0
    addr: tuple | None = None

    @property
    def alive(self) -> bool:
        return self.hp > 0


@dataclass
class Bullet:
    team: int
    x: float
    y: float
    vx: float
    vy: float
    travelled: float = 0.0


@dataclass
class Room:
    """Состояние одного матча. Ничего не знает о сети — удобно тестировать."""
    room_id: int
    account_ids: list[int]
    duration: float = MATCH_DURATION
    players: list[Player] = field(init=False)
    bullets: list[Bullet] = field(default_factory=list)
    tick: int = 0
    time_left: float = field(init=False)
    winner: int | None = None

    def __post_init__(self):
        self.time_left = self.duration
        team_sizes = [(len(self.account_ids) + 1 - t) // 2 for t in (0, 1)]
        self.players = []
        for slot, account_id in enumerate(self.account_ids):
            team, index = slot % 2, slot // 2
            x = 50 if team == 0 else MAP_W - 50
            y = MAP_H / 2 + (index - (team_sizes[team] - 1) / 2) * 80
            self.players.append(Player(account_id, team, x, y))

    def set_input(self, slot: int, seq: int, dx: int, dy: int, shoot: bool, angle: int):
        p = self.players[slot]
        if seq <= p.last_seq:  # старый или повторный пакет UDP
            return
        p.last_seq = seq
        p.dx = max(-1, min(1, dx))
        p.dy = max(-1, min(1, dy))
        p.shoot = shoot
        p.angle = angle % 360

    def step(self, dt: float):
        if self.winner is not None:
            return
        self.tick += 1
        self.time_left -= dt

        for p in self.players:
            if not p.alive:
                continue
            length = math.hypot(p.dx, p.dy)
            if length:
                p.x += p.dx / length * PLAYER_SPEED * dt
                p.y += p.dy / length * PLAYER_SPEED * dt
                p.x = max(PLAYER_RADIUS, min(MAP_W - PLAYER_RADIUS, p.x))
                p.y = max(PLAYER_RADIUS, min(MAP_H - PLAYER_RADIUS, p.y))
            p.cooldown = max(0.0, p.cooldown - dt)
            if p.shoot and p.cooldown == 0:
                p.cooldown = SHOOT_COOLDOWN
                rad = math.radians(p.angle)
                self.bullets.append(Bullet(
                    p.team, p.x, p.y, math.cos(rad) * BULLET_SPEED, math.sin(rad) * BULLET_SPEED
                ))

        remaining = []
        for b in self.bullets:
            b.x += b.vx * dt
            b.y += b.vy * dt
            b.travelled += BULLET_SPEED * dt
            if b.travelled > BULLET_RANGE or not (0 <= b.x <= MAP_W and 0 <= b.y <= MAP_H):
                continue
            target = next(
                (p for p in self.players
                 if p.alive and p.team != b.team
                 and math.hypot(p.x - b.x, p.y - b.y) <= PLAYER_RADIUS + BULLET_RADIUS),
                None,
            )
            if target:
                target.hp = max(0, target.hp - BULLET_DAMAGE)
            else:
                remaining.append(b)
        self.bullets = remaining

        alive = [sum(p.alive for p in self.players if p.team == t) for t in (0, 1)]
        if alive[0] == 0 or alive[1] == 0 or self.time_left <= 0:
            if alive[0] == alive[1]:
                self.winner = DRAW
            else:
                self.winner = 0 if alive[0] > alive[1] else 1

    def encode_state(self) -> bytes:
        w = Writer().write_int(STATE).write_int(self.tick)
        w.write_int(max(0, int(self.time_left * 1000))).write_int(len(self.players))
        for slot, p in enumerate(self.players):
            w.write_int(slot).write_int(p.team).write_int(round(p.x)).write_int(round(p.y))
            w.write_int(p.hp)
        w.write_int(len(self.bullets))
        for b in self.bullets:
            w.write_int(round(b.x)).write_int(round(b.y))
        return w.bytes()


def parse_state(r: Reader) -> dict:
    state = {"tick": r.read_int(), "time_left_ms": r.read_int(), "players": [], "bullets": []}
    for _ in range(r.read_int()):
        slot, team, x, y, hp = (r.read_int() for _ in range(5))
        state["players"].append({"slot": slot, "team": team, "x": x, "y": y, "hp": hp})
    for _ in range(r.read_int()):
        state["bullets"].append((r.read_int(), r.read_int()))
    return state


@dataclass
class Ticket:
    room: Room
    slot: int


class BattleServer(asyncio.DatagramProtocol):
    def __init__(self, on_result: Callable[[Room], None], match_duration: float = MATCH_DURATION):
        self.on_result = on_result
        self.match_duration = match_duration
        self.rooms: dict[int, Room] = {}
        self.tickets: dict[str, Ticket] = {}
        self._next_room_id = 1
        self._transport: asyncio.DatagramTransport | None = None
        self._loop_task: asyncio.Task | None = None

    async def start(self, host: str, port: int) -> int:
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(lambda: self, local_addr=(host, port))
        self._loop_task = asyncio.create_task(self._tick_loop())
        return self._transport.get_extra_info("sockname")[1]

    async def stop(self):
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        if self._transport:
            self._transport.close()

    def create_room(self, account_ids: list[int]) -> tuple[Room, list[str]]:
        """Создаёт матч и возвращает билеты в порядке слотов."""
        room = Room(self._next_room_id, account_ids, duration=self.match_duration)
        self._next_room_id += 1
        self.rooms[room.room_id] = room
        tickets = []
        for slot in range(len(account_ids)):
            ticket = secrets.token_hex(16)
            self.tickets[ticket] = Ticket(room, slot)
            tickets.append(ticket)
        log.info("room %d created for %s", room.room_id, account_ids)
        return room, tickets

    def datagram_received(self, data: bytes, addr):
        if len(data) > MAX_DATAGRAM:
            return
        try:
            r = Reader(data)
            kind = r.read_int()
            ticket = self.tickets.get(r.read_string(max_len=64))
            if ticket is None:
                return
            player = ticket.room.players[ticket.slot]
            if kind == JOIN:
                player.addr = addr  # повторный JOIN разрешён: адрес мог смениться (NAT)
                self._send(addr, Writer().write_int(JOINED).write_int(ticket.slot).write_int(player.team))
            elif kind == INPUT and addr == player.addr:
                seq, dx, dy = r.read_int(), r.read_int(), r.read_int()
                shoot, angle = r.read_bool(), r.read_int()
                ticket.room.set_input(ticket.slot, seq, dx, dy, shoot, angle)
        except ProtocolError:
            pass  # битый датаграм просто отбрасываем

    def _send(self, addr, w: Writer | bytes):
        if self._transport and addr:
            self._transport.sendto(w if isinstance(w, bytes) else w.bytes(), addr)

    async def _tick_loop(self):
        loop = asyncio.get_running_loop()
        last = loop.time()
        while True:
            await asyncio.sleep(1 / TICK_RATE)
            now = loop.time()
            dt, last = min(now - last, 0.1), now
            for room in list(self.rooms.values()):
                room.step(dt)
                state = room.encode_state()
                for p in room.players:
                    self._send(p.addr, state)
                if room.winner is not None:
                    self._finish(room)

    def _finish(self, room: Room):
        end = Writer().write_int(END).write_int(room.winner).bytes()
        for p in room.players:
            self._send(p.addr, end)
        del self.rooms[room.room_id]
        self.tickets = {k: t for k, t in self.tickets.items() if t.room is not room}
        log.info("room %d finished, winner %d", room.room_id, room.winner)
        try:
            self.on_result(room)
        except Exception:
            log.exception("on_result failed for room %d", room.room_id)
