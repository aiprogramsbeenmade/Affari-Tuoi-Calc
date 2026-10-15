"""
Costruzione delle tastiere inline per il bot.

Contiene:
- griglia dei 20 pacchi (5 colonne × 4 righe)
- bottoni azione (offerta, annulla, termina)
- bottoni per la scelta rapida dell'offerta
- bottoni per accetta/rifiuta/cambia
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from affari_tuoi.core.consulente import StatoConsulente


# ---------------------------------------------------------------------------
# Etichette compatte per i valori
# ---------------------------------------------------------------------------

def etichetta_valore(valore: int) -> str:
    """
    Formatta un valore in modo compatto per un bottone Telegram.

    Esempi:
        0       -> "0"
        500     -> "500"
        5_000   -> "5k"
        150_000 -> "150k"
    """
    if valore < 1_000:
        return str(valore)
    if valore < 10_000:
        return f"{valore // 1_000}k"
    return f"{valore // 1_000}k"


# ---------------------------------------------------------------------------
# Griglia dei pacchi
# ---------------------------------------------------------------------------

#: Numero di colonne nella griglia dei pacchi.
COLONNE_GRIGLIA: int = 5


def griglia_pacchi(
    stato: StatoConsulente,
    *,
    colonne: int = COLONNE_GRIGLIA,
) -> list[list[InlineKeyboardButton]]:
    """
    Costruisce la griglia dei pacchi rimasti.

    Ogni bottone ha callback_data = "p:<valore>" (il valore è piccolo
    e leggibile, così il callback resta corto).

    I pacchi già aperti non compaiono: la griglia si "restringe".
    """
    valori = list(stato.valori_rimasti)  # già ordinati decrescenti
    # Telegram non permette callback_data > 64 byte; "p:300000" è 9 byte,
    # va benissimo.

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
# Bottoni azione
# ---------------------------------------------------------------------------

def bottoni_azione_apertura() -> list[InlineKeyboardButton]:
    """Bottoni mostrati durante la fase di apertura pacchi."""
    return [
        InlineKeyboardButton("💰 Offerta ricevuta", callback_data="a:offerta"),
        InlineKeyboardButton("↩️ Annulla", callback_data="a:annulla"),
        InlineKeyboardButton("🏁 Termina", callback_data="a:termina"),
    ]


def bottoni_azione_offerta() -> list[InlineKeyboardButton]:
    """Bottoni mostrati quando c'è un'offerta sul tavolo."""
    return [
        InlineKeyboardButton("✅ Accetta", callback_data="a:accetta"),
        InlineKeyboardButton("❌ Rifiuta", callback_data="a:rifiuta"),
        InlineKeyboardButton("↩️ Cambia offerta", callback_data="a:offerta"),
    ]


def bottoni_azione_finale() -> list[InlineKeyboardButton]:
    """Bottoni mostrati in fase finale (≤3 pacchi)."""
    return [
        InlineKeyboardButton("💰 Offerta ricevuta", callback_data="a:offerta"),
        InlineKeyboardButton("🔄 Analizza cambio", callback_data="a:cambio"),
        InlineKeyboardButton("↩️ Annulla", callback_data="a:annulla"),
        InlineKeyboardButton("🏁 Termina", callback_data="a:termina"),
    ]


# ---------------------------------------------------------------------------
# Range per l'offerta
# ---------------------------------------------------------------------------

#: Range rapidi per l'offerta del Dottore (in euro).
RANGE_OFFERTA: list[tuple[str, int, int]] = [
    ("< 10k", 0, 10_000),
    ("10-30k", 10_000, 30_000),
    ("30-50k", 30_000, 50_000),
    ("50-80k", 50_000, 80_000),
    ("80-120k", 80_000, 120_000),
    ("> 120k", 120_000, 10**9),
]


def bottoni_range_offerta() -> list[list[InlineKeyboardButton]]:
    """
    Bottoni per la scelta rapida dell'importo dell'offerta.

    Layout:
        [< 10k]  [10-30k] [30-50k]
        [50-80k] [80-120k] [> 120k]
        [✏️ Scrivi importo]
    """
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
# Composizione completa della tastiera
# ---------------------------------------------------------------------------

def tastiera_apertura(stato: StatoConsulente) -> InlineKeyboardMarkup:
    """Tastiera completa in fase di apertura pacchi."""
    righe = griglia_pacchi(stato)
    righe.append(bottoni_azione_apertura())
    return InlineKeyboardMarkup(righe)


def tastiera_offerta(stato: StatoConsulente) -> InlineKeyboardMarkup:
    """Tastiera quando c'è un'offerta sul tavolo (accetta/rifiuta)."""
    righe = [bottoni_azione_offerta()]
    return InlineKeyboardMarkup(righe)


def tastiera_finale(stato: StatoConsulente) -> InlineKeyboardMarkup:
    """Tastiera in fase finale (≤3 pacchi)."""
    righe = griglia_pacchi(stato)
    righe.append(bottoni_azione_finale())
    return InlineKeyboardMarkup(righe)


def tastiera_range_offerta() -> InlineKeyboardMarkup:
    """Tastiera per la scelta dell'importo dell'offerta."""
    return InlineKeyboardMarkup(bottoni_range_offerta())

def tastiera_dopo_fine() -> InlineKeyboardMarkup:
    """Tastiera mostrata dopo la fine della partita."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Report completo", callback_data="a:report"),
            InlineKeyboardButton("🔄 Nuova partita", callback_data="a:nuova"),
        ]
    ])

__all__ = [
    "etichetta_valore",
    "griglia_pacchi",
    "bottoni_azione_apertura",
    "bottoni_azione_offerta",
    "bottoni_azione_finale",
    "bottoni_range_offerta",
    "tastiera_apertura",
    "tastiera_offerta",
    "tastiera_finale",
    "tastiera_range_offerta",
    "RANGE_OFFERTA",
]