"""Fictional, chance-based game mechanics."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import random


@dataclass(frozen=True)
class GameResult:
    message: str
    cash_delta: int
    heat_delta: int
    gamos: str | None = None
    prison_minutes: int | None = None


VEHICLES = {
    "rav4": ("RAV4", 350, 12),
    "crv": ("Honda CR-V", 450, 16),
    "trx": ("Dodge TRX", 700, 22),
}

BAIL_COST = 300
STEAL_SUCCESS_CHANCE = 0.60
MARKETPLACE_SUCCESS_CHANCE = 0.75
BERRI_SUCCESS_CHANCE = 0.80


def resolve_action(action: str, roll: float | None = None) -> GameResult:
    """Resolve a single fictional game action; roll supports deterministic tests."""
    chance = random.random() if roll is None else roll
    if not 0 <= chance < 1:
        raise ValueError("roll doit être compris entre 0 inclus et 1 exclu")

    if action.startswith("steal_"):
        vehicle_key = action.removeprefix("steal_")
        if vehicle_key not in VEHICLES:
            raise ValueError(f"Gamos inconnu: {vehicle_key}")
        name, reward, heat = VEHICLES[vehicle_key]
        if chance < STEAL_SUCCESS_CHANCE:
            return GameResult(
                f"Masterclass, le {name} est dans ton garage. +{reward}$ et +{heat} heat. C'est carré.",
                reward,
                heat,
                gamos=name,
            )
        return GameResult(
            f"Aïe, le SPVM t'a pé té sur le fait. Direction Bordeaux/RDP pour 1 heure, kob confisqué? Non, mais ça attendra.",
            0,
            15,
            prison_minutes=60,
        )

    if action == "marketplace":
        if chance < MARKETPLACE_SUCCESS_CHANCE:
            return GameResult(
                "La fausse Moose est partie sur Marketplace. Kichta de +250$, +8 heat. Le client trouve ça carré.",
                250,
                8,
            )
        return GameResult(
            "Le client a capté le move, le SPVM débarque: 30 minutes à Bordeaux/RDP et -75$ de frais.",
            -75,
            10,
            prison_minutes=30,
        )

    if action == "berri":
        if chance < BERRI_SUCCESS_CHANCE:
            return GameResult(
                "Petit gain fictif à Berri-UQAM: +120$ et +5 heat. Pas de recette ni de vrai plan, juste le jeu.",
                120,
                5,
            )
        return GameResult(
            "La chance a tourné à Berri-UQAM: 20 minutes à Bordeaux/RDP et +8 heat.",
            0,
            8,
            prison_minutes=20,
        )

    raise ValueError(f"Action inconnue: {action}")


def prison_deadline(minutes: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)
