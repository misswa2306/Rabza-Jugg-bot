import unittest
from unittest.mock import AsyncMock

from telegram.error import BadRequest

from bot import edit_callback_message


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


if __name__ == "__main__":
    unittest.main()
