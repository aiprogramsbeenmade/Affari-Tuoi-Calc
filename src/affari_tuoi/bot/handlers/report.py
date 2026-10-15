"""
Handler per la generazione e l'invio del report PDF.
"""

from __future__ import annotations

import io

from telegram import Update
from telegram.ext import ContextTypes

from affari_tuoi.grafici.report import genera_report_pdf
from affari_tuoi.storage.db import Database
from affari_tuoi.storage.report_builder import costruisci_dati_report
from affari_tuoi.utils.logger import get_logger

_log = get_logger(__name__)


def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


async def invia_report(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Genera e invia il PDF del report della partita corrente.

    Chiamato dal callback `a:report`.
    """
    query = update.callback_query
    await query.answer("📋 Genero il report...")

    partita_id = context.user_data.get("partita_id")
    if partita_id is None:
        await query.edit_message_text(
            "⚠️ Nessuna partita da refertare."
        )
        return

    # Genera il report
    try:
        dati = costruisci_dati_report(_db(context), partita_id)
        if dati is None:
            await query.edit_message_text(
                "⚠️ Partita non trovata nel database."
            )
            return

        pdf_bytes = genera_report_pdf(dati)
    except Exception as e:
        _log.exception("Errore generazione report")
        await query.edit_message_text(
            f"❌ Errore durante la generazione del report: {e}"
        )
        return

    # Invia il PDF
    filename = f"affari_tuoi_partita_{partita_id}.pdf"
    try:
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=io.BytesIO(pdf_bytes),
            filename=filename,
            caption=(
                f"📋 Report della partita\n"
                f"Premio finale: {dati.premio_finale:,} EUR"
            ),
        )
        _log.info("Report inviato per partita %s", partita_id)
    except Exception as e:
        _log.exception("Errore invio report")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"❌ Errore durante l'invio: {e}",
        )


__all__ = ["invia_report"]