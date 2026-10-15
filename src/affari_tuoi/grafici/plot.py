"""
Grafici per il report della partita.

Il grafico principale mostra:
- Asse X: avanzamento della partita (numero di pacchi aperti)
- Linea blu: EV del pacco del giocatore ad ogni passo
- Punti rossi: offerte del Dottore ricevute
- Punto verde: offerta accettata (se l'utente ha accettato)
- Linea tratteggiata: premio finale (per confronto)

I grafici sono generati come PNG in memoria (BytesIO) per essere
inviati su Telegram o inseriti in un PDF.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")  # backend non interattivo, obbligatorio per server

import matplotlib.pyplot as plt
from matplotlib.figure import Figure


# ---------------------------------------------------------------------------
# Stili
# ---------------------------------------------------------------------------

#: Colori coerenti con lo stile del bot.
COLORE_EV = "#2563eb"           # blu
COLORE_OFFERTA = "#dc2626"      # rosso
COLORE_ACCETTATA = "#16a34a"    # verde
COLORE_PREMIO = "#6b7280"       # grigio
COLORE_SFONDO = "#ffffff"
COLORE_GRIGLIA = "#e5e7eb"

#: Dimensioni del grafico in pollici (16:9 circa).
FIGSIZE = (10, 5.5)
DPI = 120


# ---------------------------------------------------------------------------
# Punto della timeline
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PuntoTimeline:
    """Un punto della timeline della partita."""

    n_pacchi_aperti: int
    """Numero di pacchi aperti fino a questo momento."""
    ev: float
    """Valore atteso del pacco del giocatore."""
    offerta: int | None = None
    """Offerta del Dottore a questo passo, se presente."""
    accettata: bool = False
    """True se questa offerta è stata accettata."""


# ---------------------------------------------------------------------------
# Grafico principale
# ---------------------------------------------------------------------------

def grafico_timeline(
    punti: list[PuntoTimeline],
    premio_finale: int | None = None,
    pacco_reale: int | None = None,
    titolo: str = "Andamento della partita",
) -> bytes:
    """
    Genera il grafico della timeline come PNG in memoria.

    Args:
        punti: lista di PuntoTimeline (uno per ogni pacco aperto).
        premio_finale: premio finale vinto (linea tratteggiata).
        pacco_reale: valore reale del pacco del giocatore, se noto.
        titolo: titolo del grafico.

    Returns:
        Bytes PNG del grafico.
    """
    if not punti:
        # Grafico vuoto con messaggio
        fig, ax = plt.subplots(figsize=FIGSIZE, dpi=DPI)
        ax.text(
            0.5, 0.5, "Nessun dato disponibile",
            ha="center", va="center", fontsize=14, color=COLORE_PREMIO,
        )
        ax.axis("off")
        return _fig_to_png(fig)

    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=DPI)
    fig.patch.set_facecolor(COLORE_SFONDO)
    ax.set_facecolor(COLORE_SFONDO)

    # Dati
    x = [p.n_pacchi_aperti for p in punti]
    y_ev = [p.ev for p in punti]

    # Linea EV
    ax.plot(
        x, y_ev,
        color=COLORE_EV,
        linewidth=2.5,
        marker="o",
        markersize=5,
        label="EV del pacco",
        zorder=3,
    )

    # Punti offerte
    x_off = [p.n_pacchi_aperti for p in punti if p.offerta is not None]
    y_off = [p.offerta for p in punti if p.offerta is not None]
    if x_off:
        ax.scatter(
            x_off, y_off,
            color=COLORE_OFFERTA,
            s=100,
            zorder=4,
            label="Offerte del Dottore",
            edgecolors="white",
            linewidths=1.5,
        )

        # Etichette delle offerte
        for xi, yi in zip(x_off, y_off):
            ax.annotate(
                f"{yi/1000:.0f}k",
                (xi, yi),
                textcoords="offset points",
                xytext=(0, 12),
                ha="center",
                fontsize=8,
                color=COLORE_OFFERTA,
                fontweight="bold",
            )

    # Punto accettazione
    acc = [p for p in punti if p.accettata]
    if acc:
        p = acc[0]
        ax.scatter(
            [p.n_pacchi_aperti], [p.offerta],
            color=COLORE_ACCETTATA,
            s=180,
            zorder=5,
            marker="*",
            edgecolors="white",
            linewidths=1.5,
            label="Offerta accettata",
        )

    # Linea premio finale
    if premio_finale is not None:
        ax.axhline(
            y=premio_finale,
            color=COLORE_ACCETTATA,
            linestyle="--",
            linewidth=1.5,
            alpha=0.6,
            label=f"Premio finale: {premio_finale/1000:.0f}k EUR",
            zorder=2,
        )

    # Linea pacco reale
    if pacco_reale is not None and pacco_reale != premio_finale:
        ax.axhline(
            y=pacco_reale,
            color=COLORE_PREMIO,
            linestyle=":",
            linewidth=1.5,
            alpha=0.6,
            label=f"Valore pacco reale: {pacco_reale/1000:.0f}k EUR",
            zorder=2,
        )

    # Assi
    ax.set_xlabel("Pacchi aperti", fontsize=11)
    ax.set_ylabel("Valore (EUR)", fontsize=11)
    ax.set_title(titolo, fontsize=13, fontweight="bold", pad=15)

    # Formato asse Y in migliaia
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"{v/1000:.0f}k")
    )

    # Griglia
    ax.grid(True, color=COLORE_GRIGLIA, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)

    # Legenda
    ax.legend(
        loc="best",
        framealpha=0.95,
        fontsize=9,
        edgecolor=COLORE_GRIGLIA,
    )

    # Margini
    ax.margins(x=0.05)

    fig.tight_layout()
    return _fig_to_png(fig)


# ---------------------------------------------------------------------------
# Grafico distribuzione (per il report)
# ---------------------------------------------------------------------------

def grafico_distribuzione(
    valori: list[int],
    evidenzia: int | None = None,
    titolo: str = "Distribuzione dei premi in gioco",
) -> bytes:
    """
    Genera un grafico a barre dei valori rimasti, opzionalmente evidenziandone uno.

    Args:
        valori: lista di valori ancora in gioco.
        evidenzia: valore da evidenziare (es. offerta o premio).
        titolo: titolo.

    Returns:
        Bytes PNG.
    """
    if not valori:
        fig, ax = plt.subplots(figsize=FIGSIZE, dpi=DPI)
        ax.text(0.5, 0.5, "Nessun valore", ha="center", va="center")
        ax.axis("off")
        return _fig_to_png(fig)

    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=DPI)
    fig.patch.set_facecolor(COLORE_SFONDO)
    ax.set_facecolor(COLORE_SFONDO)

    valori_ordinati = sorted(valori, reverse=True)
    x = range(len(valori_ordinati))
    colori = [
        COLORE_OFFERTA if v == evidenzia else COLORE_EV
        for v in valori_ordinati
    ]

    ax.bar(x, valori_ordinati, color=colori, edgecolor="white")
    ax.set_xticks(list(x))
    ax.set_xticklabels(
        [f"{v/1000:.0f}k" if v >= 1000 else str(v) for v in valori_ordinati],
        rotation=45,
        ha="right",
        fontsize=8,
    )
    ax.set_ylabel("Valore (EUR)", fontsize=11)
    ax.set_title(titolo, fontsize=13, fontweight="bold", pad=15)

    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"{v/1000:.0f}k")
    )
    ax.grid(True, axis="y", color=COLORE_GRIGLIA, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)

    fig.tight_layout()
    return _fig_to_png(fig)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _fig_to_png(fig: Figure) -> bytes:
    """Converte una Figure matplotlib in bytes PNG."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


__all__ = [
    "PuntoTimeline",
    "grafico_timeline",
    "grafico_distribuzione",
    "COLORE_EV",
    "COLORE_OFFERTA",
    "COLORE_ACCETTATA",
]