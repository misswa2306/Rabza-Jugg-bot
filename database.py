"""SQLite persistence for players."""

from datetime import datetime, timezone
from typing import Any

import aiosqlite

from game import ITEMS, level_for_xp


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
                    gamos TEXT NOT NULL DEFAULT 'Aucun',
                    level INTEGER NOT NULL DEFAULT 1 CHECK (level BETWEEN 1 AND 60),
                    xp INTEGER NOT NULL DEFAULT 0 CHECK (xp >= 0)
                )
                """
            )
            cursor = await connection.execute("PRAGMA table_info(players)")
            existing_columns = {row[1] for row in await cursor.fetchall()}
            if "level" not in existing_columns:
                await connection.execute(
                    "ALTER TABLE players ADD COLUMN level INTEGER NOT NULL DEFAULT 1"
                )
            if "xp" not in existing_columns:
                await connection.execute(
                    "ALTER TABLE players ADD COLUMN xp INTEGER NOT NULL DEFAULT 0"
                )
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS items (
                    item_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    price INTEGER NOT NULL CHECK (price >= 0),
                    min_level INTEGER NOT NULL CHECK (min_level BETWEEN 1 AND 60),
                    xp_bonus INTEGER NOT NULL DEFAULT 0,
                    success_bonus REAL NOT NULL DEFAULT 0
                )
                """
            )
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS inventory (
                    user_id INTEGER NOT NULL REFERENCES players(user_id) ON DELETE CASCADE,
                    item_id TEXT NOT NULL REFERENCES items(item_id),
                    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
                    PRIMARY KEY (user_id, item_id)
                )
                """
            )
            await connection.executemany(
                """
                INSERT INTO items
                    (item_id, name, category, price, min_level, xp_bonus, success_bonus)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    name = excluded.name,
                    category = excluded.category,
                    price = excluded.price,
                    min_level = excluded.min_level,
                    xp_bonus = excluded.xp_bonus,
                    success_bonus = excluded.success_bonus
                """,
                [
                    (
                        item.item_id,
                        item.name,
                        item.category,
                        item.price,
                        item.min_level,
                        item.xp_bonus,
                        item.success_bonus,
                    )
                    for item in ITEMS
                ],
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
                "SELECT user_id, username, cash, heat, in_prison_until, gamos, level, xp "
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
        xp_gain: int = 0,
    ) -> bool:
        """Apply a game result atomically, unless the player is already jailed."""
        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(self.path) as connection:
            await connection.execute("BEGIN IMMEDIATE")
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                "SELECT in_prison_until, xp FROM players WHERE user_id = ?",
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

            new_xp = row["xp"] + max(0, xp_gain)
            new_level = level_for_xp(new_xp)
            await connection.execute(
                """
                UPDATE players
                SET cash = MAX(0, cash + ?),
                    heat = MIN(100, MAX(0, heat + ?)),
                    gamos = COALESCE(?, gamos),
                    in_prison_until = ?,
                    xp = ?,
                    level = ?
                WHERE user_id = ?
                """,
                (
                    cash_delta,
                    heat_delta,
                    gamos,
                    prison_until.isoformat() if prison_until else None,
                    new_xp,
                    new_level,
                    user_id,
                ),
            )
            await connection.commit()
            return True

    async def get_inventory(self, user_id: int) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                """
                SELECT i.item_id, i.name, i.category, i.xp_bonus,
                       i.success_bonus, inv.quantity
                FROM inventory AS inv
                JOIN items AS i ON i.item_id = inv.item_id
                WHERE inv.user_id = ?
                ORDER BY i.category, i.name
                """,
                (user_id,),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def purchase_item(self, user_id: int, item_id: str) -> str:
        """Buy one item atomically. Return an outcome code for the caller."""
        async with aiosqlite.connect(self.path) as connection:
            await connection.execute("BEGIN IMMEDIATE")
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                """
                SELECT p.cash, p.level, i.price, i.min_level
                FROM players AS p CROSS JOIN items AS i
                WHERE p.user_id = ? AND i.item_id = ?
                """,
                (user_id, item_id),
            )
            row = await cursor.fetchone()
            if row is None:
                await connection.rollback()
                return "missing"
            if row["level"] < row["min_level"]:
                await connection.rollback()
                return "level"
            if row["cash"] < row["price"]:
                await connection.rollback()
                return "cash"

            await connection.execute(
                "UPDATE players SET cash = cash - ? WHERE user_id = ?",
                (row["price"], user_id),
            )
            await connection.execute(
                """
                INSERT INTO inventory (user_id, item_id, quantity)
                VALUES (?, ?, 1)
                ON CONFLICT(user_id, item_id)
                DO UPDATE SET quantity = quantity + 1
                """,
                (user_id, item_id),
            )
            await connection.commit()
            return "ok"

    async def get_item_effects(self, user_id: int) -> dict[str, float | int | bool]:
        async with aiosqlite.connect(self.path) as connection:
            cursor = await connection.execute(
                """
                SELECT
                    COALESCE(MAX(i.xp_bonus), 0),
                    COALESCE(MAX(i.success_bonus), 0),
                    COALESCE(MAX(CASE WHEN i.item_id = 'obd_device' THEN 1 ELSE 0 END), 0),
                    COALESCE(MAX(CASE WHEN i.item_id IN ('glock_19', 'ak_47') THEN 1 ELSE 0 END), 0),
                    COALESCE(MAX(CASE WHEN i.item_id = 'ak_47' THEN i.name END),
                             MAX(CASE WHEN i.item_id = 'glock_19' THEN i.name END))
                FROM inventory AS inv
                JOIN items AS i ON i.item_id = inv.item_id
                WHERE inv.user_id = ?
                """,
                (user_id,),
            )
            (
                xp_bonus,
                success_bonus,
                has_obd,
                has_weapon,
                weapon_name,
            ) = await cursor.fetchone()
            return {
                "xp_bonus": xp_bonus,
                "success_bonus": success_bonus,
                "has_obd": bool(has_obd),
                "has_weapon": bool(has_weapon),
                "weapon_name": weapon_name,
            }

    async def get_player_by_username(self, username: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                """
                SELECT user_id, username, cash, heat, in_prison_until, gamos, level, xp
                FROM players WHERE username = ? COLLATE NOCASE
                """,
                (username.lstrip("@"),),
            )
            row = await cursor.fetchone()
            return dict(row) if row is not None else None

    async def apply_pvp_result(
        self,
        attacker_id: int,
        victim_id: int,
        outcome: str,
        fine: int,
        prison_until: datetime | None,
        xp_gain: int,
        transfer_rate: float = 0.20,
    ) -> dict[str, int | str] | None:
        """Apply an abstract PVP result and cash transfer atomically."""
        if attacker_id == victim_id:
            return None
        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(self.path) as connection:
            await connection.execute("BEGIN IMMEDIATE")
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                """
                SELECT user_id, cash, xp, level, in_prison_until
                FROM players WHERE user_id IN (?, ?)
                """,
                (attacker_id, victim_id),
            )
            players = {row["user_id"]: dict(row) for row in await cursor.fetchall()}
            if attacker_id not in players or victim_id not in players:
                await connection.rollback()
                return None
            attacker = players[attacker_id]
            victim = players[victim_id]
            if attacker["level"] < 20:
                await connection.rollback()
                return {"status": "level"}
            if attacker["in_prison_until"]:
                until = datetime.fromisoformat(attacker["in_prison_until"])
                if until.tzinfo is None:
                    until = until.replace(tzinfo=timezone.utc)
                if until > now:
                    await connection.rollback()
                    return {"status": "prison"}

            if outcome == "counter":
                actual_fine = min(attacker["cash"], max(0, fine))
                await connection.execute(
                    """
                    UPDATE players
                    SET cash = cash - ?, in_prison_until = ?
                    WHERE user_id = ?
                    """,
                    (
                        actual_fine,
                        prison_until.isoformat() if prison_until else None,
                        attacker_id,
                    ),
                )
                await connection.execute(
                    "UPDATE players SET cash = cash + ? WHERE user_id = ?",
                    (actual_fine, victim_id),
                )
                await connection.commit()
                return {"status": "counter", "fine": actual_fine}

            if outcome != "success":
                if outcome == "failed" and prison_until is not None:
                    await connection.execute(
                        "UPDATE players SET in_prison_until = ? WHERE user_id = ?",
                        (prison_until.isoformat(), attacker_id),
                    )
                await connection.commit()
                return {"status": outcome}

            rate = min(0.35, max(0.15, transfer_rate))
            amount = min(victim["cash"], max(1, int(victim["cash"] * rate)))
            new_xp = attacker["xp"] + max(0, xp_gain)
            new_level = level_for_xp(new_xp)
            await connection.execute(
                "UPDATE players SET cash = cash + ?, xp = ?, level = ? WHERE user_id = ?",
                (amount, new_xp, new_level, attacker_id),
            )
            await connection.execute(
                "UPDATE players SET cash = cash - ? WHERE user_id = ?",
                (amount, victim_id),
            )
            await connection.commit()
            return {
                "status": "success",
                "amount": amount,
                "rate": rate,
                "xp": xp_gain,
                "level": new_level,
            }

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
