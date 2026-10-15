from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from telegram.error import BadRequest

from bot import edit_callback_message, player_context
from database import Database


class EditCallbackMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_unchanged_message_is_treated_as_noop(self) -> None:
        query = AsyncMock()
        query.edit_message_text.side_effect = BadRequest("Message is not modified")

        await edit_callback_message(query, "Même texte")

        query.edit_message_text.assert_awaited_once_with(
            "Même texte", reply_markup=None
        )

    async def test_other_telegram_edit_errors_are_propagated(self) -> None:
        query = AsyncMock()
        error = BadRequest("Message to edit not found")
        query.edit_message_text.side_effect = error

        with self.assertRaises(BadRequest) as raised:
            await edit_callback_message(query, "Résultat")

        self.assertIs(raised.exception, error)


class GroupPlayerContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_users_in_same_group_get_distinct_accounts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            database = Database(str(Path(temp_dir) / "group-test.sqlite3"))
            await database.initialize()
            context = SimpleNamespace(
                application=SimpleNamespace(bot_data={"database": database})
            )
            chat = SimpleNamespace(id=-100123)
            message = object()
            first_user = SimpleNamespace(id=101, username="first", is_bot=False)
            second_user = SimpleNamespace(id=202, username="second", is_bot=False)

            first = await player_context(
                SimpleNamespace(
                    effective_user=first_user,
                    effective_chat=chat,
                    effective_message=message,
                ),
                context,
            )
            second = await player_context(
                SimpleNamespace(
                    effective_user=second_user,
                    effective_chat=chat,
                    effective_message=message,
                ),
                context,
            )

            self.assertEqual(first[0].id, 101)
            self.assertEqual(second[0].id, 202)
            self.assertEqual(first[1].id, second[1].id)
            first_player = await database.get_player(first[0].id)
            second_player = await database.get_player(second[0].id)
            self.assertEqual(first_player["user_id"], 101)
            self.assertEqual(second_player["user_id"], 202)
            self.assertNotEqual(first_player["user_id"], second_player["user_id"])

    async def test_non_chat_or_bot_updates_are_not_player_commands(self) -> None:
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"database": AsyncMock()})
        )
        missing_chat = await player_context(
            SimpleNamespace(
                effective_user=SimpleNamespace(id=1, username="user", is_bot=False),
                effective_chat=None,
                effective_message=object(),
            ),
            context,
        )
        bot_user = await player_context(
            SimpleNamespace(
                effective_user=SimpleNamespace(id=2, username="bot", is_bot=True),
                effective_chat=SimpleNamespace(id=-1),
                effective_message=object(),
            ),
            context,
        )
        self.assertIsNone(missing_chat)
        self.assertIsNone(bot_user)


if __name__ == "__main__":
    unittest.main()
