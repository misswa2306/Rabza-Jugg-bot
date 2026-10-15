"""SQLite persistence for players."""

from datetime import datetime, timezone
from typing import Any

import aiosqlite


class Database:
    def __init__(self, path: str) -> None:
        self.path = path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.path) as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS players (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    cash INTEGER NOT NULL DEFAULT 500 CHECK (cash >= 0),
                    heat INTEGER NOT NULL DEFAULT 0 CHECK (heat BETWEEN 0 AND 100),
                    in_prison_until TIMESTAMP,
                    gamos TEXT NOT NULL DEFAULT 'Aucun'
                )
                """
            )
            await connection.commit()

    async def ensure_player(self, user_id: int, username: str | None) -> None:
        async with aiosqlite.connect(self.path) as connection:
            await connection.execute(
                """
                INSERT INTO players (user_id, username)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET username = excluded.username
                """,
                (user_id, username),
            )
            await connection.commit()

    async def get_player(self, user_id: int) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                "SELECT user_id, username, cash, heat, in_prison_until, gamos "
                "FROM players WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
            return dict(row) if row is not None else None

    async def get_top_players(self, limit: int = 10) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                """
                SELECT username, cash
                FROM players
                ORDER BY cash DESC, user_id ASC
                LIMIT ?
                """,
                (limit,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def apply_action_result(
        self,
        user_id: int,
        cash_delta: int,
        heat_delta: int,
        gamos: str | None,
        prison_until: datetime | None,
    ) -> bool:
        """Apply a game result atomically, unless the player is already jailed."""
        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(self.path) as connection:
            await connection.execute("BEGIN IMMEDIATE")
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                "SELECT in_prison_until FROM players WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                await connection.rollback()
                return False

            until_value = row["in_prison_until"]
            if until_value:
                until = datetime.fromisoformat(until_value)
                if until.tzinfo is None:
                    until = until.replace(tzinfo=timezone.utc)
                if until > now:
                    await connection.rollback()
                    return False

            await connection.execute(
                """
                UPDATE players
                SET cash = MAX(0, cash + ?),
                    heat = MIN(100, MAX(0, heat + ?)),
                    gamos = COALESCE(?, gamos),
                    in_prison_until = ?
                WHERE user_id = ?
                """,
                (
                    cash_delta,
                    heat_delta,
                    gamos,
                    prison_until.isoformat() if prison_until else None,
                    user_id,
                ),
            )
            await connection.commit()
            return True

    async def pay_bail(self, user_id: int, amount: int) -> bool:
        """Charge bail and release an incarcerated player as one transaction."""
        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(self.path) as connection:
            await connection.execute("BEGIN IMMEDIATE")
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                "SELECT cash, in_prison_until FROM players WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
            if row is None or row["in_prison_until"] is None:
                await connection.rollback()
                return False

            until = datetime.fromisoformat(row["in_prison_until"])
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            if until <= now or row["cash"] < amount:
                await connection.rollback()
                return False

            await connection.execute(
                """
                UPDATE players
                SET cash = cash - ?, in_prison_until = NULL
                WHERE user_id = ?
                """,
                (amount, user_id),
            )
            await connection.commit()
            return True
