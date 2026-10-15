import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database import Database


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(str(Path(self.temp_dir.name) / "test.sqlite3"))
        await self.database.initialize()

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_player_registration_and_action_result(self) -> None:
        await self.database.ensure_player(101, "rabza")
        player = await self.database.get_player(101)
        self.assertEqual(player["cash"], 500)
        self.assertEqual(player["heat"], 0)
        self.assertEqual(player["gamos"], "Aucun")

        applied = await self.database.apply_action_result(
            101, 350, 12, "RAV4", None
        )
        self.assertTrue(applied)
        player = await self.database.get_player(101)
        self.assertEqual(player["cash"], 850)
        self.assertEqual(player["heat"], 12)
        self.assertEqual(player["gamos"], "RAV4")

    async def test_prison_blocks_actions_and_bail_releases_player(self) -> None:
        await self.database.ensure_player(202, "en_taupe")
        deadline = datetime.now(timezone.utc) + timedelta(minutes=60)
        applied = await self.database.apply_action_result(
            202, 0, 15, None, deadline
        )
        self.assertTrue(applied)

        blocked = await self.database.apply_action_result(202, 250, 8, None, None)
        self.assertFalse(blocked)
        self.assertFalse(await self.database.pay_bail(202, 600))
        self.assertTrue(await self.database.pay_bail(202, 300))

        player = await self.database.get_player(202)
        self.assertEqual(player["cash"], 200)
        self.assertIsNone(player["in_prison_until"])

    async def test_leaderboard_is_ordered_by_cash(self) -> None:
        await self.database.ensure_player(1, "premier")
        await self.database.ensure_player(2, "deuxieme")
        await self.database.apply_action_result(2, 200, 0, None, None)

        leaders = await self.database.get_top_players()
        self.assertEqual(leaders[0]["username"], "deuxieme")
        self.assertEqual(leaders[0]["cash"], 700)

    async def test_xp_updates_level_and_shop_purchase_is_atomic(self) -> None:
        await self.database.ensure_player(303, "level_up")
        await self.database.apply_action_result(303, 10000, 0, None, None, xp_gain=19000)

        player = await self.database.get_player(303)
        self.assertEqual(player["level"], 20)
        self.assertEqual(player["xp"], 19000)
        self.assertEqual(await self.database.purchase_item(303, "obd_device"), "ok")
        self.assertEqual(await self.database.purchase_item(303, "glock_19"), "ok")
        effects = await self.database.get_item_effects(303)
        self.assertTrue(effects["has_obd"])
        self.assertTrue(effects["has_weapon"])
        self.assertEqual(effects["success_bonus"], 0.08)
        player = await self.database.get_player(303)
        self.assertEqual(player["cash"], 3000)

    async def test_shop_enforces_level_and_insufficient_cash(self) -> None:
        await self.database.ensure_player(404, "nouveau")
        self.assertEqual(await self.database.purchase_item(404, "glock_19"), "level")
        self.assertEqual(await self.database.purchase_item(404, "tech_fleece"), "ok")
        self.assertEqual(await self.database.purchase_item(404, "tech_fleece"), "ok")
        self.assertEqual(await self.database.purchase_item(404, "tech_fleece"), "cash")
        self.assertEqual(await self.database.purchase_item(404, "unknown"), "missing")

    async def test_pvp_cash_transfer_and_counter_fine(self) -> None:
        await self.database.ensure_player(505, "attaquant")
        await self.database.ensure_player(606, "victime")
        await self.database.apply_action_result(
            505, 1000, 0, None, None, xp_gain=19000
        )
        result = await self.database.apply_pvp_result(
            505, 606, "success", 0, None, 70
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["amount"], 100)
        self.assertEqual((await self.database.get_player(505))["cash"], 1600)
        self.assertEqual((await self.database.get_player(606))["cash"], 400)

        boosted = await self.database.apply_pvp_result(
            505, 606, "success", 0, None, 70, transfer_rate=0.28
        )
        self.assertEqual(boosted["amount"], 112)
        self.assertEqual((await self.database.get_player(606))["cash"], 288)

        jail_until = datetime.now(timezone.utc) + timedelta(minutes=30)
        counter = await self.database.apply_pvp_result(
            505, 606, "counter", 100, jail_until, 0
        )
        self.assertEqual(counter["status"], "counter")
        self.assertEqual(counter["fine"], 100)
        self.assertEqual((await self.database.get_player(505))["cash"], 1612)
        self.assertEqual((await self.database.get_player(606))["cash"], 388)

    async def test_pvp_failure_sets_prison_without_transferring_cash(self) -> None:
        await self.database.ensure_player(808, "joueur_a")
        await self.database.ensure_player(909, "joueur_b")
        await self.database.apply_action_result(
            808, 0, 0, None, None, xp_gain=19000
        )
        deadline = datetime.now(timezone.utc) + timedelta(minutes=30)

        result = await self.database.apply_pvp_result(
            808, 909, "failed", 0, deadline, 0
        )

        self.assertEqual(result["status"], "failed")
        attacker = await self.database.get_player(808)
        victim = await self.database.get_player(909)
        self.assertEqual(attacker["cash"], 500)
        self.assertIsNotNone(attacker["in_prison_until"])
        self.assertEqual(victim["cash"], 500)

    async def test_group_players_keep_separate_balances_and_inventories(self) -> None:
        await self.database.ensure_player(1111, "player_one")
        await self.database.ensure_player(2222, "player_two")
        await self.database.apply_action_result(
            1111, 4000, 0, None, None, xp_gain=19000
        )
        self.assertEqual(await self.database.purchase_item(1111, "glock_19"), "ok")

        first = await self.database.get_player(1111)
        second = await self.database.get_player(2222)
        first_items = await self.database.get_inventory(1111)
        second_items = await self.database.get_inventory(2222)
        self.assertEqual(first["cash"], 1000)
        self.assertEqual(second["cash"], 500)
        self.assertEqual([item["item_id"] for item in first_items], ["glock_19"])
        self.assertEqual(second_items, [])

    async def test_initialize_migrates_existing_players_table(self) -> None:
        legacy_path = Path(self.temp_dir.name) / "legacy.sqlite3"
        connection = sqlite3.connect(legacy_path)
        try:
            connection.execute(
                """
                CREATE TABLE players (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    cash INTEGER NOT NULL DEFAULT 500,
                    heat INTEGER NOT NULL DEFAULT 0,
                    in_prison_until TIMESTAMP,
                    gamos TEXT NOT NULL DEFAULT 'Aucun'
                )
                """
            )
            connection.execute(
                "INSERT INTO players (user_id, username) VALUES (707, 'legacy')"
            )
            connection.commit()
        finally:
            connection.close()

        migrated = Database(str(legacy_path))
        await migrated.initialize()
        player = await migrated.get_player(707)
        self.assertEqual(player["level"], 1)
        self.assertEqual(player["xp"], 0)
        self.assertEqual(await migrated.purchase_item(707, "tech_fleece"), "ok")


if __name__ == "__main__":
    unittest.main()
