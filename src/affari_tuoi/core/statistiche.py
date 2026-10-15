"""
Statistiche e probabilità per una partita di Affari Tuoi.

Qui vive tutta la matematica "descrittiva" dello stato della partita:
- valore atteso dei pacchi ancora in gioco
- probabilità che il pacco del giocatore contenga un certo valore
- entropia / incertezza residua
- soglie di riferimento per le decisioni

Nessuna logica decisionale: solo numeri.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping

from affari_tuoi.core.partita import Partita
from affari_tuoi.core.premi import carica_configurazione_premi


# ---------------------------------------------------------------------------
# Valore atteso
# ---------------------------------------------------------------------------

def valore_atteso(valori: Iterable[int]) -> float:
    """
    Media aritmetica dei valori passati.

    Args:
        valori: iterabile di interi (es. valori dei pacchi chiusi).

    Returns:
        La media come float.

    Raises:
        ValueError: se l'iterabile è vuoto.
    """
    lista = list(valori)
    if not lista:
        raise ValueError("valore_atteso richiede almeno un valore")
    return sum(lista) / len(lista)


def valore_atteso_pacchi_chiusi(partita: Partita) -> float:
    """
    EV dei pacchi ancora chiusi (incluso quello del giocatore).

    È la cifra che il Dottore tipicamente usa come ancora per l'offerta.
    """
    return valore_atteso(partita.stato_pacchi.valori_chiusi())


# ---------------------------------------------------------------------------
# Distribuzione del pacco del giocatore
# ---------------------------------------------------------------------------

def distribuzione_pacco_giocatore(partita: Partita) -> dict[int, float]:
    """
    Distribuzione di probabilità del valore nel pacco del giocatore.

    Senza informazioni asimmetriche, ogni pacco chiuso ha la stessa
    probabilità di essere quello del giocatore. Quindi la probabilità
    che il pacco del giocatore valga `v` è:

        P(valore = v) = (numero di pacchi chiusi con valore v) / (numero di pacchi chiusi)

    Nota: i premi sono tutti distinti, quindi la probabilità è uniforme
    su ogni pacco chiuso. In futuro, se introduciamo informazioni
    asimmetriche (es. il Dottore sa), questa funzione va raffinata.

    Returns:
        Dizionario {valore: probabilità}, normalizzato a 1.0.
    """
    valori = partita.stato_pacchi.valori_chiusi()
    if not valori:
        return {}
    conteggi = Counter(valori)
    n = len(valori)
    return {v: c / n for v, c in conteggi.items()}


def probabilita_pacco_giocatore_almeno(
    partita: Partita,
    soglia: int,
) -> float:
    """
    P(valore nel pacco del giocatore >= soglia).

    Utile per il bot: "quanto è probabile che rifiutando un'offerta di X
    io faccia meglio di X?".
    """
    dist = distribuzione_pacco_giocatore(partita)
    return sum(p for v, p in dist.items() if v >= soglia)


def probabilita_pacco_giocatore_tra(
    partita: Partita,
    minimo: int,
    massimo: int,
) -> float:
    """P(minimo <= valore nel pacco del giocatore <= massimo)."""
    dist = distribuzione_pacco_giocatore(partita)
    return sum(p for v, p in dist.items() if minimo <= v <= massimo)


# ---------------------------------------------------------------------------
# Entropia e incertezza
# ---------------------------------------------------------------------------

def entropia(valori: Iterable[int]) -> float:
    """
    Entropia di Shannon della distribuzione uniforme sui valori distinti.

    Misura l'incertezza residua: 0 = un solo valore possibile,
    log2(n) = massima incertezza su n valori distinti.

    Utile per capire "quanto è ancora aperto" il gioco.
    """
    lista = list(valori)
    if not lista:
        return 0.0
    distinti = len(set(lista))
    return math.log2(distinti) if distinti > 1 else 0.0


def entropia_pacchi_chiusi(partita: Partita) -> float:
    """Entropia dello stato attuale: quanti valori distinti sono ancora in gioco."""
    return entropia(partita.stato_pacchi.valori_chiusi())


# ---------------------------------------------------------------------------
# Soglie di riferimento
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SoglieOfferta:
    """
    Punti di riferimento per valutare un'offerta del Dottore.

    Attributes:
        ev: valore atteso dei pacchi chiusi.
        soglia_equa: offerta uguale all'EV (indifferente in EV puro).
        soglia_prudente: 70% dell'EV (tipicamente accettata da chi è avverso).
        soglia_aggressiva: 130% dell'EV (serve coraggio per accettarla).
        offerta_massima_possibile: il valore più alto ancora in gioco.
    """

    ev: float
    soglia_equa: float
    soglia_prudente: float
    soglia_aggressiva: float
    offerta_massima_possibile: int

    def valuta(self, offerta: float) -> str:
        """Classifica un'offerta rispetto alle soglie."""
        if offerta >= self.soglia_aggressiva:
            return "OTTIMA"
        if offerta >= self.soglia_equa:
            return "BUONA"
        if offerta >= self.soglia_prudente:
            return "MEDIA"
        return "SCARSA"


def calcola_soglie(partita: Partita) -> SoglieOfferta:
    """Calcola le soglie di riferimento dallo stato attuale della partita."""
    ev = valore_atteso_pacchi_chiusi(partita)
    massimo = max(partita.stato_pacchi.valori_chiusi())
    return SoglieOfferta(
        ev=ev,
        soglia_equa=ev,
        soglia_prudente=0.7 * ev,
        soglia_aggressiva=1.3 * ev,
        offerta_massima_possibile=massimo,
    )


# ---------------------------------------------------------------------------
# Statistiche riassuntive (comode per il bot)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class StatistichePartita:
    """Fotografia statistica dello stato attuale della partita."""

    n_pacchi_chiusi: int
    n_pacchi_aperti: int
    ev: float
    massimo_in_gioco: int
    minimo_in_gioco: int
    entropia: float
    valore_medio_pacco_giocatore: float
    probabilita_almeno_ev: float
    probabilita_almeno_100k: float


def statistiche_partita(partita: Partita) -> StatistichePartita:
    """Calcola un riassunto statistico completo dello stato attuale."""
    valori = partita.stato_pacchi.valori_chiusi()
    ev = valore_atteso(valori)
    dist = distribuzione_pacco_giocatore(partita)
    ev_giocatore = sum(v * p for v, p in dist.items())

    return StatistichePartita(
        n_pacchi_chiusi=len(valori),
        n_pacchi_aperti=len(partita.stato_pacchi.ids_aperti),
        ev=ev,
        massimo_in_gioco=max(valori),
        minimo_in_gioco=min(valori),
        entropia=entropia(valori),
        valore_medio_pacco_giocatore=ev_giocatore,
        probabilita_almeno_ev=probabilita_pacco_giocatore_almeno(partita, int(ev)),
        probabilita_almeno_100k=probabilita_pacco_giocatore_almeno(partita, 100_000),
    )


__all__ = [
    "valore_atteso",
    "valore_atteso_pacchi_chiusi",
    "distribuzione_pacco_giocatore",
    "probabilita_pacco_giocatore_almeno",
    "probabilita_pacco_giocatore_tra",
    "entropia",
    "entropia_pacchi_chiusi",
    "SoglieOfferta",
    "calcola_soglie",
    "StatistichePartita",
    "statistiche_partita",
]