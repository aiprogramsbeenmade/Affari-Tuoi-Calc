"""
Handler del gioco interattivo (con supporto pacchi speciali + jolly).
"""

from __future__ import annotations

import json
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from affari_tuoi.bot import formatters as fmt
from affari_tuoi.bot import keyboards as kb
from affari_tuoi.bot.handlers.report import invia_report
from affari_tuoi.core.consulente import analizza_stato_esteso
from affari_tuoi.core.premi import carica_configurazione_premi
from affari_tuoi.core.stato_esteso import StatoEsteso
from affari_tuoi.storage.db import Database
from affari_tuoi.utils.config import Config
from affari_tuoi.utils.logger import get_logger
from affari_tuoi.utils.parsing import parse_importo

_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


def _config(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.application.bot_data["config"]


def _stato_corrente(context: ContextTypes.DEFAULT_TYPE) -> StatoEsteso | None:
    return context.user_data.get("stato")


def _fase(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("fase", "idle")


def _partita_id(context: ContextTypes.DEFAULT_TYPE) -> int | None:
    return context.user_data.get("partita_id")


def _salva_stato(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Serializza StatoEsteso e lo salva su DB."""
    stato: StatoEsteso | None = _stato_corrente(context)
    pid = _partita_id(context)
    if stato is None or pid is None:
        return
    stato_json = json.dumps(stato.to_dict(), ensure_ascii=False)
    _db(context).aggiorna_stato(pid, stato_json)


def _evento(
    context: ContextTypes.DEFAULT_TYPE,
    tipo: str,
    dati: dict[str, Any],
) -> None:
    pid = _partita_id(context)
    if pid is None:
        return
    _db(context).aggiungi_evento(pid, tipo, dati)


def _tastiera_corrente(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    stato = _stato_corrente(context)
    if stato is None:
        return InlineKeyboardMarkup([])
    if _fase(context) == "offerta":
        return kb.tastiera_offerta(stato)
    if stato.in_fase_finale:
        return kb.tastiera_finale(stato)
    return kb.tastiera_apertura(stato)


def _inizializza_partita(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> int:
    """Crea una nuova partita in memoria + DB. Ritorna l'id."""
    stato = StatoEsteso.iniziale()
    stato_json = json.dumps(
        {
            "valori_disponibili": sorted(stato.valori_disponibili),
            "valori_aperti": [],
            "speciali_chiusi": sorted(stato.speciali_chiusi),
            "speciali_aperti": [],
            "valori_speciali_rivelati": {},
            "offerta_corrente": None,
        },
        ensure_ascii=False,
    )
    pid = _db(context).crea_partita(user_id=user_id, stato_json=stato_json)
    context.user_data["stato"] = stato
    context.user_data["partita_id"] = pid
    context.user_data["fase"] = "apertura"
    context.user_data["storico_ev"] = []
    context.user_data["storico_offerte"] = []
    context.user_data["pacco_giocatore_valore"] = None
    return pid


# ---------------------------------------------------------------------------
# Comandi
# ---------------------------------------------------------------------------

async def cmd_new(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user = update.effective_user
    if user is None:
        return
    pid = _inizializza_partita(context, user.id)
    stato = _stato_corrente(context)
    assert stato is not None

    analisi = analizza_stato_esteso(stato)
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
    stato = _stato_corrente(context)
    if stato is None:
        await update.message.reply_text(
            "Nessuna partita in corso. Usa /new per iniziarne una."
        )
        return
    risultato = stato.annulla_ultimo()
    if risultato is None:
        await update.message.reply_text(
            "Niente da annullare.",
            reply_markup=_tastiera_corrente(context),
        )
        return
    tipo, valore = risultato
    _salva_stato(context)
    _evento(context, "annulla", {"tipo": tipo, "valore": valore})

    analisi = analizza_stato_esteso(stato)
    testo = (
        f"↩️ Annullata apertura ({tipo})\n\n"
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
# Callback: apertura pacco numerico
# ---------------------------------------------------------------------------

async def on_callback_pacco(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    await query.answer()

    stato = _stato_corrente(context)
    if stato is None:
        await query.edit_message_text("Nessuna partita in corso. Usa /new.")
        return

    if _fase(context) not in ("apertura",):
        await query.edit_message_text("⚠️ Azione non consentita in questa fase.")
        return

    try:
        valore = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return

    if valore not in stato.valori_disponibili:
        await query.edit_message_text("⚠️ Pacco già aperto.")
        return

    stato.apri_numerico(valore)
    _salva_stato(context)
    _evento(context, "pacco_aperto", {"valore": valore})
    await _dopo_apertura(update, context, valore)


# ---------------------------------------------------------------------------
# Callback: apertura pacco speciale
# ---------------------------------------------------------------------------

async def on_callback_speciale(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    await query.answer()

    stato = _stato_corrente(context)
    if stato is None:
        await query.edit_message_text("Nessuna partita in corso. Usa /new.")
        return

    if _fase(context) not in ("apertura",):
        await query.edit_message_text("⚠️ Azione non consentita in questa fase.")
        return

    try:
        id_pacco = query.data.split(":", 1)[1]
    except IndexError:
        return

    config = carica_configurazione_premi()
    pacco = config.pacco_speciale(id_pacco)
    if pacco is None:
        await query.edit_message_text("⚠️ Pacco speciale sconosciuto.")
        return

    if id_pacco not in stato.speciali_chiusi:
        await query.edit_message_text("⚠️ Pacco speciale già aperto.")
        return

    if pacco.e_jolly:
        # Pacco Nero: chiedi il valore rivelato
        context.user_data["fase"] = "attesa_valore_pacco_nero"
        await query.edit_message_text(
            f"⚫ *{pacco.label}*\n\n"
            "Qual è il valore rivelato in TV?\n"
            "Scrivi l'importo (es. `35000` o `35k`).",
            parse_mode="Markdown",
        )
        return

    # Tommasino/Ballerina: apri senza valore numerico
    stato.apri_speciale(id_pacco, valore_rivelato=None)
    _salva_stato(context)
    _evento(context, "pacco_speciale", {
        "id": pacco.id,
        "label": pacco.label,
    })
    await _dopo_apertura_speciale(update, context, pacco.label)


async def _dopo_apertura_speciale(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    label: str,
) -> None:
    stato = _stato_corrente(context)
    if stato is None:
        return
    analisi = analizza_stato_esteso(stato)
    testo = (
        f"🎁 *{label}* (nessun valore monetario)\n\n"
        + fmt.formatta_stato_breve(stato, analisi)
    )
    await update.callback_query.edit_message_text(
        testo,
        parse_mode="Markdown",
        reply_markup=_tastiera_corrente(context),
    )


# ---------------------------------------------------------------------------
# Dopo apertura numerica
# ---------------------------------------------------------------------------

async def _dopo_apertura(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    valore: int,
) -> None:
    stato = _stato_corrente(context)
    if stato is None:
        return

    if stato.n_pacchi_chiusi == 1:
        premio_finale = _ultimo_valore(stato)
        await _chiudi_partita(
            update, context,
            premio=premio_finale,
            via_uscita="pacco_finale",
        )
        return

    analisi = analizza_stato_esteso(stato)
    testo = fmt.formatta_stato_breve(stato, analisi, ultimo_aperto=valore)
    await update.callback_query.edit_message_text(
        testo,
        parse_mode="Markdown",
        reply_markup=_tastiera_corrente(context),
    )


def _ultimo_valore(stato: StatoEsteso) -> int:
    """Ritorna il valore dell'ultimo pacco chiuso (numerico o jolly)."""
    if stato.valori_disponibili:
        return max(stato.valori_disponibili)
    return 0


# ---------------------------------------------------------------------------
# Callback azioni
# ---------------------------------------------------------------------------

async def on_callback_azione(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
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


async def _azione_offerta(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["fase"] = "attesa_offerta"
    await query.edit_message_text(
        "💰 *Quanto ha offerto il Dottore?*\n\n"
        "Scegli un range o scrivi l'importo (es. `35000` o `35k`).",
        parse_mode="Markdown",
        reply_markup=kb.tastiera_range_offerta(),
    )


async def _azione_range(update, context, parti):
    query = update.callback_query
    await query.answer()
    try:
        minimo = int(parti[2])
        massimo = int(parti[3])
    except (IndexError, ValueError):
        return
    await query.edit_message_text(
        f"💰 Range scelto: *{minimo:,} - {massimo:,} EUR*\n\n"
        "Ora scrivi l'importo esatto (es. `35000` o `35k`).",
        parse_mode="Markdown",
    )
    context.user_data["fase"] = "attesa_offerta_testo"


async def _azione_scrivi_offerta(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["fase"] = "attesa_offerta_testo"
    await query.edit_message_text(
        "✏️ Scrivi l'importo dell'offerta (es. `35000` o `35k`).",
        parse_mode="Markdown",
    )


async def _azione_accetta(update, context):
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


async def _azione_rifiuta(update, context):
    query = update.callback_query
    await query.answer("❌ Offerta rifiutata")
    stato = _stato_corrente(context)
    if stato is None:
        return
    _evento(context, "offerta_rifiutata", {"offerta": stato.offerta_corrente})
    stato.offerta_corrente = None
    context.user_data["fase"] = "apertura"
    _salva_stato(context)
    analisi = analizza_stato_esteso(stato)
    testo = "❌ Offerta rifiutata.\n\n" + fmt.formatta_stato_breve(stato, analisi)
    await query.edit_message_text(
        testo,
        parse_mode="Markdown",
        reply_markup=_tastiera_corrente(context),
    )


async def _azione_cambio(update, context):
    query = update.callback_query
    await query.answer()
    stato = _stato_corrente(context)
    if stato is None:
        return
    analisi = analizza_stato_esteso(stato)
    if analisi.analisi_cambio is None:
        await query.edit_message_text(
            "⚠️ Il cambio è disponibile solo con 2-3 pacchi rimasti."
        )
        return
    testo = fmt.formatta_cambio(stato, analisi)
    await query.edit_message_text(
        testo, parse_mode="Markdown",
        reply_markup=_tastiera_corrente(context),
    )


async def _azione_annulla(update, context):
    query = update.callback_query
    stato = _stato_corrente(context)
    if stato is None:
        await query.answer("Nessuna partita in corso.", show_alert=True)
        return
    risultato = stato.annulla_ultimo()
    if risultato is None:
        await query.answer("Niente da annullare.", show_alert=True)
        return
    await query.answer("↩️ Apertura annullata")
    tipo, valore = risultato
    _salva_stato(context)
    _evento(context, "annulla", {"tipo": tipo, "valore": valore})
    analisi = analizza_stato_esteso(stato)
    testo = (
        f"↩️ Annullata apertura ({tipo})\n\n"
        + fmt.formatta_stato_breve(stato, analisi)
    )
    await query.edit_message_text(
        testo, parse_mode="Markdown",
        reply_markup=_tastiera_corrente(context),
    )


async def _azione_termina(update, context):
    query = update.callback_query
    await query.answer()
    await cmd_termina(update, context)


async def _azione_fine_offerta(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["fase"] = "fine_importo"
    context.user_data["fine_via"] = "offerta"
    await query.edit_message_text(
        "💰 *Quanto hai vinto?*\n\nScrivi l'importo.",
        parse_mode="Markdown",
    )


async def _azione_fine_cambio(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["fase"] = "fine_importo"
    context.user_data["fine_via"] = "cambio"
    await query.edit_message_text(
        "🔄 *Quanto valeva il pacco dopo il cambio?*\n\nScrivi l'importo.",
        parse_mode="Markdown",
    )


async def _azione_fine_pacco(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["fase"] = "fine_importo"
    context.user_data["fine_via"] = "pacco_finale"
    await query.edit_message_text(
        "📦 *Quanto valeva il tuo pacco?*\n\nScrivi l'importo.",
        parse_mode="Markdown",
    )


async def _azione_nuova_partita(update, context):
    user = update.effective_user
    if user is None:
        return
    _inizializza_partita(context, user.id)
    stato = _stato_corrente(context)
    assert stato is not None
    analisi = analizza_stato_esteso(stato)
    testo = fmt.formatta_stato_breve(stato, analisi)
    await update.callback_query.edit_message_text(
        testo, parse_mode="Markdown",
        reply_markup=kb.tastiera_apertura(stato),
    )


# ---------------------------------------------------------------------------
# Testo libero
# ---------------------------------------------------------------------------

async def on_testo(update, context):
    if update.message is None or update.message.text is None:
        return
    fase = _fase(context)
    testo = update.message.text.strip()
    if fase == "attesa_offerta_testo":
        await _ricevi_offerta(update, context, testo)
    elif fase == "fine_importo":
        await _ricevi_premio_finale(update, context, testo)
    elif fase == "attesa_valore_pacco_nero":
        await _ricevi_valore_pacco_nero(update, context, testo)


async def _ricevi_offerta(update, context, testo):
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
    _evento(context, "offerta", {"valore": importo})
    _salva_stato(context)

    analisi = analizza_stato_esteso(stato)
    testo_risposta = fmt.formatta_offerta(stato, analisi)
    await update.message.reply_text(
        testo_risposta, parse_mode="Markdown",
        reply_markup=kb.tastiera_offerta(stato),
    )


async def _ricevi_premio_finale(update, context, testo):
    importo = parse_importo(testo)
    if importo is None or importo < 0:
        await update.message.reply_text(
            "⚠️ Non ho capito l'importo.", parse_mode="Markdown",
        )
        return
    via = context.user_data.get("fine_via", "offerta")
    await _chiudi_partita(update, context, premio=importo, via_uscita=via)


async def _ricevi_valore_pacco_nero(update, context, testo):
    """L'utente ha scritto il valore rivelato del Pacco Nero."""
    stato = _stato_corrente(context)
    if stato is None:
        return

    valore = parse_importo(testo)
    if valore is None or valore < 0:
        await update.message.reply_text(
            "⚠️ Non ho capito il valore.\n"
            "Scrivi un numero, es. `35000` o `35k`.",
            parse_mode="Markdown",
        )
        return

    # Il Pacco Nero può contenere QUALSIASI valore del tabellone,
    # anche uno già uscito in un altro pacco (il notaio lo sorteggia
    # a parte, quindi può duplicare).
    config = carica_configurazione_premi()
    if valore not in config.premi:
        await update.message.reply_text(
            f"⚠️ Il valore {fmt.formatta_euro(valore)} EUR non è tra i valori "
            f"del tabellone."
        )
        return

    stato.apri_speciale(
        "pacco_nero",
        valore_rivelato=valore,
        consenti_duplicati=True,
    )
    context.user_data["fase"] = "apertura"
    _salva_stato(context)
    _evento(context, "pacco_speciale", {
        "id": "pacco_nero", "label": "⚫ Pacco Nero",
        "valore_equivalente": valore,
    })

    if stato.n_pacchi_chiusi == 1:
        premio_finale = _ultimo_valore(stato)
        await _chiudi_partita(
            update, context,
            premio=premio_finale, via_uscita="pacco_finale",
        )
        return

    analisi = analizza_stato_esteso(stato)
    testo_risposta = (
        f"⚫ *Pacco Nero* — valore: {fmt.formatta_euro(valore)} EUR\n\n"
        + fmt.formatta_stato_breve(stato, analisi)
    )
    await update.message.reply_text(
        testo_risposta, parse_mode="Markdown",
        reply_markup=_tastiera_corrente(context),
    )


# ---------------------------------------------------------------------------
# Chiusura partita
# ---------------------------------------------------------------------------

async def _chiudi_partita(update, context, premio, via_uscita):
    stato = _stato_corrente(context)
    pid = _partita_id(context)
    if stato is None or pid is None:
        return

    pacco_reale: int | None = None
    if via_uscita == "pacco_finale":
        pacco_reale = premio

    _evento(context, "fine", {"premio": premio, "via": via_uscita})
    _db(context).chiudi_partita(
        pid, premio=premio, via_uscita=via_uscita, pacco_reale=pacco_reale,
    )
    context.user_data["fase"] = "conclusa"

    testo = fmt.formatta_riepilogo_breve(premio, pacco_reale, via_uscita)
    tastiera = kb.tastiera_dopo_fine()
    if update.callback_query:
        await update.callback_query.edit_message_text(
            testo, parse_mode="Markdown", reply_markup=tastiera
        )
    elif update.message:
        await update.message.reply_text(
            testo, parse_mode="Markdown", reply_markup=tastiera
        )
    _log.info("Partita chiusa id=%s premio=%s via=%s", pid, premio, via_uscita)


__all__ = [
    "cmd_new", "cmd_annulla", "cmd_termina",
    "on_callback_pacco", "on_callback_speciale",
    "on_callback_azione", "on_testo",
]