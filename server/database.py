"""Хранилище аккаунтов на SQLite."""
import secrets
import sqlite3
from dataclasses import dataclass

START_COINS = 500
START_GEMS = 50


@dataclass
class Account:
    id: int
    token: str
    name: str
    coins: int
    gems: int
    trophies: int


class Database:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                token    TEXT    NOT NULL,
                name     TEXT    NOT NULL,
                coins    INTEGER NOT NULL,
                gems     INTEGER NOT NULL,
                trophies INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS inventory (
                account_id INTEGER NOT NULL REFERENCES accounts(id),
                item_id    INTEGER NOT NULL,
                PRIMARY KEY (account_id, item_id)
            );
            """
        )
        self._conn.commit()

    def close(self):
        self._conn.close()

    def create_account(self) -> Account:
        token = secrets.token_hex(20)
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO accounts (token, name, coins, gems) VALUES (?, '', ?, ?)",
                (token, START_COINS, START_GEMS),
            )
        return self.get_account(cur.lastrowid)

    def get_account(self, account_id: int) -> Account | None:
        row = self._conn.execute(
            "SELECT id, token, name, coins, gems, trophies FROM accounts WHERE id = ?",
            (account_id,),
        ).fetchone()
        return Account(*row) if row else None

    def set_name(self, account_id: int, name: str):
        with self._conn:
            self._conn.execute("UPDATE accounts SET name = ? WHERE id = ?", (name, account_id))

    def get_items(self, account_id: int) -> list[int]:
        rows = self._conn.execute(
            "SELECT item_id FROM inventory WHERE account_id = ? ORDER BY item_id", (account_id,)
        ).fetchall()
        return [r[0] for r in rows]

    def buy_item(self, account_id: int, item_id: int, currency: str, price: int) -> bool:
        """Атомарно списывает валюту и выдаёт предмет. False — не хватает средств."""
        assert currency in ("coins", "gems")
        with self._conn:
            cur = self._conn.execute(
                f"UPDATE accounts SET {currency} = {currency} - ? WHERE id = ? AND {currency} >= ?",
                (price, account_id, price),
            )
            if cur.rowcount != 1:
                return False
            self._conn.execute(
                "INSERT INTO inventory (account_id, item_id) VALUES (?, ?)", (account_id, item_id)
            )
        return True

    def add_trophies(self, account_id: int, delta: int) -> int:
        """Меняет трофеи (не ниже нуля) и возвращает новое значение."""
        with self._conn:
            self._conn.execute(
                "UPDATE accounts SET trophies = MAX(0, trophies + ?) WHERE id = ?",
                (delta, account_id),
            )
        return self.get_account(account_id).trophies
