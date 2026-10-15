"""
Simulazione Monte Carlo di partite di Affari Tuoi.

Esegue N partite con una data Policy e aggrega i risultati in un
ReportSimulazione, con statistiche descrittive complete:
- payout medio, mediano, deviazione standard
- percentili (p5, p25, p50, p75, p95)
- frequenza di accettazione delle offerte
- frequenza del cambio
- frequenza di arrivo al pacco finale
- offerte medie ricevute

I report sono serializzabili (to_dict, to_json) e confrontabili.
"""

from __future__ import annotations

import json
import random
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from affari_tuoi.core.offerte import (
    ModelloOfferta,
    OffertaPercentualeEVConRumore,
    modello_default,
)
from affari_tuoi.simulazione.policy import Policy, RisultatoPartita, gioca_partita


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ReportSimulazione:
    """Risultati aggregati di una simulazione Monte Carlo."""

    policy: str
    n_partite: int
    seed: int | None

    # Statistiche payout
    payout_medio: float
    payout_mediano: float
    payout_std: float
    payout_min: int
    payout_max: int
    percentili: dict[int, float]
    """Percentili chiave: 5, 25, 50, 75, 95."""

    # Frequenze per via di uscita
    freq_offerta: float
    freq_cambio: float
    freq_pacco_finale: float

    # Altre statistiche
    turno_medio_uscita: float
    offerte_medie_ricevute: float
    n_offerte_medio: float
    n_valori_aperti_medio: float

    def to_dict(self) -> dict[str, Any]:
        """Converte il report in un dizionario serializzabile."""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Serializza il report in JSON."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def riga_tabella(self) -> str:
        """Riga formattata per una tabella di confronto."""
        return (
            f"{self.policy:<28} | "
            f"{self.payout_medio:>12,.0f} | "
            f"{self.payout_mediano:>12,.0f} | "
            f"{self.percentili[5]:>10,.0f} | "
            f"{self.percentili[95]:>10,.0f} | "
            f"{self.freq_offerta:>6.1%} | "
            f"{self.freq_cambio:>6.1%}"
        )

    @staticmethod
    def intestazione_tabella() -> str:
        return (
            f"{'Policy':<28} | "
            f"{'Media':>12} | "
            f"{'Mediana':>12} | "
            f"{'p5':>10} | "
            f"{'p95':>10} | "
            f"{'Acc.':>6} | "
            f"{'Cambio':>6}"
        )


# ---------------------------------------------------------------------------
# Funzione principale
# ---------------------------------------------------------------------------

def simula_molte_partite(
    policy: Policy,
    n_partite: int,
    *,
    modello_offerta: ModelloOfferta | None = None,
    seed: int | None = None,
) -> ReportSimulazione:
    """
    Simula N partite con la policy data e aggrega i risultati.

    Args:
        policy: strategia del giocatore.
        n_partite: numero di partite da simulare.
        modello_offerta: modello di offerta del Dottore. Se None, usa
            `modello_default(seed)`.
        seed: se passato, rende la simulazione riproducibile.

    Returns:
        ReportSimulazione con tutte le statistiche.

    Raises:
        ValueError: se n_partite <= 0.
    """
    if n_partite <= 0:
        raise ValueError(f"n_partite deve essere > 0, ricevuto {n_partite}")

    if modello_offerta is None:
        modello_offerta = modello_default(seed=seed)

    rng = random.Random(seed)

    risultati: list[RisultatoPartita] = []
    for i in range(n_partite):
        # Ogni partita usa un seed derivato per garantire indipendenza
        # e riproducibilità anche quando il modello ha rumore interno.
        seed_partita = rng.randrange(2**32)
        rng_partita = random.Random(seed_partita)
        r = gioca_partita(policy, rng_partita, modello_offerta)
        risultati.append(r)

    return _aggrega(risultati, policy.nome, seed)


# ---------------------------------------------------------------------------
# Aggregazione
# ---------------------------------------------------------------------------

