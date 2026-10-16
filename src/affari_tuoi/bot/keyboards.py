"""
Costruzione delle tastiere inline per il bot.

Usa `StatoEsteso` come stato canonico: la griglia mostra i valori
numerici, i bottoni speciali mostrano Tommasino, Ballerina e Pacco Nero.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from affari_tuoi.core.premi import carica_configurazione_premi
from affari_tuoi.core.stato_esteso import StatoEsteso


# ---------------------------------------------------------------------------
# Etichette
# ---------------------------------------------------------------------------

def etichetta_valore(valore: int) -> str:
    """Formatta un valore in modo compatto per un bottone Telegram."""
    if valore < 1_000:
        return str(valore)
    return f"{valore // 1_000}k"


# ---------------------------------------------------------------------------
# Griglia dei pacchi numerici
# ---------------------------------------------------------------------------

COLONNE_GRIGLIA: int = 5


def griglia_pacchi(
    stato: StatoEsteso,
    *,
    colonne: int = COLONNE_GRIGLIA,
) -> list[list[InlineKeyboardButton]]:
    """Griglia dei pacchi numerici rimasti."""
    valori = list(stato.valori_numerici_rimasti)

    righe: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(valori), colonne):
        chunk = valori[i : i + colonne]
        riga = [
            InlineKeyboardButton(
                etichetta_valore(v),
                callback_data=f"p:{v}",
            )
            for v in chunk
        ]
        righe.append(riga)
    return righe


# ---------------------------------------------------------------------------
# Bottoni speciali
# ---------------------------------------------------------------------------

def bottoni_speciali(
    stato: StatoEsteso,
) -> list[list[InlineKeyboardButton]]:
    """
    Bottoni per i pacchi speciali ancora chiusi.
    """
    config = carica_configurazione_premi()
    riga: list[InlineKeyboardButton] = []
    for s in config.pacchi_speciali:
        if s.id in stato.speciali_chiusi:
            riga.append(
                InlineKeyboardButton(
                    s.label,
                    callback_data=f"s:{s.id}",
                )
            )
    return [riga] if riga else []


# ---------------------------------------------------------------------------
# Bottoni azione
# ---------------------------------------------------------------------------

def bottoni_azione_apertura() -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton("💰 Offerta ricevuta", callback_data="a:offerta"),
        InlineKeyboardButton("↩️ Annulla", callback_data="a:annulla"),
        InlineKeyboardButton("🏁 Termina", callback_data="a:termina"),
    ]


def bottoni_azione_offerta() -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton("✅ Accetta", callback_data="a:accetta"),
        InlineKeyboardButton("❌ Rifiuta", callback_data="a:rifiuta"),
        InlineKeyboardButton("↩️ Cambia offerta", callback_data="a:offerta"),
    ]


def bottoni_azione_finale() -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton("💰 Offerta ricevuta", callback_data="a:offerta"),
        InlineKeyboardButton("🔄 Analizza cambio", callback_data="a:cambio"),
        InlineKeyboardButton("↩️ Annulla", callback_data="a:annulla"),
        InlineKeyboardButton("🏁 Termina", callback_data="a:termina"),
    ]


# ---------------------------------------------------------------------------
# Range offerta
# ---------------------------------------------------------------------------

RANGE_OFFERTA: list[tuple[str, int, int]] = [
    ("< 10k", 0, 10_000),
    ("10-30k", 10_000, 30_000),
    ("30-50k", 30_000, 50_000),
    ("50-80k", 50_000, 80_000),
    ("80-120k", 80_000, 120_000),
    ("> 120k", 120_000, 10**9),
]


def bottoni_range_offerta() -> list[list[InlineKeyboardButton]]:
    righe: list[list[InlineKeyboardButton]] = []
    riga_corrente: list[InlineKeyboardButton] = []
    for etichetta, minimo, massimo in RANGE_OFFERTA:
        riga_corrente.append(
            InlineKeyboardButton(
                etichetta,
                callback_data=f"a:range:{minimo}:{massimo}",
            )
        )
        if len(riga_corrente) == 3:
            righe.append(riga_corrente)
            riga_corrente = []
    if riga_corrente:
        righe.append(riga_corrente)
    righe.append(
        [InlineKeyboardButton("✏️ Scrivi importo", callback_data="a:scrivi_offerta")]
    )
    return righe


# ---------------------------------------------------------------------------
# Composizione
# ---------------------------------------------------------------------------

def tastiera_apertura(stato: StatoEsteso) -> InlineKeyboardMarkup:
    righe = griglia_pacchi(stato)
    righe.extend(bottoni_speciali(stato))
    righe.append(bottoni_azione_apertura())
    return InlineKeyboardMarkup(righe)


def tastiera_offerta(stato: StatoEsteso) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([bottoni_azione_offerta()])


def tastiera_finale(stato: StatoEsteso) -> InlineKeyboardMarkup:
    righe = griglia_pacchi(stato)
    righe.extend(bottoni_speciali(stato))
    righe.append(bottoni_azione_finale())
    return InlineKeyboardMarkup(righe)


def tastiera_range_offerta() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(bottoni_range_offerta())


def tastiera_dopo_fine() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Report completo", callback_data="a:report"),
            InlineKeyboardButton("🔄 Nuova partita", callback_data="a:nuova"),
        ]
    ])


__all__ = [
    "etichetta_valore",
    "griglia_pacchi",
    "bottoni_speciali",
    "bottoni_azione_apertura",
    "bottoni_azione_offerta",
    "bottoni_azione_finale",
    "bottoni_range_offerta",
    "tastiera_apertura",
    "tastiera_offerta",
    "tastiera_finale",
    "tastiera_range_offerta",
    "tastiera_dopo_fine",
    "RANGE_OFFERTA",
]