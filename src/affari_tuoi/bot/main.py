"""
Entry point del bot Telegram.

Avvio:
    python -m affari_tuoi.bot.main

oppure, da script dedicato:
    python scripts/run_bot.py
"""

from __future__ import annotations

import logging

from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from affari_tuoi.storage.db import Database
from affari_tuoi.utils.config import carica_config
from affari_tuoi.utils.logger import configura_logging, get_logger

from affari_tuoi.bot.handlers import start as handler_start
from affari_tuoi.bot.handlers import gioco as handler_gioco
from telegram.request import HTTPXRequest

_log = get_logger(__name__)


def costruisci_application() -> Application:
    """
    Costruisce e configura l'Application di python-telegram-bot.

    Registra tutti gli handler e prepara il DB condiviso.
    """
    config = carica_config()
    configura_logging(config.log_level)

    _log.info("Avvio bot Affari Tuoi")

    # DB condiviso in bot_data
    db = Database(config.db_path)
    db.inizializza()

    # Timeout generosi: la rete può essere lenta o il server Telegram
    # può rispondere con latenza variabile.
    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )

    application = (
        ApplicationBuilder()
        .token(config.telegram_bot_token)
        .request(request)
        .get_updates_request(request)
        .build()
    )
    application.bot_data["config"] = config
    application.bot_data["db"] = db

    # --- Comandi base ---
    application.add_handler(CommandHandler("start", handler_start.cmd_start))
    application.add_handler(CommandHandler("help", handler_start.cmd_help))
    application.add_handler(CommandHandler("reset_db", handler_start.cmd_reset_db))
    application.add_handler(CommandHandler("stats", handler_start.cmd_stats))

    # --- Gioco ---
    application.add_handler(CommandHandler("new", handler_gioco.cmd_new))
    application.add_handler(CommandHandler("annulla", handler_gioco.cmd_annulla))
    application.add_handler(CommandHandler("termina", handler_gioco.cmd_termina))

    # --- Callback inline (bottoni) ---
    application.add_handler(
        CallbackQueryHandler(
            handler_start.on_reset_db_conferma, pattern=r"^reset_db:"
        )
    )
    application.add_handler(
        CallbackQueryHandler(handler_gioco.on_callback_pacco, pattern=r"^p:")
    )
    application.add_handler(
        CallbackQueryHandler(handler_gioco.on_callback_azione, pattern=r"^a:")
    )

    # --- Messaggi di testo (per importo offerta) ---
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handler_gioco.on_testo)
    )
    application.add_handler(
        CallbackQueryHandler(handler_gioco.on_callback_azione, pattern=r"^a:")
    )

    _log.info("Bot configurato, avvio polling")
    return application

def main() -> None:
    """Avvia il bot in polling."""
    application = costruisci_application()
    application.run_polling(
        drop_pending_updates=True,
        bootstrap_retries=5,  # riprova fino a 5 volte se l'avvio fallisce
    )


if __name__ == "__main__":
    main()