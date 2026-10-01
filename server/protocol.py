"""Бинарный протокол: заголовок пакета и чтение/запись полей.

Формат пакета (big-endian):
    | ID сообщения: u16 | Длина данных: u32 | Версия: u16 | Данные: N байт |
"""
import asyncio
import struct

HEADER = struct.Struct(">HIH")
MAX_PAYLOAD = 64 * 1024
PROTOCOL_VERSION = 1


class ProtocolError(Exception):
    pass


class Writer:
    def __init__(self):
        self._buf = bytearray()

    def write_int(self, value: int) -> "Writer":
        self._buf += struct.pack(">i", value)
        return self

    def write_long(self, value: int) -> "Writer":
        self._buf += struct.pack(">q", value)
        return self

    def write_bool(self, value: bool) -> "Writer":
        self._buf.append(1 if value else 0)
        return self

    def write_string(self, value: str) -> "Writer":
        data = value.encode("utf-8")
        self.write_int(len(data))
        self._buf += data
        return self

    def bytes(self) -> bytes:
        return bytes(self._buf)


class Reader:
    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    def _take(self, size: int) -> bytes:
        if size < 0 or self._pos + size > len(self._data):
            raise ProtocolError("unexpected end of payload")
        chunk = self._data[self._pos:self._pos + size]
        self._pos += size
        return chunk

    def read_int(self) -> int:
        return struct.unpack(">i", self._take(4))[0]

    def read_long(self) -> int:
        return struct.unpack(">q", self._take(8))[0]

    def read_bool(self) -> bool:
        return self._take(1)[0] != 0

    def read_string(self, max_len: int = 1024) -> str:
        size = self.read_int()
        if size > max_len:
            raise ProtocolError("string too long")
        try:
            return self._take(size).decode("utf-8")
        except UnicodeDecodeError as e:
            raise ProtocolError("invalid utf-8") from e


def encode_packet(msg_id: int, payload: bytes = b"", version: int = PROTOCOL_VERSION) -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError("payload too large")
    return HEADER.pack(msg_id, len(payload), version) + payload


async def read_packet(reader: asyncio.StreamReader) -> tuple[int, int, bytes]:
    """Читает один пакет. Возвращает (id, версия, данные)."""
    header = await reader.readexactly(HEADER.size)
    msg_id, length, version = HEADER.unpack(header)
    if length > MAX_PAYLOAD:
        raise ProtocolError(f"payload too large: {length}")
    payload = await reader.readexactly(length)
    return msg_id, version, payload
