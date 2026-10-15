"""
Handler del gioco interattivo.

Comandi:
- /new       inizia una nuova partita
- /annulla   annulla l'ultima apertura
- /termina   termina la partita corrente

Callback inline:
- p:<valore>           apri il pacco con quel valore
- a:offerta            richiedi inserimento offerta
- a:range:<min>:<max>  filtro range per l'offerta
- a:scrivi_offerta     attiva input testuale per l'offerta
- a:accetta            accetta l'offerta
- a:rifiuta            rifiuta l'offerta
- a:cambio             analizza il cambio
- a:annulla            annulla ultima apertura (bottone)
- a:termina            termina la partita (bottone)
- a:fine_offerta       termina dichiarando offerta accettata
- a:fine_cambio        termina dichiarando cambio accettato
- a:fine_pacco         termina dichiarando pacco tenuto
- a:report             mostra il report (stub)
- a:nuova              avvia una nuova partita

Testo libero:
- importo dell'offerta quando in attesa (formato: 35000, 35.000, 35k, ...)
- importo del premio finale quando in attesa (stesso formato)
"""

from __future__ import annotations

import json
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from affari_tuoi.bot import formatters as fmt
from affari_tuoi.bot import keyboards as kb
from affari_tuoi.core.consulente import (
    StatoConsulente,
    analizza_stato,
)
from affari_tuoi.storage.db import Database
from affari_tuoi.utils.config import Config
from affari_tuoi.utils.logger import get_logger
from affari_tuoi.utils.parsing import parse_importo
from affari_tuoi.bot.handlers.report import invia_report

_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Utility interne
# ---------------------------------------------------------------------------

def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


