"""Telegram entry point for Rabza Jugg Bot."""

import asyncio
import logging
from datetime import datetime, timezone
import time
from typing import cast

from telegram import (
    CallbackQuery,
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
    User,
)
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from config import BOT_TOKEN, DATABASE_PATH, validate_config
from database import Database
from game import (
    ACTION_SPECS,
    BAIL_COST,
    ITEMS,
    MAX_LEVEL,
    PRISON_DURATION_SECONDS,
    SHOP_CATEGORIES,
    actions_available,
    item_by_id,
    prison_deadline,
    resolve_action,
    resolve_pvp,
    xp_to_next_level,
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def edit_callback_message(
    query: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Edit the callback's message and tolerate Telegram's no-op response only."""
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as error:
        if "message is not modified" not in str(error).lower():
            raise
        logger.debug("Telegram message already contains the requested text.")


def database_for(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return cast(Database, context.application.bot_data["database"])


async def player_context(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple[User, Chat, Message] | None:
    """Resolve this group/private-chat actor and ensure their user-id account."""
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    if user is None or chat is None or message is None or user.is_bot:
        return None

    await database_for(context).ensure_player(user.id, user.username, chat.id)
    return user, chat, message


def owned_callback_payload(
    data: str | None,
    namespace: str,
    user_id: int,
) -> str | None:
    """Return a callback payload only for the player who opened its menu."""
    if data is None:
        return None
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != namespace:
        return None
    try:
        owner_id = int(parts[1])
    except ValueError:
        return None
    return parts[2] if owner_id == user_id else None


def prison_remaining_seconds(player: dict[str, object]) -> int:
    """Return the remaining whole seconds until the Unix jail deadline."""
    end_time = player.get("in_prison_until")
    if not end_time:
        return 0
    if isinstance(end_time, str):
        try:
            end_time = float(end_time)
        except ValueError:
            legacy_datetime = datetime.fromisoformat(end_time)
            if legacy_datetime.tzinfo is None:
                legacy_datetime = legacy_datetime.replace(tzinfo=timezone.utc)
            end_time = legacy_datetime.timestamp()
    elif isinstance(end_time, datetime):
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        end_time = end_time.timestamp()
    if not isinstance(end_time, (int, float)):
        raise TypeError("in_prison_until doit être un timestamp Unix")
    return max(0, int(end_time - time.time()))


async def post_init(application: Application) -> None:
    database = Database(DATABASE_PATH)
    await database.initialize()
    application.bot_data["database"] = database


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    actor = await player_context(update, context)
    if actor is None:
        return
    message = actor[2]
    await message.reply_text(
        "Wesh l'équipe, bienvenue sur le Rabza Jugg Bot! "
        "Montréal t'attend: gamos, kichta et décisions douteuses — "
        "tout ça dans un jeu fictif, c'est carré. T'as 500$ pour commencer.\n\n"
        "Tape /profil pour checker ton statut ou /jugg pour choisir ton move."
    )


async def profil(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    actor = await player_context(update, context)
    if actor is None:
        return
    user, chat, message = actor
    database = database_for(context)
    player = await database.get_player(user.id, chat.id)
    if player is None:
        raise RuntimeError(
            f"Le joueur {user.id} est introuvable après son enregistrement."
        )

    remaining_seconds = prison_remaining_seconds(player)
    if remaining_seconds:
        status = f"En taule à Bordeaux/RDP — encore {remaining_seconds} s"
    elif player["in_prison_until"]:
        status = "Libre (ta peine est finie, c'est carré)"
    else:
        status = "Libre"

    await message.reply_text(
        f"📍 Profil de {user.first_name}\n"
        f"💵 Kob: {player['cash']}$\n"
        f"🚘 Gamos: {player['gamos']}\n"
        f"🔥 Heat: {player['heat']}/100\n"
        f"⭐ Rang MTL: niveau {player['level']}/{MAX_LEVEL}\n"
        f"✨ XP: {player['xp']} (prochain niveau: "
        f"{xp_to_next_level(player['xp'], player['level'])} XP)\n"
        f"🚔 Statut: {status}"
    )


async def jugg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    actor = await player_context(update, context)
    if actor is None:
        return
    user, chat, message = actor

    database = database_for(context)
    player = await database.get_player(user.id, chat.id)
    effects = await database.get_item_effects(user.id, chat.id)
    if player is None:
        raise RuntimeError(f"Le joueur {user.id} est introuvable après son enregistrement.")
    jail_seconds = prison_remaining_seconds(player)
    if jail_seconds:
        await message.reply_text(
            f"T'es encore à Bordeaux/RDP pour {jail_seconds} seconde(s). "
            "Réessaie quand le compteur tombe à zéro."
        )
        return
    available = actions_available(player["level"], bool(effects["has_obd"]))
    keyboard = [
        [
            InlineKeyboardButton(
                spec.title,
                callback_data=f"game:{user.id}:{action_id}",
            )
        ]
        for action_id, spec in available
    ]
    locked_specs = [
        spec for spec in ACTION_SPECS.values()
        if player["level"] < spec.min_level
        or (spec.requires_obd and not effects["has_obd"])
    ]
    if locked_specs:
        keyboard.append(
            [
                InlineKeyboardButton(
                    "🔒 Débloque d'autres moves: /profil et /shop",
                    callback_data=f"game:{user.id}:locked",
                )
            ]
        )
    await message.reply_text(
        f"Choisis ton défi d'arcade, chef — niveau {player['level']}. "
        "Les moves sont fictifs et abstraits:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_game_action(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    user = update.effective_user
    if user is None:
        return
    action = owned_callback_payload(query.data, "game", user.id)
    if action is None:
        return
    actor = await player_context(update, context)
    if actor is None:
        return
    user, chat = actor[0], actor[1]

    allowed_actions = set(ACTION_SPECS)
    if action not in allowed_actions:
        await edit_callback_message(query, "Ce move-là n'existe pas, chef.")
        return

    database = database_for(context)
    player = await database.get_player(user.id, chat.id)
    effects = await database.get_item_effects(user.id, chat.id)
    if player is None:
        raise RuntimeError(f"Le joueur {user.id} est introuvable.")
    spec = ACTION_SPECS[action]
    jail_seconds = prison_remaining_seconds(player)
    if jail_seconds:
        await edit_callback_message(
            query,
            f"T'es encore à Bordeaux/RDP pour {jail_seconds} seconde(s). "
            "Réessaie quand le compteur tombe à zéro.",
        )
        return
    if player["level"] < spec.min_level:
        await edit_callback_message(
            query,
            f"Move verrouillé: niveau {spec.min_level} requis; "
            f"t'es niveau {player['level']}. Continue à gagner de l'XP.",
        )
        return
    if spec.requires_obd and not effects["has_obd"]:
        await edit_callback_message(
            query, "Le défi gamos est verrouillé: le boîtier OBD fictif est requis. /shop"
        )
        return

    suspense_message = f"🎮 Défi d'arcade en cours: {spec.title}... Le suspense est à son max."

    await edit_callback_message(query, suspense_message)
    await asyncio.sleep(2)

    result = resolve_action(
        action,
        success_bonus=float(effects["success_bonus"]),
    )
    xp_gain = (
        result.xp_gain
        + (result.xp_gain * int(effects["xp_bonus"]) // 100)
        if result.success
        else 0
    )
    prison_until = (
        prison_deadline(result.prison_seconds)
        if result.prison_seconds is not None
        else None
    )
    applied = await database.apply_action_result(
        user.id,
        result.cash_delta,
        result.heat_delta,
        result.gamos,
        prison_until,
        xp_gain,
        chat_id=chat.id,
    )
    if not applied:
        await edit_callback_message(
            query,
            "T'es déjà en taule à Bordeaux/RDP, chef. "
            "Check /prison avant de retenter un jugg."
        )
        return
    await edit_callback_message(
        query,
        f"{result.message}"
        + (f"\nBonus de sapes inclus; +{xp_gain} XP total." if result.success else "")
        + "\n\nPour voir tes stats: /profil"
    )


async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    actor = await player_context(update, context)
    if actor is None:
        return
    user, message = actor[0], actor[2]
    keyboard = [
        [
            InlineKeyboardButton(
                category.title(), callback_data=f"shop:{user.id}:{category}"
            )
        ]
        for category in SHOP_CATEGORIES
    ]
    await message.reply_text(
        "🛍️ Marketplace MTL — items fictifs, effets de jeu uniquement. "
        "Choisis une catégorie:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    user = update.effective_user
    if user is None:
        return
    data = query.data or ""
    if data.startswith("buy:"):
        payload = owned_callback_payload(data, "buy", user.id)
    else:
        payload = owned_callback_payload(data, "shop", user.id)
    if payload is None:
        return
    actor = await player_context(update, context)
    if actor is None:
        return
    user, chat = actor[0], actor[1]
    database = database_for(context)

    if data.startswith("shop:") and payload != "home":
        category = payload
        if category not in SHOP_CATEGORIES:
            await edit_callback_message(query, "Cette catégorie n'existe pas.")
            return
        player = await database.get_player(user.id, chat.id)
        if player is None:
            raise RuntimeError(f"Le joueur {user.id} est introuvable.")
        category_items = [item for item in ITEMS if item.category == category]
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{item.name} — {item.price}$ (niv. {item.min_level})",
                    callback_data=f"buy:{user.id}:{item.item_id}",
                )
            ]
            for item in category_items
        ]
        keyboard.append(
            [InlineKeyboardButton("↩️ Catégories", callback_data=f"shop:{user.id}:home")]
        )
        await edit_callback_message(
            query,
            f"{SHOP_CATEGORIES[category]} | Ton niveau: {player['level']} | "
            f"Kob: {player['cash']}$",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith("shop:") and payload == "home":
        keyboard = [
            [
                InlineKeyboardButton(
                    category.title(), callback_data=f"shop:{user.id}:{category}"
                )
            ]
            for category in SHOP_CATEGORIES
        ]
        await edit_callback_message(
            query,
            "Marketplace MTL: choisis une catégorie.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith("buy:"):
        item_id = payload
        item = item_by_id(item_id)
        if item is None:
            await edit_callback_message(query, "Cet item n'existe pas.")
            return
        outcome = await database.purchase_item(user.id, item_id, chat.id)
        if outcome == "ok":
            player = await database.get_player(user.id, chat.id)
            text = (
                f"✅ {item.name} ajouté à ton inventaire! "
                f"Kob restant: {player['cash']}$."
            )
        elif outcome == "level":
            text = f"Niveau {item.min_level} requis pour {item.name}."
        elif outcome == "cash":
            text = f"Pas assez de kob pour {item.name}."
        else:
            text = "Achat impossible: joueur ou item introuvable."
        await edit_callback_message(
            query,
            text,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            f"↩️ {SHOP_CATEGORIES[item.category]}",
                            callback_data=f"shop:{user.id}:{item.category}",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "Toutes les catégories",
                            callback_data=f"shop:{user.id}:home",
                        )
                    ],
                ]
            ),
        )
        return

    await edit_callback_message(query, "Action de marketplace invalide.")


async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    actor = await player_context(update, context)
    if actor is None:
        return
    user, chat, message = actor
    database = database_for(context)
    items = await database.get_inventory(user.id, chat.id)
    if not items:
        await message.reply_text("Ton inventaire est vide. Fais /shop pour magasiner.")
        return

    categories: dict[str, list[str]] = {}
    for item in items:
        categories.setdefault(item["category"], []).append(
            f"• {item['name']} ×{item['quantity']}"
        )
    lines = ["🎒 Inventaire MTL (effets fictifs):"]
    for category, entries in categories.items():
        lines.append(f"\n{SHOP_CATEGORIES.get(category, category.title())}:")
        lines.extend(entries)

    effects = await database.get_item_effects(user.id, chat.id)
    lines.append(f"\nBonus XP max des sapes: +{effects['xp_bonus']}%")
    lines.append(f"Bonus de réussite abstrait: +{effects['success_bonus']:.0%}")
    lines.append(
        "Boîtier OBD de jeu: "
        + ("oui" if effects["has_obd"] else "non")
    )
    await message.reply_text("\n".join(lines))


async def braquer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    actor = await player_context(update, context)
    if actor is None:
        return
    user, chat, message = actor
    if chat.type not in {"group", "supergroup"}:
        await message.reply_text(
            "❌ Les braquages entre joueurs se font uniquement dans les groupes !"
        )
        return
    database = database_for(context)
    attacker = await database.get_player(user.id, chat.id)
    if attacker is None:
        raise RuntimeError(f"Le joueur {user.id} est introuvable.")
    jail_seconds = prison_remaining_seconds(attacker)
    if jail_seconds:
        await message.reply_text(
            f"T'es encore à Bordeaux pour {jail_seconds} seconde(s). "
            "Le défi PVP sera dispo quand ta peine sera finie."
        )
        return
    if attacker["level"] < 20:
        await message.reply_text("Le défi PVP est verrouillé jusqu'au niveau 20.")
        return
    if len(context.args) != 1 or not context.args[0].startswith("@"):
        await message.reply_text("Usage: /braquer @username (défi fictif entre joueurs)")
        return

    victim = await database.get_player_by_username(context.args[0], chat.id)
    if victim is None:
        await message.reply_text(
            "Joueur introuvable. Il doit avoir lancé /start et avoir un username Telegram."
        )
        return
    if victim["user_id"] == user.id:
        await message.reply_text("Tu peux pas lancer un défi contre toi-même.")
        return

    attacker_effects = await database.get_item_effects(user.id, chat.id)
    victim_effects = await database.get_item_effects(victim["user_id"], chat.id)
    result = resolve_pvp(
        attacker_has_weapon=bool(attacker_effects["has_weapon"]),
        victim_has_weapon=bool(victim_effects["has_weapon"]),
    )
    deadline = (
        prison_deadline(result.prison_seconds)
        if result.prison_seconds
        else None
    )
    applied = await database.apply_pvp_result(
        user.id,
        victim["user_id"],
        result.outcome,
        result.fine,
        deadline,
        result.xp_gain,
        result.transfer_rate,
        chat_id=chat.id,
    )
    if applied is None:
        await message.reply_text("Défi PVP impossible: cible invalide.")
    elif applied["status"] == "level":
        await message.reply_text("Le défi PVP est réservé aux joueurs niveau 20+.")
    elif applied["status"] == "prison":
        await message.reply_text("T'es en taule; aucun défi PVP possible pour le moment.")
    elif applied["status"] == "counter":
        await message.reply_text(
            f"💥 Riposte de jeu! @{victim['username']} bloque le braquage avec "
            f"son équipement ({victim_effects['weapon_name']}). "
            f"Tu prends {PRISON_DURATION_SECONDS} secondes à Bordeaux et verses "
            f"{applied['fine']}$ à "
            f"@{victim['username']}."
        )
    elif applied["status"] == "success":
        await message.reply_text(
            f"🎯 Tu as braqué @{victim['username']} dans le jeu et tu es reparti "
            f"avec {applied['amount']}$ ({applied['rate']:.0%} du cash) ! "
            f"+{applied['xp']} XP. Niveau actuel: {applied['level']}."
        )
    else:
        await message.reply_text(
            f"{result.message} Direction Bordeaux pour {PRISON_DURATION_SECONDS} secondes. "
            "Aucun cash n'a changé de mains."
        )


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    actor = await player_context(update, context)
    if actor is None:
        return
    chat, message = actor[1], actor[2]
    players = await database_for(context).get_top_players(chat_id=chat.id)
    if not players:
        await message.reply_text("Y'a personne dans le classement pour l'instant.")
        return

    lines = ["🏆 Top 10 des plus grosses kichtas de Montréal:"]
    for rank, player in enumerate(players, start=1):
        username = player["username"] or "Joueur sans blaze"
        lines.append(f"{rank}. {username} — {player['cash']}$")
    await message.reply_text("\n".join(lines))


async def prison(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    actor = await player_context(update, context)
    if actor is None:
        return
    user, chat, message = actor
    database = database_for(context)
    player = await database.get_player(user.id, chat.id)
    if player is None:
        raise RuntimeError(
            f"Le joueur {user.id} est introuvable après son enregistrement."
        )
    prison_until = player["in_prison_until"]
    remaining_seconds = prison_remaining_seconds(player)
    if not prison_until:
        await message.reply_text("T'es libre, chef. Pas de cellule pour toi, c'est carré.")
        return

    if remaining_seconds <= 0:
        await message.reply_text(
            "Ta peine est finie, t'es libre! Retour dans les rues de Montréal."
        )
        return

    keyboard = [
        [
            InlineKeyboardButton(
                f"Payer la caution ({BAIL_COST}$)",
                callback_data=f"bail:{user.id}:pay",
            )
        ]
    ]
    await message.reply_text(
        f"T'es encore à Bordeaux/RDP pour {remaining_seconds} seconde(s). "
        f"T'as {player['cash']}$; la caution coûte {BAIL_COST}$. "
        "La patience ou la kichta, à toi de voir.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def pay_bail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    user = update.effective_user
    if user is None or owned_callback_payload(query.data, "bail", user.id) != "pay":
        return
    actor = await player_context(update, context)
    if actor is None:
        return
    user, chat = actor[0], actor[1]
    released = await database_for(context).pay_bail(
        user.id, BAIL_COST, chat.id
    )
    if released:
        await edit_callback_message(
            query,
            f"Caution payée: -{BAIL_COST}$. T'es libre, c'est carré. "
            "Va checker ton kob avec /profil."
        )
    else:
        await edit_callback_message(
            query,
            "La caution peut pas passer: soit ta peine est finie, "
            "soit t'as pas assez de kob. Check /prison et /profil."
        )


async def error_handler(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    logger.error(
        "Erreur inattendue lors du traitement de la mise à jour",
        exc_info=context.error,
    )
    if isinstance(update, Update) and update.effective_message is not None:
        await update.effective_message.reply_text(
            "Oups, le bot a eu un pépin. Réessaie dans un instant."
        )


def main() -> None:
    validate_config()
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("profil", profil))
    application.add_handler(CommandHandler("jugg", jugg))
    application.add_handler(CommandHandler("shop", shop))
    application.add_handler(CommandHandler("inventory", inventory))
    application.add_handler(CommandHandler("braquer", braquer))
    application.add_handler(CommandHandler("top", top))
    application.add_handler(CommandHandler("prison", prison))
    application.add_handler(
        CallbackQueryHandler(
            handle_game_action,
            pattern=r"^game:",
        )
    )
    application.add_handler(
        CallbackQueryHandler(shop_callback, pattern=r"^(shop:|buy:)")
    )
    application.add_handler(CallbackQueryHandler(pay_bail, pattern=r"^bail:"))
    application.add_error_handler(error_handler)
    logger.info("Rabza Jugg Bot démarre.")
    application.run_polling()


if __name__ == "__main__":
    main()