def _aggrega(
    risultati: list[RisultatoPartita],
    policy_nome: str,
    seed: int | None,
) -> ReportSimulazione:
    """Calcola le statistiche aggregate dai risultati delle partite."""
    n = len(risultati)
    payouts = [r.premio for r in risultati]

    # Statistiche payout
    payout_medio = statistics.fmean(payouts)
    payout_mediano = statistics.median(payouts)
    payout_std = statistics.pstdev(payouts) if n > 1 else 0.0
    payout_min = min(payouts)
    payout_max = max(payouts)

    # Percentili
    percentili = _calcola_percentili(payouts, [5, 25, 50, 75, 95])

    # Frequenze via di uscita
    n_offerta = sum(1 for r in risultati if r.via_di_uscita == "offerta")
    n_cambio = sum(1 for r in risultati if r.via_di_uscita == "cambio")
    n_pacco = sum(1 for r in risultati if r.via_di_uscita == "pacco_finale")

    # Altre statistiche
    turni_uscita = [r.turno_uscita for r in risultati]
    n_offerte = [len(r.offerte_ricevute) for r in risultati]
    offerte_medie = [
        statistics.fmean(r.offerte_ricevute) if r.offerte_ricevute else 0.0
        for r in risultati
    ]
    n_aperti = [len(r.valori_aperti) for r in risultati]

    return ReportSimulazione(
        policy=policy_nome,
        n_partite=n,
        seed=seed,
        payout_medio=payout_medio,
        payout_mediano=payout_mediano,
        payout_std=payout_std,
        payout_min=payout_min,
        payout_max=payout_max,
        percentili=percentili,
        freq_offerta=n_offerta / n,
        freq_cambio=n_cambio / n,
        freq_pacco_finale=n_pacco / n,
        turno_medio_uscita=statistics.fmean(turni_uscita),
        offerte_medie_ricevute=statistics.fmean(offerte_medie),
        n_offerte_medio=statistics.fmean(n_offerte),
        n_valori_aperti_medio=statistics.fmean(n_aperti),
    )


def _calcola_percentili(valori: list[int], percentili: Iterable[int]) -> dict[int, float]:
    """
    Calcola i percentili con interpolazione lineare (metodo 'inclusive').

    Implementazione manuale per non dipendere da numpy.
    """
    ordinati = sorted(valori)
    n = len(ordinati)
    risultato: dict[int, float] = {}
    for p in percentili:
        if not 0 <= p <= 100:
            raise ValueError(f"percentile fuori range: {p}")
        if n == 1:
            risultato[p] = float(ordinati[0])
            continue
        # Posizione nel ranking (metodo inclusive di NIST)
        k = (p / 100) * (n - 1)
        f = int(k)
        c = min(f + 1, n - 1)
        if f == c:
            risultato[p] = float(ordinati[f])
        else:
            d = k - f
            risultato[p] = ordinati[f] * (1 - d) + ordinati[c] * d
    return risultato


# ---------------------------------------------------------------------------
# Confronto tra policy
# ---------------------------------------------------------------------------

def confronta_policy(
    policies: list[Policy],
    n_partite: int,
    *,
    modello_offerta: ModelloOfferta | None = None,
    seed: int | None = None,
) -> list[ReportSimulazione]:
    """
    Simula più policy con gli stessi parametri e restituisce i report.

    Utile per il confronto A/B e per capire quale strategia rende di più.

    Args:
        policies: lista di policy da confrontare.
        n_partite: partite per ciascuna policy.
        modello_offerta: modello comune a tutte le policy.
        seed: seed comune (ogni policy usa una derivazione per indipendenza).

    Returns:
        Lista di ReportSimulazione nell'ordine delle policy.
    """
    if not policies:
        raise ValueError("serve almeno una policy")

    if modello_offerta is None:
        modello_offerta = modello_default(seed=seed)

    reports: list[ReportSimulazione] = []
    for i, pol in enumerate(policies):
        # Ogni policy ha il proprio seed per garantire indipendenza
        seed_pol = None if seed is None else seed + i * 1_000_003
        report = simula_molte_partite(
            pol,
            n_partite,
            modello_offerta=modello_offerta,
            seed=seed_pol,
        )
        reports.append(report)
    return reports


def formatta_tabella(reports: list[ReportSimulazione]) -> str:
    """Formatta una lista di report come tabella testuale."""
    righe = [
        ReportSimulazione.intestazione_tabella(),
        "-" * len(ReportSimulazione.intestazione_tabella()),
    ]
    for r in reports:
        righe.append(r.riga_tabella())
    return "\n".join(righe)


__all__ = [
    "ReportSimulazione",
    "simula_molte_partite",
    "confronta_policy",
    "formatta_tabella",
]