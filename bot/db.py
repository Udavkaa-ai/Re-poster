from __future__ import annotations

import aiosqlite
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

_db_path: str = "reposter.db"


def set_db_path(path: str) -> None:
    global _db_path
    _db_path = path


@asynccontextmanager
async def _connect():
    async with aiosqlite.connect(_db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        yield conn


async def init_db() -> None:
    async with _connect() as conn:
        await conn.executescript("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER UNIQUE NOT NULL,
            chat_username TEXT,
            chat_title TEXT,
            owner_user_id INTEGER NOT NULL,
            forward_mode TEXT NOT NULL DEFAULT 'forward'
                CHECK (forward_mode IN ('forward', 'copy')),
            trigger_emoji TEXT,
            paid_until TIMESTAMP,
            is_active INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS processed (
            chat_id INTEGER NOT NULL,
            msg_id INTEGER NOT NULL,
            forwarded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (chat_id, msg_id)
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            currency TEXT NOT NULL DEFAULT 'XTR',
            payment_charge_id TEXT,
            telegram_payment_charge_id TEXT,
            days_added INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (client_id) REFERENCES clients(id)
        );
        """)
        await conn.commit()


async def upsert_client(
    chat_id: int,
    owner_user_id: int,
    chat_username: Optional[str],
    chat_title: Optional[str],
) -> int:
    async with _connect() as conn:
        cur = await conn.execute(
            """
            INSERT INTO clients (chat_id, owner_user_id, chat_username, chat_title)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                chat_username = excluded.chat_username,
                chat_title = excluded.chat_title
            RETURNING id
            """,
            (chat_id, owner_user_id, chat_username, chat_title),
        )
        row = await cur.fetchone()
        await conn.commit()
        return row["id"]


async def get_client_by_chat(chat_id: int) -> Optional[aiosqlite.Row]:
    async with _connect() as conn:
        cur = await conn.execute("SELECT * FROM clients WHERE chat_id = ?", (chat_id,))
        return await cur.fetchone()


async def get_client(client_id: int) -> Optional[aiosqlite.Row]:
    async with _connect() as conn:
        cur = await conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,))
        return await cur.fetchone()


async def list_clients_for_owner(owner_user_id: int) -> list[aiosqlite.Row]:
    async with _connect() as conn:
        cur = await conn.execute(
            "SELECT * FROM clients WHERE owner_user_id = ? ORDER BY id DESC",
            (owner_user_id,),
        )
        return list(await cur.fetchall())


async def list_all_clients() -> list[aiosqlite.Row]:
    async with _connect() as conn:
        cur = await conn.execute("SELECT * FROM clients ORDER BY id DESC")
        return list(await cur.fetchall())


async def set_forward_mode(client_id: int, mode: str) -> None:
    assert mode in ("forward", "copy")
    async with _connect() as conn:
        await conn.execute(
            "UPDATE clients SET forward_mode = ? WHERE id = ?", (mode, client_id)
        )
        await conn.commit()


async def set_trigger_emoji(client_id: int, emoji: Optional[str]) -> None:
    async with _connect() as conn:
        await conn.execute(
            "UPDATE clients SET trigger_emoji = ? WHERE id = ?", (emoji, client_id)
        )
        await conn.commit()


async def set_active(client_id: int, active: bool) -> None:
    async with _connect() as conn:
        await conn.execute(
            "UPDATE clients SET is_active = ? WHERE id = ?",
            (1 if active else 0, client_id),
        )
        await conn.commit()


async def extend_subscription(client_id: int, days: int) -> datetime:
    """Extend paid_until by N days (from now or from current paid_until, whichever later).
    Also flips is_active=1. Returns the new paid_until."""
    now = datetime.now(timezone.utc)
    async with _connect() as conn:
        cur = await conn.execute(
            "SELECT paid_until FROM clients WHERE id = ?", (client_id,)
        )
        row = await cur.fetchone()
        current = _parse_dt(row["paid_until"]) if row and row["paid_until"] else None
        base = max(current, now) if current else now
        new_until = base + timedelta(days=days)
        await conn.execute(
            "UPDATE clients SET paid_until = ?, is_active = 1 WHERE id = ?",
            (new_until.isoformat(), client_id),
        )
        await conn.commit()
        return new_until


async def delete_client(client_id: int) -> None:
    async with _connect() as conn:
        await conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
        await conn.commit()


async def is_processed(chat_id: int, msg_id: int) -> bool:
    async with _connect() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM processed WHERE chat_id = ? AND msg_id = ?",
            (chat_id, msg_id),
        )
        return (await cur.fetchone()) is not None


async def mark_processed(chat_id: int, msg_id: int) -> None:
    async with _connect() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO processed (chat_id, msg_id) VALUES (?, ?)",
            (chat_id, msg_id),
        )
        await conn.commit()


async def record_payment(
    client_id: int,
    user_id: int,
    amount: int,
    currency: str,
    days_added: int,
    payment_charge_id: Optional[str],
    telegram_payment_charge_id: Optional[str],
) -> None:
    async with _connect() as conn:
        await conn.execute(
            """
            INSERT INTO payments
                (client_id, user_id, amount, currency, days_added,
                 payment_charge_id, telegram_payment_charge_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id,
                user_id,
                amount,
                currency,
                days_added,
                payment_charge_id,
                telegram_payment_charge_id,
            ),
        )
        await conn.commit()


def _parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def subscription_active(client_row: aiosqlite.Row) -> bool:
    if not client_row["is_active"]:
        return False
    until = _parse_dt(client_row["paid_until"])
    if not until:
        return False
    return until > datetime.now(timezone.utc)