def _config(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.application.bot_data["config"]


def _stato_corrente(context: ContextTypes.DEFAULT_TYPE) -> StatoConsulente | None:
    return context.user_data.get("stato")


def _fase(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("fase", "idle")


def _set_fase(context: ContextTypes.DEFAULT_TYPE, fase: str) -> None:
    context.user_data["fase"] = fase


def _partita_id(context: ContextTypes.DEFAULT_TYPE) -> int | None:
    return context.user_data.get("partita_id")


def _salva_stato(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Serializza lo stato della partita e lo salva su DB."""
    stato: StatoConsulente | None = _stato_corrente(context)
    pid = _partita_id(context)
    if stato is None or pid is None:
        return
    stato_json = json.dumps(
        {
            "valori_rimasti": list(stato.valori_rimasti),
            "valori_aperti": list(stato.valori_aperti),
            "offerta_corrente": stato.offerta_corrente,
        },
        ensure_ascii=False,
    )
    _db(context).aggiorna_stato(pid, stato_json)


def _evento(
    context: ContextTypes.DEFAULT_TYPE,
    tipo: str,
    dati: dict[str, Any],
) -> None:
    """Registra un evento nella partita corrente."""
    pid = _partita_id(context)
    if pid is None:
        return
    _db(context).aggiungi_evento(pid, tipo, dati)


def _tastiera_corrente(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    """Restituisce la tastiera giusta per la fase corrente."""
    stato = _stato_corrente(context)
    if stato is None:
        return InlineKeyboardMarkup([])
    if _fase(context) == "offerta":
        return kb.tastiera_offerta(stato)
    if stato.in_fase_finale:
        return kb.tastiera_finale(stato)
    return kb.tastiera_apertura(stato)


# ---------------------------------------------------------------------------
# Comandi
# ---------------------------------------------------------------------------

async def cmd_new(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Crea una nuova partita e mostra la griglia dei pacchi."""
    user = update.effective_user
    if user is None:
        return

    stato = StatoConsulente.iniziale()
    stato_json = json.dumps(
        {
            "valori_rimasti": list(stato.valori_rimasti),
            "valori_aperti": [],
            "offerta_corrente": None,
        },
        ensure_ascii=False,
    )

    pid = _db(context).crea_partita(user_id=user.id, stato_json=stato_json)

    context.user_data["stato"] = stato
    context.user_data["partita_id"] = pid
    context.user_data["fase"] = "apertura"
    context.user_data["storico_ev"] = []
    context.user_data["storico_offerte"] = []
    context.user_data["pacco_giocatore_valore"] = None

    analisi = analizza_stato(stato)
    testo = fmt.formatta_stato_breve(stato, analisi)

    msg = await update.message.reply_text(
        testo,
        parse_mode="Markdown",
        reply_markup=kb.tastiera_apertura(stato),
    )
    context.user_data["messaggio_id"] = msg.message_id
    _log.info("Nuova partita id=%s user=%s", pid, user.id)


async def cmd_annulla(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Annulla l'ultima apertura (da comando /annulla)."""
    stato = _stato_corrente(context)
    if stato is None:
        await update.message.reply_text(
            "Nessuna partita in corso. Usa /new per iniziarne una."
        )
        return

    valore = stato.annulla_ultimo()
    if valore is None:
        await update.message.reply_text(
            "Niente da annullare.",
            reply_markup=_tastiera_corrente(context),
        )
        return

    _salva_stato(context)
    _evento(context, "annulla", {"valore": valore})

    analisi = analizza_stato(stato)
    testo = (
        f"↩️ Annullata apertura di *{fmt.formatta_euro(valore)} EUR*\n\n"
        + fmt.formatta_stato_breve(stato, analisi)
    )
    await update.message.reply_text(
        testo,
        parse_mode="Markdown",
        reply_markup=_tastiera_corrente(context),
    )


async def cmd_termina(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Avvia la procedura di fine partita (comando o bottone)."""
    stato = _stato_corrente(context)
    if stato is None:
        testo = "Nessuna partita in corso. Usa /new per iniziarne una."
        if update.callback_query:
            await update.callback_query.answer(testo, show_alert=True)
        elif update.message:
            await update.message.reply_text(testo)
        return

    context.user_data["fase"] = "fine_via"
    tastiera = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💰 Ho accettato un'offerta", callback_data="a:fine_offerta"
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 Ho accettato il cambio", callback_data="a:fine_cambio"
            ),
            InlineKeyboardButton(
                "📦 Ho tenuto il pacco", callback_data="a:fine_pacco"
            ),
        ],
    ])
    testo = "🏁 *Come è finita la partita?*"

    if update.callback_query:
        await update.callback_query.edit_message_text(
            testo, parse_mode="Markdown", reply_markup=tastiera
        )
    elif update.message:
        await update.message.reply_text(
            testo, parse_mode="Markdown", reply_markup=tastiera
        )


# ---------------------------------------------------------------------------
# Callback: apertura pacco
# ---------------------------------------------------------------------------

async def on_callback_pacco(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Gestisce il click su un pacco."""
    query = update.callback_query
    await query.answer()

    stato = _stato_corrente(context)
    if stato is None:
        await query.edit_message_text(
            "Nessuna partita in corso. Usa /new."
        )
        return

    if _fase(context) not in ("apertura",):
        await query.edit_message_text(
            "⚠️ Azione non consentita in questa fase."
        )
        return

    try:
        valore = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return

    if valore not in stato.valori_rimasti:
        await query.edit_message_text(
            "⚠️ Pacco già aperto."
        )
        return

    stato.apri_pacco(valore)
    _salva_stato(context)
    _evento(context, "pacco_aperto", {"valore": valore})

    # Se è rimasto un solo pacco, è il pacco del giocatore:
    # chiudi automaticamente la partita con quel valore.
    if stato.n_rimasti == 1:
        premio_finale = stato.valori_rimasti[0]
        _log.info(
            "Pacco finale rivelato: %s EUR. Chiudo la partita.",
            premio_finale,
        )
        await _chiudi_partita(
            update,
            context,
            premio=premio_finale,
            via_uscita="pacco_finale",
        )
        return

    analisi = analizza_stato(stato)
    testo = fmt.formatta_stato_breve(stato, analisi, ultimo_aperto=valore)

    await query.edit_message_text(
        testo,
        parse_mode="Markdown",
        reply_markup=_tastiera_corrente(context),
    )


# ---------------------------------------------------------------------------
# Callback: azioni
# ---------------------------------------------------------------------------

async def on_callback_azione(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Smista le callback a:..."""
    query = update.callback_query
    parti = query.data.split(":")
    azione = parti[1] if len(parti) > 1 else ""

    match azione:
        case "offerta":
            await _azione_offerta(update, context)
        case "range":
            await _azione_range(update, context, parti)
        case "scrivi_offerta":
            await _azione_scrivi_offerta(update, context)
        case "accetta":
            await _azione_accetta(update, context)
        case "rifiuta":
            await _azione_rifiuta(update, context)
        case "cambio":
            await _azione_cambio(update, context)
        case "annulla":
            await _azione_annulla(update, context)
        case "termina":
            await _azione_termina(update, context)
        case "fine_offerta":
            await _azione_fine_offerta(update, context)
        case "fine_cambio":
            await _azione_fine_cambio(update, context)
        case "fine_pacco":
            await _azione_fine_pacco(update, context)
        case "report":
            await invia_report(update, context)
        case "nuova":
            await query.answer()
            await _azione_nuova_partita(update, context)
        case _:
            await query.answer("Azione sconosciuta.", show_alert=True)


async def _azione_offerta(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Chiede l'importo dell'offerta."""
    query = update.callback_query
    await query.answer()

    context.user_data["fase"] = "attesa_offerta"
    await query.edit_message_text(
        "💰 *Quanto ha offerto il Dottore?*\n\n"
        "Scegli un range o scrivi l'importo (es. `35000` o `35k`).",
        parse_mode="Markdown",
        reply_markup=kb.tastiera_range_offerta(),
    )


async def _azione_range(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parti: list[str],
) -> None:
    """Mostra suggerimento per il range scelto."""
    query = update.callback_query
    await query.answer()

    try:
        minimo = int(parti[2])
        massimo = int(parti[3])
    except (IndexError, ValueError):
        return

    await query.edit_message_text(
        f"💰 Range scelto: *{minimo:,} - {massimo:,} EUR*\n\n"
        "Ora scrivi l'importo esatto dell'offerta (es. `35000` o `35k`).",
        parse_mode="Markdown",
    )
    context.user_data["fase"] = "attesa_offerta_testo"


async def _azione_scrivi_offerta(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Attiva la scrittura manuale dell'offerta."""
    query = update.callback_query
    await query.answer()

    context.user_data["fase"] = "attesa_offerta_testo"
    await query.edit_message_text(
        "✏️ Scrivi l'importo dell'offerta (es. `35000` o `35k`).",
        parse_mode="Markdown",
    )


async def _azione_accetta(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Accetta l'offerta corrente."""
    query = update.callback_query
    await query.answer("✅ Offerta accettata")

    stato = _stato_corrente(context)
    if stato is None or stato.offerta_corrente is None:
        return

    await _chiudi_partita(
        update, context,
        premio=stato.offerta_corrente,
        via_uscita="offerta",
    )


async def _azione_rifiuta(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Rifiuta l'offerta e torna all'apertura."""
    query = update.callback_query
    await query.answer("❌ Offerta rifiutata")

    stato = _stato_corrente(context)
    if stato is None:
        return

    _evento(context, "offerta_rifiutata", {"offerta": stato.offerta_corrente})
    stato.offerta_corrente = None
    context.user_data["fase"] = "apertura"
    _salva_stato(context)

    analisi = analizza_stato(stato)
    testo = (
        "❌ Offerta rifiutata.\n\n"
        + fmt.formatta_stato_breve(stato, analisi)
    )
    await query.edit_message_text(
        testo,
        parse_mode="Markdown",
        reply_markup=_tastiera_corrente(context),
    )


async def _azione_cambio(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Analizza il cambio."""
    query = update.callback_query
    await query.answer()

    stato = _stato_corrente(context)
    if stato is None:
        return

    analisi = analizza_stato(stato)
    if analisi.analisi_cambio is None:
        await query.edit_message_text(
            "⚠️ Il cambio è disponibile solo con 2-3 pacchi rimasti."
        )
        return

    testo = fmt.formatta_cambio(stato, analisi)
    await query.edit_message_text(
        testo,
        parse_mode="Markdown",
        reply_markup=_tastiera_corrente(context),
    )


async def _azione_annulla(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Annulla ultima apertura (da bottone)."""
    query = update.callback_query

    stato = _stato_corrente(context)
    if stato is None:
        await query.answer("Nessuna partita in corso.", show_alert=True)
        return

    valore = stato.annulla_ultimo()
    if valore is None:
        # Niente da annullare: mostra un alert senza toccare la griglia
        await query.answer("Niente da annullare.", show_alert=True)
        return

    await query.answer("↩️ Apertura annullata")

    _salva_stato(context)
    _evento(context, "annulla", {"valore": valore})
    analisi = analizza_stato(stato)
    testo = (
        f"↩️ Annullata apertura di *{fmt.formatta_euro(valore)} EUR*\n\n"
        + fmt.formatta_stato_breve(stato, analisi)
    )
    await query.edit_message_text(
        testo,
        parse_mode="Markdown",
        reply_markup=_tastiera_corrente(context),
    )


async def _azione_termina(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Termina la partita (da bottone)."""
    query = update.callback_query
    await query.answer()
    await cmd_termina(update, context)


async def _azione_fine_offerta(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """L'utente dichiara di aver accettato un'offerta: chiedi importo."""
    query = update.callback_query
    await query.answer()

    context.user_data["fase"] = "fine_importo"
    context.user_data["fine_via"] = "offerta"
    await query.edit_message_text(
        "💰 *Quanto hai vinto?*\n\nScrivi l'importo (es. `35000` o `35k`).",
        parse_mode="Markdown",
    )


async def _azione_fine_cambio(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """L'utente dichiara di aver accettato il cambio: chiedi importo."""
    query = update.callback_query
    await query.answer()

    context.user_data["fase"] = "fine_importo"
    context.user_data["fine_via"] = "cambio"
    await query.edit_message_text(
        "🔄 *Quanto valeva il pacco dopo il cambio?*\n\n"
        "Scrivi l'importo (es. `35000` o `35k`).",
        parse_mode="Markdown",
    )


async def _azione_fine_pacco(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """L'utente dichiara di aver tenuto il pacco: chiedi importo."""
    query = update.callback_query
    await query.answer()

    context.user_data["fase"] = "fine_importo"
    context.user_data["fine_via"] = "pacco_finale"
    await query.edit_message_text(
        "📦 *Quanto valeva il tuo pacco?*\n\n"
        "Scrivi l'importo (es. `35000` o `35k`).",
        parse_mode="Markdown",
    )


async def _azione_nuova_partita(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Crea una nuova partita da callback (no update.message)."""
    user = update.effective_user
    if user is None:
        return

    stato = StatoConsulente.iniziale()
    stato_json = json.dumps(
        {
            "valori_rimasti": list(stato.valori_rimasti),
            "valori_aperti": [],
            "offerta_corrente": None,
        },
        ensure_ascii=False,
    )
    pid = _db(context).crea_partita(user_id=user.id, stato_json=stato_json)

    context.user_data["stato"] = stato
    context.user_data["partita_id"] = pid
    context.user_data["fase"] = "apertura"
    context.user_data["storico_ev"] = []
    context.user_data["storico_offerte"] = []
    context.user_data["pacco_giocatore_valore"] = None

    analisi = analizza_stato(stato)
    testo = fmt.formatta_stato_breve(stato, analisi)

    await update.callback_query.edit_message_text(
        testo,
        parse_mode="Markdown",
        reply_markup=kb.tastiera_apertura(stato),
    )
    _log.info("Nuova partita id=%s user=%s (da callback)", pid, user.id)


# ---------------------------------------------------------------------------
# Testo libero
# ---------------------------------------------------------------------------

async def on_testo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Gestisce input testuale: importo offerta o premio finale."""
    if update.message is None or update.message.text is None:
        return

    fase = _fase(context)
    testo_utente = update.message.text.strip()

    if fase == "attesa_offerta_testo":
        await _ricevi_offerta(update, context, testo_utente)
    elif fase == "fine_importo":
        await _ricevi_premio_finale(update, context, testo_utente)
    # Altre fasi: ignora silenziosamente


async def _ricevi_offerta(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    testo: str,
) -> None:
    """L'utente ha scritto l'importo dell'offerta."""
    stato = _stato_corrente(context)
    if stato is None:
        return

    importo = parse_importo(testo)
    if importo is None or importo <= 0:
        await update.message.reply_text(
            "⚠️ Non ho capito l'importo.\n"
            "Scrivi un numero, es. `35000` o `35k`.",
            parse_mode="Markdown",
        )
        return

    stato.offerta_corrente = importo
    context.user_data["fase"] = "offerta"
    _salva_stato(context)
    _evento(context, "offerta", {"valore": importo})

    analisi = analizza_stato(stato)
    testo_risposta = fmt.formatta_offerta(stato, analisi)

    await update.message.reply_text(
        testo_risposta,
        parse_mode="Markdown",
        reply_markup=kb.tastiera_offerta(stato),
    )


async def _ricevi_premio_finale(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    testo: str,
) -> None:
    """L'utente ha scritto il premio finale."""
    importo = parse_importo(testo)
    if importo is None or importo < 0:
        await update.message.reply_text(
            "⚠️ Non ho capito l'importo.\n"
            "Scrivi un numero, es. `35000` o `35k`.",
            parse_mode="Markdown",
        )
        return

    via = context.user_data.get("fine_via", "offerta")
    await _chiudi_partita(update, context, premio=importo, via_uscita=via)


# ---------------------------------------------------------------------------
# Chiusura partita
# ---------------------------------------------------------------------------

async def _chiudi_partita(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    premio: int,
    via_uscita: str,
) -> None:
    """Chiude la partita, salva sul DB, mostra il riepilogo."""
    stato = _stato_corrente(context)
    pid = _partita_id(context)
    if stato is None or pid is None:
        return

    pacco_reale: int | None = None
    if via_uscita == "pacco_finale":
        pacco_reale = premio

    _evento(context, "fine", {"premio": premio, "via": via_uscita})
    _db(context).chiudi_partita(
        pid,
        premio=premio,
        via_uscita=via_uscita,
        pacco_reale=pacco_reale,
    )

    context.user_data["fase"] = "conclusa"

    testo = fmt.formatta_riepilogo_breve(premio, pacco_reale, via_uscita)
    tastiera = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Report completo", callback_data="a:report"),
            InlineKeyboardButton("🔄 Nuova partita", callback_data="a:nuova"),
        ]
    ])

    if update.callback_query:
        await update.callback_query.edit_message_text(
            testo, parse_mode="Markdown", reply_markup=tastiera
        )
    elif update.message:
        await update.message.reply_text(
            testo, parse_mode="Markdown", reply_markup=tastiera
        )

    _log.info(
        "Partita chiusa id=%s premio=%s via=%s",
        pid, premio, via_uscita,
    )


__all__ = [
    "cmd_new",
    "cmd_annulla",
    "cmd_termina",
    "on_callback_pacco",
    "on_callback_azione",
    "on_testo",
]