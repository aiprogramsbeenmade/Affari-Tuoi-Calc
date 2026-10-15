"""
Generazione del report PDF di una partita.

Il report è un PDF multipagina con:
- Pagina 1: copertina (premio, via di uscita, data)
- Pagina 2: grafico della timeline
- Pagina 3: timeline delle decisioni (tabella)
- Pagina 4: statistiche e confronto con strategie alternative
- Pagina 5: commento didattico

Il report è generato a partire dagli eventi della partita, letti dal DB.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from fpdf import FPDF

from affari_tuoi.grafici.plot import (
    PuntoTimeline,
    grafico_timeline,
)


# ---------------------------------------------------------------------------
# Costanti di stile
# ---------------------------------------------------------------------------

COLORE_BLU = (37, 99, 235)
COLORE_VERDE = (22, 163, 74)
COLORE_ROSSO = (220, 38, 38)
COLORE_GRIGIO = (107, 114, 128)
COLORE_GRIGIO_CHIARO = (229, 231, 235)
COLORE_TESTO = (31, 41, 55)


# ---------------------------------------------------------------------------
# Font Unicode
# ---------------------------------------------------------------------------

#: Percorsi candidati per un font Unicode. Proviamo in ordine.
FONT_CANDIDATI = [
    # macOS
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Verdana.ttf",
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    # Windows
    "C:/Windows/Fonts/arial.ttf",
]


def _trova_font_unicode() -> str | None:
    """Restituisce il percorso del primo font Unicode disponibile."""
    for path in FONT_CANDIDATI:
        if Path(path).is_file():
            return path
    return None


# ---------------------------------------------------------------------------
# Dataclass di input
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DatiReport:
    """Tutti i dati necessari per generare il report."""

    # Metadati
    data_partita: str
    """Data/ora della partita, formattata (es. "15/10/2026 21:34")."""

    # Esito
    premio_finale: int
    via_uscita: str
    """Una tra: 'offerta', 'cambio', 'pacco_finale', 'interrotta'."""
    pacco_reale: int | None = None

    # Timeline
    punti: list[PuntoTimeline] = field(default_factory=list)
    """Punti della timeline (uno per pacco aperto)."""

    # Statistiche
    offerta_massima: int | None = None
    offerta_minima: int | None = None
    n_offerte: int = 0
    ev_massimo: float = 0.0
    ev_minimo: float = 0.0
    n_pacchi_aperti: int = 0

    # Confronto strategie
    confronto_strategie: dict[str, int | None] = field(default_factory=dict)
    """{nome_strategia: premio_che_avrebbe_vinto}. None se non determinabile."""

    # Commento didattico
    commento: str = ""


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

class ReportPDF(FPDF):
    """
    Estensione di FPDF con header/footer personalizzati e supporto
    trasparente per font Unicode.

    Registrando un font Unicode tramite `registra_font_unicode()`, tutte
    le chiamate a `set_font("Helvetica", ...)` vengono automaticamente
    reindirizzate al font Unicode. Così il codice delle pagine non deve
    sapere nulla di tutto questo.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._font_unicode: str = "Helvetica"
        """Nome del font Unicode registrato (o "Helvetica" se non disponibile)."""

    def registra_font_unicode(self) -> bool:
        """
        Cerca e registra un font Unicode. Restituisce True se trovato.
        """
        path = _trova_font_unicode()
        if path is None:
            return False
        try:
            self.add_font("Unicode", "", path)
            self.add_font("Unicode", "B", path)
            self.add_font("Unicode", "I", path)
            self._font_unicode = "Unicode"
            return True
        except Exception:
            # Se add_font fallisce, ricadi su Helvetica
            self._font_unicode = "Helvetica"
            return False

    def set_font(self, family=None, style="", size=0):
        """
        Sovrascrive set_font per sostituire automaticamente Helvetica
        con il font Unicode registrato (se disponibile).
        """
        if family == "Helvetica" and self._font_unicode != "Helvetica":
            family = self._font_unicode
        super().set_font(family, style, size)

    def header(self) -> None:
        # Sfondo bianco
        self.set_fill_color(255, 255, 255)
        self.rect(0, 0, 210, 297, "F")

        # Barra superiore blu
        self.set_fill_color(*COLORE_BLU)
        self.rect(0, 0, 210, 8, "F")

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*COLORE_GRIGIO)
        self.cell(0, 10, f"Pagina {self.page_no()}", align="C")


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _euro(valore: float | int) -> str:
    """Formatta un importo con separatore migliaia italiano."""
    return f"{valore:,.0f}".replace(",", ".") + " EUR"


