from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg

_pool: Optional[asyncpg.Pool] = None


def _normalize_dsn(dsn: str) -> tuple[str, Optional[str]]:
    """asyncpg doesn't understand libpq-style ?sslmode=require — strip it
    and translate into the ssl= keyword for create_pool()."""
    if "sslmode=" not in dsn:
        return dsn, None
    parts = urlsplit(dsn)
    query = parse_qsl(parts.query, keep_blank_values=True)
    ssl_mode = None
    remaining = []
    for k, v in query:
        if k == "sslmode":
            ssl_mode = v
        else:
            remaining.append((k, v))
    clean = urlunsplit(parts._replace(query=urlencode(remaining)))
    return clean, ssl_mode


async def init_pool(database_url: str) -> None:
    global _pool
    dsn, sslmode = _normalize_dsn(database_url)
    kwargs: dict = {"dsn": dsn, "min_size": 1, "max_size": 10}
    if sslmode in ("require", "verify-ca", "verify-full"):
        kwargs["ssl"] = "require"
    elif sslmode == "disable":
        kwargs["ssl"] = False
    _pool = await asyncpg.create_pool(**kwargs)


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool is not initialized. Call init_pool() first.")
    return _pool


SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT UNIQUE NOT NULL,
    chat_username TEXT,
    chat_title TEXT,
    owner_user_id BIGINT NOT NULL,
    forward_mode TEXT NOT NULL DEFAULT 'forward'
        CHECK (forward_mode IN ('forward', 'copy')),
    trigger_emoji TEXT,
    paid_until TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS processed (
    chat_id BIGINT NOT NULL,
    msg_id BIGINT NOT NULL,
    forwarded_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (chat_id, msg_id)
);

CREATE TABLE IF NOT EXISTS payments (
    id BIGSERIAL PRIMARY KEY,
    client_id BIGINT REFERENCES clients(id) ON DELETE SET NULL,
    client_chat_id BIGINT,
    user_id BIGINT NOT NULL,
    amount BIGINT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'XTR',
    payment_charge_id TEXT,
    telegram_payment_charge_id TEXT,
    days_added INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Migrations for installs that ran the previous (CASCADE) schema:
ALTER TABLE payments ADD COLUMN IF NOT EXISTS client_chat_id BIGINT;
ALTER TABLE payments ALTER COLUMN client_id DROP NOT NULL;
ALTER TABLE payments DROP CONSTRAINT IF EXISTS payments_client_id_fkey;
ALTER TABLE payments ADD CONSTRAINT payments_client_id_fkey
    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE SET NULL;
"""


async def init_schema() -> None:
    async with pool().acquire() as conn:
        await conn.execute(SCHEMA)


async def upsert_client(
    chat_id: int,
    owner_user_id: int,
    chat_username: Optional[str],
    chat_title: Optional[str],
) -> int:
    row = await pool().fetchrow(
        """
        INSERT INTO clients (chat_id, owner_user_id, chat_username, chat_title)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (chat_id) DO UPDATE SET
            chat_username = EXCLUDED.chat_username,
            chat_title = EXCLUDED.chat_title
        RETURNING id
        """,
        chat_id, owner_user_id, chat_username, chat_title,
    )
    return row["id"]


async def get_client_by_chat(chat_id: int) -> Optional[asyncpg.Record]:
    return await pool().fetchrow("SELECT * FROM clients WHERE chat_id = $1", chat_id)


async def get_client(client_id: int) -> Optional[asyncpg.Record]:
    return await pool().fetchrow("SELECT * FROM clients WHERE id = $1", client_id)


async def list_clients_for_owner(owner_user_id: int) -> list[asyncpg.Record]:
    return list(await pool().fetch(
        "SELECT * FROM clients WHERE owner_user_id = $1 ORDER BY id DESC",
        owner_user_id,
    ))


async def list_all_clients() -> list[asyncpg.Record]:
    return list(await pool().fetch("SELECT * FROM clients ORDER BY id DESC"))


async def set_forward_mode(client_id: int, mode: str) -> None:
    assert mode in ("forward", "copy")
    await pool().execute(
        "UPDATE clients SET forward_mode = $1 WHERE id = $2", mode, client_id
    )


async def set_trigger_emoji(client_id: int, emoji: Optional[str]) -> None:
    await pool().execute(
        "UPDATE clients SET trigger_emoji = $1 WHERE id = $2", emoji, client_id
    )


async def set_active(client_id: int, active: bool) -> None:
    await pool().execute(
        "UPDATE clients SET is_active = $1 WHERE id = $2", active, client_id
    )


async def extend_subscription(client_id: int, days: int) -> datetime:
    """Extend paid_until by N days from now (or from current paid_until if it's
    in the future). Also sets is_active = TRUE. Returns the new paid_until.
    Atomic — wrapped in a transaction."""
    now = datetime.now(timezone.utc)
    async with pool().acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT paid_until FROM clients WHERE id = $1 FOR UPDATE", client_id
            )
            if row is None:
                raise ValueError(f"client {client_id} not found")
            current: Optional[datetime] = row["paid_until"]
            base = max(current, now) if current else now
            new_until = base + timedelta(days=days)
            await conn.execute(
                "UPDATE clients SET paid_until = $1, is_active = TRUE WHERE id = $2",
                new_until, client_id,
            )
    return new_until


async def delete_client(client_id: int) -> None:
    async with pool().acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT chat_id FROM clients WHERE id = $1", client_id
            )
            if row:
                await conn.execute(
                    "DELETE FROM processed WHERE chat_id = $1", row["chat_id"]
                )
            await conn.execute("DELETE FROM clients WHERE id = $1", client_id)


async def is_processed(chat_id: int, msg_id: int) -> bool:
    row = await pool().fetchrow(
        "SELECT 1 FROM processed WHERE chat_id = $1 AND msg_id = $2", chat_id, msg_id,
    )
    return row is not None


async def mark_processed(chat_id: int, msg_id: int) -> None:
    await pool().execute(
        "INSERT INTO processed (chat_id, msg_id) VALUES ($1, $2) "
        "ON CONFLICT DO NOTHING",
        chat_id, msg_id,
    )


async def record_payment(
    client_id: int,
    client_chat_id: int,
    user_id: int,
    amount: int,
    currency: str,
    days_added: int,
    payment_charge_id: Optional[str],
    telegram_payment_charge_id: Optional[str],
) -> None:
    await pool().execute(
        """
        INSERT INTO payments
            (client_id, client_chat_id, user_id, amount, currency, days_added,
             payment_charge_id, telegram_payment_charge_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        client_id, client_chat_id, user_id, amount, currency, days_added,
        payment_charge_id, telegram_payment_charge_id,
    )


def subscription_active(client_row: asyncpg.Record) -> bool:
    if not client_row["is_active"]:
        return False
    until: Optional[datetime] = client_row["paid_until"]
    if not until:
        return False
    return until > datetime.now(timezone.utc)
