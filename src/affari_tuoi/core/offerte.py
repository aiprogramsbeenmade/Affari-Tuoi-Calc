"""
Modelli di offerta del Dottore per Affari Tuoi.

Il Dottore non ha una formula pubblica. Qui modelliamo il suo comportamento
con diverse strategie, tutte intercambiabili tramite la Protocol `ModelloOfferta`.

Le offerte reali tendono a:
- essere una frazione dell'EV dei pacchi chiusi
- crescere in percentuale man mano che si va avanti (meno incertezza)
- avere una componente di "spettacolarità" (numeri tondi, rumore)

Riferimenti empirici (approssimativi) dalle puntate italiane:
- primi turni: 20-35% dell'EV
- turni intermedi: 40-60%
- ultimi turni (3-5 pacchi): 70-95%
- con 2 pacchi: spesso 80-100%, a volte con offerta "spacca" (rara)
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol

from affari_tuoi.core.partita import Partita
from affari_tuoi.core.statistiche import valore_atteso_pacchi_chiusi


# ---------------------------------------------------------------------------
# Interfaccia comune
# ---------------------------------------------------------------------------

class ModelloOfferta(Protocol):
    """Contratto per qualsiasi modello di offerta del Dottore."""

    def calcola(self, partita: Partita) -> int:
        """
        Calcola l'offerta del Dottore per lo stato attuale.

        Args:
            partita: stato corrente della partita.

        Returns:
            Offerta in euro (intero).
        """
        ...

    @property
    def nome(self) -> str:
        """Nome descrittivo del modello (per log e bot)."""
        ...


# ---------------------------------------------------------------------------
# Utility: frazione dell'EV in funzione dell'avanzamento
# ---------------------------------------------------------------------------

def frazione_ev_da_turno(n_pacchi_chiusi: int) -> float:
    """
    Stima la frazione dell'EV che il Dottore tende a offrire.

    Modello: interpolazione lineare tra due estremi empirici.
    - Con 20 pacchi chiusi: ~0.25 (25% dell'EV)
    - Con 2 pacchi chiusi:  ~0.90 (90% dell'EV)

    Args:
        n_pacchi_chiusi: numero di pacchi ancora chiusi (incluso il giocatore).

    Returns:
        Frazione in [0.2, 1.0].
    """
    n = max(2, min(20, n_pacchi_chiusi))
    # interpolazione lineare: 20 -> 0.25, 2 -> 0.90
    t = (20 - n) / (20 - 2)   # 0 con 20 pacchi, 1 con 2 pacchi
    frazione = 0.25 + t * (0.90 - 0.25)
    return min(frazione, 1.0)


def arrotonda_offerta(valore: float) -> int:
    """
    Arrotonda un'offerta a un numero 'presentabile' in TV.

    Il Dottore non offre mai 47.382 EUR: offre 47.000 o 47.500.
    Qui arrotondiamo in modo progressivo in base all'ordine di grandezza.
    """
    if valore <= 0:
        return 0
    if valore < 1_000:
        return int(round(valore / 10) * 10)          # multipli di 10
    if valore < 10_000:
        return int(round(valore / 100) * 100)         # multipli di 100
    if valore < 100_000:
        return int(round(valore / 500) * 500)         # multipli di 500
    return int(round(valore / 1_000) * 1_000)         # multipli di 1000


# ---------------------------------------------------------------------------
# Modello 1: percentuale dell'EV, deterministico
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class OffertaPercentualeEV:
    """
    Offerta = frazione(turno) * EV.

    Deterministico, utile per simulazioni pulite e per capire i limiti
    teorici della strategia "accetta se offerta >= EV".
    """

    @property
    def nome(self) -> str:
        return "OffertaPercentualeEV"

    def calcola(self, partita: Partita) -> int:
        ev = valore_atteso_pacchi_chiusi(partita)
        n = partita.n_pacchi_chiusi
        frazione = frazione_ev_da_turno(n)
        return arrotonda_offerta(ev * frazione)


# ---------------------------------------------------------------------------
# Modello 2: percentuale dell'EV con rumore
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class OffertaPercentualeEVConRumore:
    """
    Offerta = frazione(turno) * EV * (1 + rumore gaussiano).

    Più realistico: introduce varianza, quindi anche la strategia
    "accetta se >= EV" non è più banalmente ottimale.

    Attributes:
        sigma: deviazione standard del rumore moltiplicativo (default 0.08).
        rng: generatore random opzionale (per test deterministici).
        cap: limite superiore come frazione dell'EV (default 1.0).
        floor: limite inferiore come frazione dell'EV (default 0.10).
    """

    sigma: float = 0.08
    cap: float = 1.0
    floor: float = 0.10
    rng: random.Random | None = None

    @property
    def nome(self) -> str:
        return f"OffertaPercentualeEVConRumore(sigma={self.sigma})"

    def calcola(self, partita: Partita) -> int:
        ev = valore_atteso_pacchi_chiusi(partita)
        n = partita.n_pacchi_chiusi
        frazione = frazione_ev_da_turno(n)

        rng = self.rng or random.Random()
        rumore = rng.gauss(0.0, self.sigma)
        frazione_rumorosa = frazione * (1.0 + rumore)

        # clamp tra floor e cap (relativi all'EV)
        frazione_rumorosa = max(self.floor, min(self.cap, frazione_rumorosa))

        return arrotonda_offerta(ev * frazione_rumorosa)


# ---------------------------------------------------------------------------
# Modello 3: agganciato alla fase finale (cambio)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class OffertaFinaleDuePacchi:
    """
    Offerta del Dottore quando restano 2 pacchi (situazione da cambio).

    In questa fase il Dottore tende a offrire una frazione alta dell'EV,
    e a volte propone anche il cambio. Qui modelliamo solo l'offerta in
    denaro; la logica del cambio vive in cambio.py.
    """

    frazione_base: float = 0.85
    sigma: float = 0.07
    rng: random.Random | None = None

    @property
    def nome(self) -> str:
        return f"OffertaFinaleDuePacchi(frazione_base={self.frazione_base})"

    def calcola(self, partita: Partita) -> int:
        if partita.n_pacchi_chiusi != 2:
            raise ValueError(
                "OffertaFinaleDuePacchi richiede esattamente 2 pacchi chiusi, "
                f"trovati {partita.n_pacchi_chiusi}."
            )
        ev = valore_atteso_pacchi_chiusi(partita)
        rng = self.rng or random.Random()
        rumore = rng.gauss(0.0, self.sigma)
        frazione = max(0.5, min(1.2, self.frazione_base * (1.0 + rumore)))
        return arrotonda_offerta(ev * frazione)


# ---------------------------------------------------------------------------
# Factory di comodo
# ---------------------------------------------------------------------------

def modello_default(seed: int | None = None) -> ModelloOfferta:
    """
    Restituisce il modello di offerta consigliato per l'uso generale.

    Args:
        seed: se passato, il modello usa un RNG deterministico.
    """
    rng = random.Random(seed) if seed is not None else None
    return OffertaPercentualeEVConRumore(rng=rng)


__all__ = [
    "ModelloOfferta",
    "frazione_ev_da_turno",
    "arrotonda_offerta",
    "OffertaPercentualeEV",
    "OffertaPercentualeEVConRumore",
    "OffertaFinaleDuePacchi",
    "modello_default",
]