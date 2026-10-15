"""
Ricostruzione della timeline di una partita a partire dagli eventi del DB.

Gli eventi sono salvati in ordine cronologico nella tabella `eventi`:
- `pacco_aperto` con {"valore": N}
- `offerta` con {"valore": N}
- `offerta_rifiutata` con {"offerta": N}
- `annulla` con {"valore": N}
- `fine` con {"premio": N, "via": "offerta"}

Questo modulo trasforma quella sequenza in una lista di PuntoTimeline
pronta per essere passata a `genera_report_pdf`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from affari_tuoi.core.consulente import StatoConsulente, analizza_stato
from affari_tuoi.core.premi import carica_configurazione_premi
from affari_tuoi.grafici.plot import PuntoTimeline
from affari_tuoi.grafici.report import DatiReport
from affari_tuoi.storage.db import Database, PartitaDB
from affari_tuoi.utils.logger import get_logger

_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Costruzione timeline
# ---------------------------------------------------------------------------

def _ricostruisci_timeline(
    eventi: list[dict],
) -> tuple[list[PuntoTimeline], dict]:
    """
    Ripercorre gli eventi e ricostruisce la timeline della partita.

    Returns:
        (punti, info) dove info contiene:
        - n_pacchi_aperti
        - offerte (lista di valori)
        - offerta_accettata (int | None)
        - via_uscita (str | None)
        - premio_finale (int | None)
    """
    # Stato iniziale: tutti i premi
    config = carica_configurazione_premi()
    stato = StatoConsulente(
        valori_rimasti=tuple(sorted(config.premi, reverse=True)),
        valori_aperti=(),
    )

    punti: list[PuntoTimeline] = []
    n_pacchi_aperti = 0
    offerte: list[int] = []
    offerta_accettata: int | None = None
    via_uscita: str | None = None
    premio_finale: int | None = None

    for ev in eventi:
        tipo = ev["tipo"]
        dati = ev["dati"]

        if tipo == "pacco_aperto":
            valore = dati["valore"]
            try:
                stato.apri_pacco(valore)
            except ValueError:
                # Evento incoerente (dovrebbe essere raro), skip
                continue
            n_pacchi_aperti += 1
            analisi = analizza_stato(stato)
            punti.append(
                PuntoTimeline(
                    n_pacchi_aperti=n_pacchi_aperti,
                    ev=analisi.ev,
                )
            )

        elif tipo == "annulla":
            # Rimuovi l'ultimo punto se c'era
            valore = dati["valore"]
            try:
                stato.annulla_ultimo()
                if punti:
                    punti.pop()
                n_pacchi_aperti = max(0, n_pacchi_aperti - 1)
            except Exception:
                pass

        elif tipo == "offerta":
            valore = dati["valore"]
            offerte.append(valore)
            # Aggiungi il punto con offerta all'ultimo EV
            if punti:
                # Sostituisci l'ultimo punto con la versione con offerta
                ultimo = punti[-1]
                punti[-1] = PuntoTimeline(
                    n_pacchi_aperti=ultimo.n_pacchi_aperti,
                    ev=ultimo.ev,
                    offerta=valore,
                )
            else:
                # Offerta senza pacchi aperti: strano, ma gestiamo
                punti.append(PuntoTimeline(0, 0, offerta=valore))

        elif tipo == "offerta_rifiutata":
            # Nulla di speciale: la offerta era già stata registrata
            pass

        elif tipo == "fine":
            premio_finale = dati.get("premio")
            via_uscita = dati.get("via")
            # Marca l'ultima offerta come accettata se la via è "offerta"
            if via_uscita == "offerta" and punti:
                ultimo = punti[-1]
                if ultimo.offerta is not None and ultimo.offerta == premio_finale:
                    punti[-1] = PuntoTimeline(
                        n_pacchi_aperti=ultimo.n_pacchi_aperti,
                        ev=ultimo.ev,
                        offerta=ultimo.offerta,
                        accettata=True,
                    )

    info = {
        "n_pacchi_aperti": n_pacchi_aperti,
        "offerte": offerte,
        "offerta_accettata": offerta_accettata,
        "via_uscita": via_uscita,
        "premio_finale": premio_finale,
    }
    return punti, info


# ---------------------------------------------------------------------------
# Commento automatico
# ---------------------------------------------------------------------------

def _genera_commento(
    punti: list[PuntoTimeline],
    premio_finale: int,
    via_uscita: str,
    pacco_reale: int | None,
) -> str:
    """
    Genera il commento didattico a partire dalla timeline.

    Regole semplici, descrittive, non moralistiche.
    """
    righe: list[str] = []

    # 1. Via di uscita
    if via_uscita == "offerta":
        righe.append(
            f"Hai accettato un'offerta del Dottore di "
            f"{premio_finale/1000:.0f}k EUR."
        )
    elif via_uscita == "cambio":
        righe.append(
            f"Hai accettato il cambio finale e hai vinto "
            f"{premio_finale/1000:.0f}k EUR."
        )
    elif via_uscita == "pacco_finale":
        righe.append(
            f"Hai tenuto il pacco fino alla fine e hai vinto "
            f"{premio_finale/1000:.0f}k EUR."
        )
    elif via_uscita == "interrotta":
        righe.append("La partita è stata interrotta prima della fine.")

    righe.append("")

    # 2. Confronto con EV finale
    if punti:
        ev_finale = punti[-1].ev
        if premio_finale > ev_finale * 1.1:
            righe.append(
                f"Il premio finale ({premio_finale/1000:.0f}k) è stato "
                f"superiore all'EV del tuo pacco ({ev_finale/1000:.0f}k): "
                f"una scelta aggressiva e fortunata."
            )
        elif premio_finale < ev_finale * 0.9:
            righe.append(
                f"Il premio finale ({premio_finale/1000:.0f}k) è stato "
                f"inferiore all'EV del tuo pacco ({ev_finale/1000:.0f}k): "
                f"una scelta prudente."
            )
        else:
            righe.append(
                f"Il premio finale ({premio_finale/1000:.0f}k) è in linea "
                f"con l'EV del tuo pacco ({ev_finale/1000:.0f}k)."
            )

    righe.append("")

    # 3. Se il pacco reale è noto e differisce
    if pacco_reale is not None and pacco_reale != premio_finale:
        diff = pacco_reale - premio_finale
        if diff > 0:
            righe.append(
                f"Il tuo pacco valeva {pacco_reale/1000:.0f}k: hai lasciato "
                f"sul tavolo {diff/1000:.0f}k rispetto al valore reale."
            )
        else:
            righe.append(
                f"Il tuo pacco valeva {pacco_reale/1000:.0f}k: hai fatto "
                f"meglio del valore reale del pacco di {abs(diff)/1000:.0f}k."
            )

    righe.append("")

    # 4. Disclaimer
    righe.append(
        "Attenzione: questa è una singola partita. La fortuna gioca un "
        "ruolo enorme. Sul lungo periodo, le strategie aggressive hanno "
        "media piu' alta ma anche varianza molto maggiore. Non esiste una "
        "strategia dominante in assoluto: dipende dalla tua propensione "
        "al rischio."
    )

    return "\n".join(righe)


# ---------------------------------------------------------------------------
# Builder principale
# ---------------------------------------------------------------------------

def costruisci_dati_report(db: Database, partita_id: int) -> DatiReport | None:
    """
    Costruisce i dati del report a partire dal DB.

    Args:
        db: connessione al DB.
        partita_id: id della partita.

    Returns:
        DatiReport pronto per `genera_report_pdf`, o None se la partita
        non esiste o non è conclusa.
    """
    partita = db.partita(partita_id)
    if partita is None:
        _log.warning("Partita %s non trovata", partita_id)
        return None

    eventi = db.eventi_partita(partita_id)

    # Ricostruisci timeline
    punti, info = _ricostruisci_timeline(eventi)

    premio_finale = partita.premio_finale
    via_uscita = partita.via_uscita or "interrotta"
    pacco_reale = partita.pacco_reale

    if premio_finale is None:
        # Partita non conclusa: usa l'ultimo EV o 0
        premio_finale = int(punti[-1].ev) if punti else 0

    # Statistiche
    offerte = info["offerte"]
    evs = [p.ev for p in punti]
    dati = DatiReport(
        data_partita=_formatta_data(partita.data_inizio),
        premio_finale=premio_finale,
        via_uscita=via_uscita,
        pacco_reale=pacco_reale,
        punti=punti,
        offerta_massima=max(offerte) if offerte else None,
        offerta_minima=min(offerte) if offerte else None,
        n_offerte=len(offerte),
        ev_massimo=max(evs) if evs else 0.0,
        ev_minimo=min(evs) if evs else 0.0,
        n_pacchi_aperti=info["n_pacchi_aperti"],
        confronto_strategie={},  # per ora vuoto, lo riempiamo dopo
        commento=_genera_commento(punti, premio_finale, via_uscita, pacco_reale),
    )
    return dati


def _formatta_data(iso: str) -> str:
    """Converte una data ISO in formato leggibile italiano."""
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return iso


__all__ = [
    "costruisci_dati_report",
]