def _via_uscita_label(via: str) -> str:
    return {
        "offerta": "Hai accettato un'offerta",
        "cambio": "Hai accettato il cambio",
        "pacco_finale": "Hai tenuto il pacco fino alla fine",
        "interrotta": "Partita interrotta",
    }.get(via, via)


# ---------------------------------------------------------------------------
# Pagine
# ---------------------------------------------------------------------------

def _pagina_copertina(pdf: ReportPDF, dati: DatiReport) -> None:
    """Pagina 1: copertina."""
    pdf.add_page()

    # Titolo
    pdf.set_y(40)
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_text_color(*COLORE_BLU)
    pdf.cell(0, 15, "Affari Tuoi", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 16)
    pdf.set_text_color(*COLORE_GRIGIO)
    pdf.cell(0, 10, "Report della partita", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(20)

    # Premio finale grande
    pdf.set_font("Helvetica", "", 14)
    pdf.set_text_color(*COLORE_GRIGIO)
    pdf.cell(0, 8, "Premio finale", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 48)
    pdf.set_text_color(*COLORE_VERDE)
    pdf.cell(0, 25, _euro(dati.premio_finale), align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(10)

    # Via di uscita
    pdf.set_font("Helvetica", "I", 12)
    pdf.set_text_color(*COLORE_TESTO)
    pdf.cell(
        0, 8,
        _via_uscita_label(dati.via_uscita),
        align="C", new_x="LMARGIN", new_y="NEXT",
    )

    # Pacco reale
    if dati.pacco_reale is not None and dati.pacco_reale != dati.premio_finale:
        pdf.ln(6)
        pdf.set_font("Helvetica", "", 12)
        pdf.set_text_color(*COLORE_GRIGIO)
        pdf.cell(
            0, 8,
            f"Il tuo pacco valeva {_euro(dati.pacco_reale)}",
            align="C", new_x="LMARGIN", new_y="NEXT",
        )

    # Data
    pdf.ln(20)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*COLORE_GRIGIO)
    pdf.cell(0, 8, dati.data_partita, align="C", new_x="LMARGIN", new_y="NEXT")


def _pagina_grafico(pdf: ReportPDF, dati: DatiReport) -> None:
    """Pagina 2: grafico della timeline."""
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*COLORE_BLU)
    pdf.cell(0, 12, "Andamento della partita", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    if not dati.punti:
        pdf.set_font("Helvetica", "", 12)
        pdf.set_text_color(*COLORE_GRIGIO)
        pdf.cell(
            0, 10,
            "Nessun dato disponibile.",
            new_x="LMARGIN", new_y="NEXT",
        )
        return

    # Genera il grafico
    png_bytes = grafico_timeline(
        dati.punti,
        premio_finale=dati.premio_finale,
        pacco_reale=dati.pacco_reale,
    )

    # Inserisci nel PDF
    pdf.image(BytesIO(png_bytes), x=15, y=40, w=180)


def _pagina_timeline_decisioni(pdf: ReportPDF, dati: DatiReport) -> None:
    """Pagina 3: tabella delle decisioni."""
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*COLORE_BLU)
    pdf.cell(0, 12, "Timeline delle decisioni", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Raccogli le offerte dalla timeline
    offerte = [p for p in dati.punti if p.offerta is not None]

    if not offerte:
        pdf.set_font("Helvetica", "", 12)
        pdf.set_text_color(*COLORE_GRIGIO)
        pdf.cell(
            0, 10,
            "Non hai registrato offerte durante la partita.",
            new_x="LMARGIN", new_y="NEXT",
        )
        return

    # Header tabella
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(*COLORE_BLU)
    pdf.set_text_color(255, 255, 255)
    larghezze = [20, 30, 35, 30, 45]
    intestazioni = ["Turno", "Offerta", "EV", "Scelta", "Note"]
    for i, titolo in enumerate(intestazioni):
        pdf.cell(larghezze[i], 10, titolo, border=0, align="C", fill=True)
    pdf.ln()

    # Righe
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*COLORE_TESTO)
    for idx, p in enumerate(offerte, start=1):
        # Turno
        pdf.cell(larghezze[0], 9, str(idx), border="B", align="C")
        # Offerta
        pdf.cell(
            larghezze[1], 9,
            f"{p.offerta/1000:.0f}k",
            border="B", align="C",
        )
        # EV
        pdf.cell(
            larghezze[2], 9,
            f"{p.ev/1000:.0f}k",
            border="B", align="C",
        )
        # Scelta
        if p.accettata:
            pdf.set_text_color(*COLORE_VERDE)
            pdf.cell(larghezze[3], 9, "ACCETTA", border="B", align="C")
            pdf.set_text_color(*COLORE_TESTO)
        else:
            pdf.cell(larghezze[3], 9, "Rifiuta", border="B", align="C")
        # Note
        delta = (p.offerta - p.ev) / p.ev * 100 if p.ev > 0 else 0
        nota = f"{delta:+.0f}% vs EV"
        pdf.cell(larghezze[4], 9, nota, border="B", align="C")
        pdf.ln()


