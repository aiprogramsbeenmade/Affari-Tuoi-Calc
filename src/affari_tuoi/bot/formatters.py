"""
Formattazione dei messaggi Telegram.

Due funzioni principali:
- formatta_stato_breve: durante la partita, informazioni essenziali
- formatta_report_completo: a fine partita, tutti i dettagli

Tutti i testi usano Markdown di Telegram. I caratteri speciali
(_, *, [, ], `) vanno escapati quando compaiono in input utente.
"""

from __future__ import annotations

from affari_tuoi.core.consulente import AnalisiConsulente, StatoConsulente
from affari_tuoi.core.decisione import Decisione


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def formatta_euro(valore: float | int) -> str:
    """Formatta un importo con separatore migliaia."""
    return f"{valore:,.0f}".replace(",", ".")


def escape_md(testo: str) -> str:
    """Escapa i caratteri speciali di MarkdownV1."""
    speciali = ["_", "*", "[", "]", "`"]
    for c in speciali:
        testo = testo.replace(c, f"\\{c}")
    return testo


# ---------------------------------------------------------------------------
# Messaggio di stato durante la partita
# ---------------------------------------------------------------------------

def formatta_stato_breve(
    stato: StatoConsulente,
    analisi: AnalisiConsulente,
    ultimo_aperto: int | None = None,
) -> str:
    """
    Messaggio compatto mostrato durante l'apertura dei pacchi.

    Layout:
        📦 Pacco aperto: 5.000 EUR

        📊 14 pacchi rimasti
        💎 EV: 42.500 EUR
        🎯 P(pacco ≥ EV): 36%
    """
    righe: list[str] = []

    if ultimo_aperto is not None:
        righe.append(f"📦 *Pacco aperto:* {formatta_euro(ultimo_aperto)} EUR")
        righe.append("")

    righe.append(f"📊 *{analisi.n_rimasti} pacchi rimasti*")
    righe.append(f"💎 EV: *{formatta_euro(analisi.ev)} EUR*")
    righe.append(
        f"🎯 P(pacco ≥ EV): *{analisi.probabilita_almeno_ev:.0%}*"
    )

    if analisi.n_rimasti <= 3:
        righe.append("")
        righe.append("🔄 *Fase finale* — puoi analizzare il cambio")

    return "\n".join(righe)


# ---------------------------------------------------------------------------
# Messaggio con offerta del Dottore
# ---------------------------------------------------------------------------

def formatta_offerta(
    stato: StatoConsulente,
    analisi: AnalisiConsulente,
) -> str:
    """
    Messaggio con l'offerta e le decisioni dei criteri.

    Layout:
        💰 Offerta: 35.000 EUR

        📊 EV: 42.500 EUR
        🎯 P(battere l'offerta): 42%

        💡 RIFIUTA — il tuo pacco vale più dell'offerta nel 42% dei casi
    """
    if analisi.offerta is None:
        return "⚠️ Nessuna offerta sul tavolo."

    righe = [
        f"💰 *Offerta:* {formatta_euro(analisi.offerta)} EUR",
        "",
        f"📊 EV: *{formatta_euro(analisi.ev)} EUR*",
        f"🎯 P(battere l'offerta): *{analisi.probabilita_battere_offerta:.0%}*",
    ]

    # Trova il criterio Prob per il consiglio principale
    consiglio_testo = _consiglio_principale(analisi)
    if consiglio_testo:
        righe.append("")
        righe.append(consiglio_testo)

    # Dettaglio per criterio
    if analisi.decisioni:
        righe.append("")
        righe.append("*Confronto criteri*")
        for nome, dec in analisi.decisioni.items():
            esito = "✅" if dec.accetta else "❌"
            azione = "Accetta" if dec.accetta else "Rifiuta"
            righe.append(f"{esito} {escape_md(nome)}: {azione}")

    return "\n".join(righe)


def _consiglio_principale(analisi: AnalisiConsulente) -> str:
    """Genera il suggerimento principale basato su Prob 30%."""
    for nome, dec in analisi.decisioni.items():
        if "Prob" in nome:
            if dec.accetta:
                return (
                    f"💡 *Consiglio: ACCETTA* — hai solo il "
                    f"{analisi.probabilita_battere_offerta:.0%} di probabilità "
                    f"di fare meglio rifiutando."
                )
            return (
                f"💡 *Consiglio: RIFIUTA* — hai il "
                f"{analisi.probabilita_battere_offerta:.0%} di probabilità "
                f"di fare meglio rifiutando."
            )
    return ""


# ---------------------------------------------------------------------------
# Messaggio con analisi del cambio
# ---------------------------------------------------------------------------

def formatta_cambio(
    stato: StatoConsulente,
    analisi: AnalisiConsulente,
) -> str:
    """Messaggio con l'analisi bayesiana del cambio."""
    if analisi.analisi_cambio is None:
        return "⚠️ Cambio non disponibile in questa fase."

    ac = analisi.analisi_cambio
    righe = [
        "🔄 *Analisi del cambio*",
        "",
        f"Valori in gioco: {formatta_euro(ac.valori_in_gioco[0])} EUR | "
        f"{formatta_euro(ac.valori_in_gioco[-1])} EUR",
        "",
        f"📊 EV tuo pacco: *{formatta_euro(ac.ev_tuo_pacco)} EUR*",
        f"📊 EV pacco alternativo: *{formatta_euro(ac.ev_pacco_alternativo)} EUR*",
        f"💡 {ac.consiglio}",
    ]

    # Posterior per valore (se rilevante)
    if ac.n_pacchi <= 3 and ac.probabilita_per_valore:
        righe.append("")
        righe.append("*Probabilità per il tuo pacco*")
        for valore in sorted(ac.probabilita_per_valore.keys(), reverse=True):
            p = ac.probabilita_per_valore[valore]
            righe.append(
                f"• {formatta_euro(valore)} EUR: *{p:.0%}*"
            )

    return "\n".join(righe)


# ---------------------------------------------------------------------------
# Riepilogo finale breve
# ---------------------------------------------------------------------------

def formatta_riepilogo_breve(
    premio: int,
    pacco_reale: int | None,
    via_uscita: str,
) -> str:
    """Riepilogo breve mostrato a fine partita."""
    righe = [
        "🏁 *Partita conclusa*",
        "",
        f"Premio finale: *{formatta_euro(premio)} EUR*",
    ]
    if pacco_reale is not None and pacco_reale != premio:
        righe.append(
            f"Il tuo pacco valeva: *{formatta_euro(pacco_reale)} EUR*"
        )

    descrizioni = {
        "offerta": "Hai accettato un'offerta del Dottore",
        "cambio": "Hai accettato il cambio",
        "pacco_finale": "Hai tenuto il pacco fino alla fine",
        "interrotta": "Partita interrotta",
    }
    righe.append("")
    righe.append(descrizioni.get(via_uscita, via_uscita))

    return "\n".join(righe)


__all__ = [
    "formatta_euro",
    "escape_md",
    "formatta_stato_breve",
    "formatta_offerta",
    "formatta_cambio",
    "formatta_riepilogo_breve",
]