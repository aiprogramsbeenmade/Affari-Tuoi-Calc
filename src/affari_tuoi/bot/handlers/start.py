"""
Handler dei comandi base: /start, /help, /reset_db, /stats.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from affari_tuoi.storage.db import Database
from affari_tuoi.utils.config import Config
from affari_tuoi.utils.logger import get_logger

_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Utility interne
# ---------------------------------------------------------------------------

def _config(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.application.bot_data["config"]


def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

async def cmd_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Messaggio di benvenuto."""
    user = update.effective_user
    nome = user.first_name if user else "ospite"

    testo = (
        f"👋 Ciao {nome}!\n\n"
        "Sono il tuo assistente per *Affari Tuoi*. "
        "Posso aiutarti in due modi:\n\n"
        "🎮 *Gioca insieme a me*\n"
        "Usa /new mentre guardi la puntata: ti dico in tempo reale "
        "EV, probabilità e consigli su offerte e cambio.\n\n"
        "📊 *Analizza una partita*\n"
        "Sempre con /new: apri i pacchi man mano che escono in TV "
        "e ricevi i numeri aggiornati.\n\n"
        "📋 *Comandi disponibili*\n"
        "• /new — Inizia una nuova partita\n"
        "• /annulla — Annulla l'ultima apertura\n"
        "• /termina — Chiudi la partita corrente\n"
        "• /stats — Statistiche delle tue partite\n"
        "• /help — Questo messaggio\n\n"
        "Buona fortuna! 🍀"
    )

    await update.message.reply_text(testo, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------

async def cmd_help(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Guida ai comandi."""
    testo = (
        "📖 *Guida rapida*\n\n"
        "*Come funziona*\n"
        "1. Avvia la partita con /new\n"
        "2. Ogni volta che in TV esce un pacco, toccalo nel bot\n"
        "3. Il bot ricalcola EV, probabilità e soglie\n"
        "4. Quando il Dottore fa un'offerta, premi 💰 e inseriscila\n"
        "5. Con 2 pacchi rimasti, il bot attiva la modalità cambio\n\n"
        "*Comandi principali*\n"
        "• /new — Nuova partita\n"
        "• /annulla — Annulla l'ultima apertura\n"
        "• /termina — Concludi la partita\n"
        "• /stats — Statistiche personali\n"
        "• /reset\\_db — Cancella tutto il DB (solo admin)\n\n"
        "*Suggerimento*\n"
        "I consigli mostrati durante la partita sono basati su "
        "calcoli probabilistici. Non esiste una strategia "
        "migliore in assoluto: dipende dalla tua propensione al rischio."
    )
    await update.message.reply_text(testo, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /reset_db (con conferma)
# ---------------------------------------------------------------------------

async def cmd_reset_db(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Chiede conferma prima di resettare il DB."""
    user = update.effective_user
    config = _config(context)

    if user is None or not config.is_admin(user.id):
        await update.message.reply_text(
            "⛔ Comando riservato all'amministratore."
        )
        _log.warning("Tentativo /reset_db non autorizzato da user=%s", user.id if user else None)
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Sì, cancella tutto", callback_data="reset_db:sì"),
            InlineKeyboardButton("❌ No, annulla", callback_data="reset_db:no"),
        ]
    ])

    await update.message.reply_text(
        "⚠️ *Attenzione*\n\n"
        "Stai per cancellare *tutte* le partite e gli eventi dal DB.\n"
        "L'operazione è irreversibile.\n\n"
        "Confermi?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def on_reset_db_conferma(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Callback dei bottoni di conferma reset DB."""
    query = update.callback_query
    await query.answer()

    if query.data == "reset_db:sì":
        db = _db(context)
        db.reset()
        await query.edit_message_text("✅ DB resettato. Tutte le partite sono state cancellate.")
        _log.warning("DB resettato da user=%s", update.effective_user.id if update.effective_user else None)
    else:
        await query.edit_message_text("❌ Operazione annullata.")


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------

async def cmd_stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Statistiche aggregate delle partite dell'utente."""
    user = update.effective_user
    if user is None:
        return

    db = _db(context)
    stats = db.statistiche_globali(user_id=user.id)

    if stats["n"] == 0:
        await update.message.reply_text(
            "📊 Non hai ancora completato nessuna partita.\n"
            "Usa /new per iniziarne una!"
        )
        return

    testo = (
        "📊 *Le tue statistiche*\n\n"
        f"Partite concluse: *{stats['n']}*\n"
        f"Premio medio: *{stats['media']:,.0f}* EUR\n"
        f"Premio minimo: *{stats['minimo']:,}* EUR\n"
        f"Premio massimo: *{stats['massimo']:,}* EUR\n\n"
        "*Come sono finite le partite*\n"
        f"• Accettando un'offerta: {stats['n_offerte']}\n"
        f"• Accettando il cambio: {stats['n_cambi']}\n"
        f"• Tenendo il pacco fino alla fine: {stats['n_pacchi']}"
    )
    await update.message.reply_text(testo, parse_mode="Markdown")


__all__ = [
    "cmd_start",
    "cmd_help",
    "cmd_reset_db",
    "on_reset_db_conferma",
    "cmd_stats",
]