def _pagina_statistiche(pdf: ReportPDF, dati: DatiReport) -> None:
    """Pagina 4: statistiche e confronto strategie."""
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*COLORE_BLU)
    pdf.cell(0, 12, "Statistiche della partita", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Statistiche base
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*COLORE_TESTO)

    righe = [
        ("Pacchi aperti", f"{dati.n_pacchi_aperti}"),
        ("Offerte ricevute", f"{dati.n_offerte}"),
    ]
    if dati.offerta_massima is not None:
        righe.append(("Offerta massima", _euro(dati.offerta_massima)))
    if dati.offerta_minima is not None:
        righe.append(("Offerta minima", _euro(dati.offerta_minima)))
    if dati.ev_massimo > 0:
        righe.append(("EV massimo raggiunto", _euro(dati.ev_massimo)))
    if dati.ev_minimo > 0:
        righe.append(("EV minimo raggiunto", _euro(dati.ev_minimo)))

    for etichetta, valore in righe:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(90, 9, etichetta, border="B")
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 9, valore, border="B", align="R", new_x="LMARGIN", new_y="NEXT")

    # Confronto strategie
    if dati.confronto_strategie:
        pdf.ln(10)
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(*COLORE_BLU)
        pdf.cell(
            0, 10,
            "Cosa avrebbero fatto altre strategie",
            new_x="LMARGIN", new_y="NEXT",
        )
        pdf.ln(4)

        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(*COLORE_GRIGIO_CHIARO)
        pdf.set_text_color(*COLORE_TESTO)
        pdf.cell(100, 9, "Strategia", border=0, align="L", fill=True)
        pdf.cell(40, 9, "Risultato", border=0, align="C", fill=True)
        pdf.cell(
            0, 9, "Differenza",
            border=0, align="C", fill=True,
            new_x="LMARGIN", new_y="NEXT",
        )

        for nome, valore in dati.confronto_strategie.items():
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(*COLORE_TESTO)
            pdf.cell(100, 9, nome, border="B")
            if valore is None:
                pdf.cell(40, 9, "n/d", border="B", align="C")
                pdf.cell(0, 9, "-", border="B", align="C", new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.cell(40, 9, _euro(valore), border="B", align="C")
                diff = valore - dati.premio_finale
                if diff > 0:
                    pdf.set_text_color(*COLORE_ROSSO)
                    pdf.cell(
                        0, 9, f"+{_euro(diff)}",
                        border="B", align="C",
                        new_x="LMARGIN", new_y="NEXT",
                    )
                elif diff < 0:
                    pdf.set_text_color(*COLORE_VERDE)
                    pdf.cell(
                        0, 9, f"-{_euro(abs(diff))}",
                        border="B", align="C",
                        new_x="LMARGIN", new_y="NEXT",
                    )
                else:
                    pdf.set_text_color(*COLORE_GRIGIO)
                    pdf.cell(
                        0, 9, "uguale",
                        border="B", align="C",
                        new_x="LMARGIN", new_y="NEXT",
                    )


def _pagina_commento(pdf: ReportPDF, dati: DatiReport) -> None:
    """Pagina 5: commento didattico."""
    if not dati.commento:
        return

    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*COLORE_BLU)
    pdf.cell(0, 12, "Analisi della partita", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*COLORE_TESTO)

    # multi_cell gestisce l'andare a capo automaticamente
    pdf.multi_cell(0, 6, dati.commento)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def genera_report_pdf(dati: DatiReport) -> bytes:
    """
    Genera il PDF completo del report.

    Args:
        dati: tutti i dati della partita.

    Returns:
        Bytes del PDF.
    """
    pdf = ReportPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(15, 15, 15)

    # Prova a registrare un font Unicode; se fallisce, resta Helvetica
    pdf.registra_font_unicode()

    _pagina_copertina(pdf, dati)
    _pagina_grafico(pdf, dati)
    _pagina_timeline_decisioni(pdf, dati)
    _pagina_statistiche(pdf, dati)
    _pagina_commento(pdf, dati)

    return bytes(pdf.output())


__all__ = [
    "DatiReport",
    "genera_report_pdf",
    "ReportPDF",
]