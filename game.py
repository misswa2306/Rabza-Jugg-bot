"""Fictional, non-instructional game mechanics and progression catalogue."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import random


MAX_LEVEL = 60
BAIL_COST = 300


@dataclass(frozen=True)
class GameResult:
    message: str
    cash_delta: int
    heat_delta: int
    gamos: str | None = None
    prison_minutes: int | None = None
    xp_gain: int = 0
    success: bool = False


@dataclass(frozen=True)
class ActionSpec:
    title: str
    min_level: int
    success_chance: float
    reward: int
    xp: int
    heat: int
    success_message: str
    failure_message: str
    prison_minutes: int
    high_tier: bool = False
    gamos: str | None = None
    requires_obd: bool = False


@dataclass(frozen=True)
class ShopItem:
    item_id: str
    name: str
    category: str
    price: int
    min_level: int
    xp_bonus: int = 0
    success_bonus: float = 0.0


@dataclass(frozen=True)
class PvpResult:
    outcome: str
    message: str
    prison_minutes: int = 0
    fine: int = 0
    xp_gain: int = 0
    transfer_rate: float = 0.0


ITEMS = (
    ShopItem("tech_fleece", "Tech Fleece", "sapes", 250, 1, xp_bonus=5),
    ShopItem("moose_knuckles", "Moose Knuckles", "sapes", 800, 10, xp_bonus=10),
    ShopItem("trapstar_bag", "Sacoche Trapstar", "sapes", 1500, 20, xp_bonus=15),
    ShopItem("bixi", "BIXI", "vehicules", 50, 1),
    ShopItem("lime_scooter", "Scooter Lime", "vehicules", 400, 10),
    ShopItem("civic_2008", "Civic 2008", "vehicules", 2500, 20),
    ShopItem("rav4", "RAV4", "vehicules", 15000, 35),
    ShopItem("urus", "Urus", "vehicules", 120000, 50),
    ShopItem("tear_gas", "Lacrymo", "armes", 150, 1, success_bonus=0.03),
    ShopItem("glock_19", "Glock 19", "armes", 3500, 20, success_bonus=0.08),
    ShopItem("ak_47", "AK-47", "armes", 12000, 35, success_bonus=0.15),
    ShopItem("bolt_cutter", "Coupe-boulon", "matos", 100, 1),
    ShopItem("obd_device", "Boîtier OBD Keyless", "matos", 4000, 20),
    ShopItem("gps_jammer", "Brouilleur GPS", "matos", 8000, 35),
)

SHOP_CATEGORIES = {
    "sapes": "Sapes",
    "vehicules": "Véhicules",
    "armes": "Armes",
    "matos": "Matos",
}


ACTION_SPECS = {
    "berri": ActionSpec(
        "Move fictif à Berri-UQAM", 1, 0.80, 120, 25, 5,
        "Petit gain de jeu à Berri-UQAM: +{reward}$ et +{xp} XP.",
        "La chance tourne: 20 minutes à Bordeaux/RDP.", 20,
    ),
    "bixi": ActionSpec(
        "Défi BIXI", 1, 0.65, 90, 30, 8,
        "Défi BIXI réussi dans le jeu: +{reward}$ et +{xp} XP.",
        "Le défi BIXI échoue: 15 minutes à Bordeaux/RDP.", 15,
    ),
    "dep": ActionSpec(
        "Défi dép de quartier", 10, 0.60, 220, 45, 12,
        "Défi du dép réussi dans le jeu: +{reward}$ et +{xp} XP.",
        "Le défi dérape: 30 minutes à Bordeaux/RDP.", 30,
    ),
    "marketplace": ActionSpec(
        "Défi Marketplace Radisson", 10, 0.75, 250, 50, 8,
        "Le deal fictif passe: +{reward}$ et +{xp} XP.",
        "Le deal échoue: 30 minutes à Bordeaux/RDP.", 30,
    ),
    "steal_rav4": ActionSpec(
        "Défi gamos RAV4", 20, 0.60, 350, 75, 12,
        "Défi RAV4 réussi dans le jeu: +{reward}$ et +{xp} XP.",
        "Le défi échoue: 60 minutes à Bordeaux/RDP.", 60,
        high_tier=True, gamos="RAV4", requires_obd=True,
    ),
    "steal_lexus": ActionSpec(
        "Défi gamos Lexus", 20, 0.52, 500, 85, 15,
        "Défi Lexus réussi dans le jeu: +{reward}$ et +{xp} XP.",
        "Le défi échoue: 60 minutes à Bordeaux/RDP.", 60,
        high_tier=True, gamos="Lexus", requires_obd=True,
    ),
    "jewelry": ActionSpec(
        "Défi Plaza St-Hubert", 35, 0.40, 1200, 120, 25,
        "Défi d'arcade Plaza réussi: +{reward}$ et +{xp} XP.",
        "Défi raté: 60 minutes à Bordeaux/RDP.", 60,
        high_tier=True,
    ),
    "port": ActionSpec(
        "Défi conteneur du Port", 50, 0.30, 2500, 160, 35,
        "Défi d'arcade du Port réussi: +{reward}$ et +{xp} XP.",
        "Défi raté: 60 minutes à Bordeaux/RDP.", 60,
        high_tier=True,
    ),
}


def level_for_xp(xp: int) -> int:
    """Each next level costs 100 × current level XP, capped at level 60."""
    if xp < 0:
        raise ValueError("XP ne peut pas être négatif")
    level = 1
    remaining = xp
    while level < MAX_LEVEL:
        required = 100 * level
        if remaining < required:
            break
        remaining -= required
        level += 1
    return level


def xp_to_next_level(xp: int, level: int) -> int:
    if level >= MAX_LEVEL:
        return 0
    return 100 * level - (xp - 50 * level * (level - 1))


def item_by_id(item_id: str) -> ShopItem | None:
    return next((item for item in ITEMS if item.item_id == item_id), None)


def actions_available(level: int, has_obd: bool) -> list[tuple[str, ActionSpec]]:
    return [
        (action_id, spec)
        for action_id, spec in ACTION_SPECS.items()
        if level >= spec.min_level and (has_obd or not spec.requires_obd)
    ]


def resolve_action(
    action: str,
    roll: float | None = None,
    success_bonus: float = 0.0,
) -> GameResult:
    """Resolve a fictional action without describing real-world methods."""
    spec = ACTION_SPECS.get(action)
    if spec is None:
        raise ValueError(f"Action inconnue: {action}")
    chance = random.random() if roll is None else roll
    if not 0 <= chance < 1:
        raise ValueError("roll doit être compris entre 0 inclus et 1 exclu")

    threshold = min(0.95, spec.success_chance + (success_bonus if spec.high_tier else 0))
    if chance < threshold:
        return GameResult(
            spec.success_message.format(reward=spec.reward, xp=spec.xp),
            spec.reward,
            spec.heat,
            gamos=spec.gamos,
            xp_gain=spec.xp,
            success=True,
        )
    return GameResult(
        spec.failure_message,
        0,
        spec.heat,
        prison_minutes=spec.prison_minutes,
    )


def resolve_pvp(
    attacker_has_weapon: bool,
    victim_has_weapon: bool,
    attack_roll: float | None = None,
    counter_roll: float | None = None,
    transfer_roll: float | None = None,
) -> PvpResult:
    """Resolve a fictional, non-violent player-versus-player contest."""
    attack = random.random() if attack_roll is None else attack_roll
    counter = random.random() if counter_roll is None else counter_roll
    transfer = random.random() if transfer_roll is None else transfer_roll
    if not all(0 <= roll < 1 for roll in (attack, counter, transfer)):
        raise ValueError("Les tirages doivent être compris entre 0 inclus et 1 exclu")

    if victim_has_weapon and counter < 0.60:
        return PvpResult(
            "counter",
            "Riposte fictive réussie: la victime bloque le braquage. "
            "Le braqueur prend 1 heure à Bordeaux et une amende de 500$ versée à la victime.",
            prison_minutes=60,
            fine=500,
        )
    success_chance = 0.50 + (0.15 if attacker_has_weapon else 0.0)
    if attack < success_chance:
        return PvpResult(
            "success",
            "Défi PVP remporté dans le jeu: le transfert de kob est appliqué.",
            xp_gain=70,
            transfer_rate=0.15 + 0.20 * transfer,
        )
    return PvpResult(
        "failed",
        "Le braquage fictif échoue; les condés interviennent. "
        "Aucun cash n'est transféré.",
        prison_minutes=30,
    )


def prison_deadline(minutes: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)
