import unittest
from unittest.mock import patch

from game import resolve_action


class ResolveActionTests(unittest.TestCase):
    def test_vehicle_success_awards_cash_heat_and_car(self) -> None:
        result = resolve_action("steal_rav4", roll=0.49)
        self.assertEqual(result.cash_delta, 350)
        self.assertEqual(result.heat_delta, 12)
        self.assertEqual(result.gamos, "RAV4")
        self.assertIsNone(result.prison_minutes)

    def test_vehicle_failure_sends_player_to_prison(self) -> None:
        result = resolve_action("steal_trx", roll=0.6)
        self.assertEqual(result.cash_delta, 0)
        self.assertEqual(result.prison_minutes, 60)

    def test_vehicle_success_threshold_is_60_percent(self) -> None:
        self.assertEqual(resolve_action("steal_rav4", roll=0.599).cash_delta, 350)
        self.assertEqual(resolve_action("steal_rav4", roll=0.6).prison_minutes, 60)

    def test_marketplace_success_threshold_is_75_percent(self) -> None:
        self.assertEqual(resolve_action("marketplace", roll=0.749).cash_delta, 250)
        self.assertEqual(resolve_action("marketplace", roll=0.75).prison_minutes, 30)

    def test_berri_success_threshold_is_80_percent(self) -> None:
        self.assertEqual(resolve_action("berri", roll=0.799).cash_delta, 120)
        self.assertEqual(resolve_action("berri", roll=0.8).prison_minutes, 20)

    @patch("game.random.random", return_value=0.59)
    def test_default_roll_uses_random_module(self, random_roll) -> None:
        result = resolve_action("steal_rav4")
        random_roll.assert_called_once_with()
        self.assertEqual(result.cash_delta, 350)

    def test_unknown_action_and_invalid_roll_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve_action("unknown", roll=0.2)
        with self.assertRaises(ValueError):
            resolve_action("berri", roll=1)


if __name__ == "__main__":
    unittest.main()
