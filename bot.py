"""Telegram entry point for Rabza Jugg Bot."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import cast

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
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
from game import BAIL_COST, VEHICLES, prison_deadline, resolve_action

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def edit_callback_message(query: CallbackQuery, text: str) -> None:
    """Edit the callback's message and tolerate Telegram's no-op response only."""
    try:
        await query.edit_message_text(text, reply_markup=None)
    except BadRequest as error:
        if "message is not modified" not in str(error).lower():
            raise
        logger.debug("Telegram message already contains the requested text.")


def database_for(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return cast(Database, context.application.bot_data["database"])


async def post_init(application: Application) -> None:
    database = Database(DATABASE_PATH)
    await database.initialize()
    application.bot_data["database"] = database


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return

    await database_for(context).ensure_player(user.id, user.username)
    await message.reply_text(
        "Wesh l'équipe, bienvenue sur le Rabza Jugg Bot! "
        "Montréal t'attend: gamos, kichta et décisions douteuses — "
        "tout ça dans un jeu fictif, c'est carré. T'as 500$ pour commencer.\n\n"
        "Tape /profil pour checker ton statut ou /jugg pour choisir ton move."
    )


async def profil(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return
    database = database_for(context)
    await database.ensure_player(user.id, user.username)
    player = await database.get_player(user.id)
    if player is None:
        raise RuntimeError(
            f"Le joueur {user.id} est introuvable après son enregistrement."
        )

    prison_until = player["in_prison_until"]
    if prison_until:
        until = datetime.fromisoformat(prison_until)
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        remaining = until - datetime.now(timezone.utc)
        if remaining.total_seconds() > 0:
            minutes = max(1, int((remaining.total_seconds() + 59) // 60))
            status = f"En taule à Bordeaux/RDP — encore {minutes} min"
        else:
            status = "Libre (ta peine est finie, c'est carré)"
    else:
        status = "Libre"

    await message.reply_text(
        f"📍 Profil de {user.first_name}\n"
        f"💵 Kob: {player['cash']}$\n"
        f"🚘 Gamos: {player['gamos']}\n"
        f"🔥 Heat: {player['heat']}/100\n"
        f"🚔 Statut: {status}"
    )


async def jugg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return
    await database_for(context).ensure_player(user.id, user.username)

    keyboard = [
        [
            InlineKeyboardButton("Jugg un RAV4", callback_data="steal_rav4"),
            InlineKeyboardButton("Jugg un CR-V", callback_data="steal_crv"),
        ],
        [InlineKeyboardButton("Jugg un Dodge TRX", callback_data="steal_trx")],
        [InlineKeyboardButton("Coup Marketplace", callback_data="marketplace")],
        [InlineKeyboardButton("Petit move à Berri-UQAM", callback_data="berri")],
    ]
    await message.reply_text(
        "Choisis ton move, chef. Chaque action est un mini-jeu fictif — "
        "pas un guide pour la vraie vie:",
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

    action = query.data
    allowed_actions = {f"steal_{key}" for key in VEHICLES} | {
        "marketplace",
        "berri",
    }
    if action not in allowed_actions:
        await edit_callback_message(query, "Ce move-là n'existe pas, chef.")
        return

    database = database_for(context)
    await database.ensure_player(user.id, user.username)

    if action.startswith("steal_"):
        vehicle_key = action.removeprefix("steal_")
        vehicle_name = VEHICLES[vehicle_key][0]
        suspense_message = (
            f"🚘 Tu forces la porte du {vehicle_name}... "
            "🔌 Tentative de piratage de la prise OBD..."
        )
    elif action == "marketplace":
        suspense_message = (
            "📦 Tu donnes rendez-vous à la station Radisson... "
            "Tu guettes si y a des condés..."
        )
    else:
        suspense_message = (
            "❄️ Tu te poses à la sortie du métro Berri... "
            "Tu surveilles les agents STM..."
        )

    await edit_callback_message(query, suspense_message)
    await asyncio.sleep(2)

    result = resolve_action(action)
    prison_until = (
        prison_deadline(result.prison_minutes)
        if result.prison_minutes is not None
        else None
    )
    applied = await database.apply_action_result(
        user.id,
        result.cash_delta,
        result.heat_delta,
        result.gamos,
        prison_until,
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
        f"{result.message}\n\nPour voir tes stats: /profil"
    )


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    players = await database_for(context).get_top_players()
    if not players:
        await message.reply_text("Y'a personne dans le classement pour l'instant.")
        return

    lines = ["🏆 Top 10 des plus grosses kichtas de Montréal:"]
    for rank, player in enumerate(players, start=1):
        username = player["username"] or "Joueur sans blaze"
        lines.append(f"{rank}. {username} — {player['cash']}$")
    await message.reply_text("\n".join(lines))


async def prison(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return
    database = database_for(context)
    await database.ensure_player(user.id, user.username)
    player = await database.get_player(user.id)
    if player is None:
        raise RuntimeError(
            f"Le joueur {user.id} est introuvable après son enregistrement."
        )
    prison_until = player["in_prison_until"]
    if not prison_until:
        await message.reply_text("T'es libre, chef. Pas de cellule pour toi, c'est carré.")
        return

    until = datetime.fromisoformat(prison_until)
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    remaining = until - datetime.now(timezone.utc)
    if remaining.total_seconds() <= 0:
        await message.reply_text(
            "Ta peine est finie, t'es libre! Retour dans les rues de Montréal."
        )
        return

    minutes = max(1, int((remaining.total_seconds() + 59) // 60))
    keyboard = [
        [
            InlineKeyboardButton(
                f"Payer la caution ({BAIL_COST}$)",
                callback_data="pay_bail",
            )
        ]
    ]
    await message.reply_text(
        f"T'es encore à Bordeaux/RDP pour environ {minutes} min. "
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
    if user is None:
        return
    released = await database_for(context).pay_bail(user.id, BAIL_COST)
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
    application.add_handler(CommandHandler("top", top))
    application.add_handler(CommandHandler("prison", prison))
    application.add_handler(
        CallbackQueryHandler(
            handle_game_action, pattern=r"^(steal_|marketplace|berri)"
        )
    )
    application.add_handler(CallbackQueryHandler(pay_bail, pattern=r"^pay_bail$"))
    application.add_error_handler(error_handler)
    logger.info("Rabza Jugg Bot démarre.")
    application.run_polling()


if __name__ == "__main__":
    main()
