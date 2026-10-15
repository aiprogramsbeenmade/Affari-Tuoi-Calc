"""
Logica del cambio e analisi bayesiana.

Il Dottore può offrire al giocatore di scambiare il proprio pacco con
un altro pacco chiuso. Poiché il Dottore conosce il contenuto dei
pacchi, l'offerta del cambio è un segnale: possiamo inferire qualcosa
sul contenuto del nostro pacco osservando se il cambio è stato offerto.

Modello:

- Siano N i pacchi chiusi (giocatore + altri).
- Assegniamo a ogni pacco un "rango" 1..N in base al valore (1 = più alto).
- Prior uniforme: P(tuo pacco = rango r) = 1/N per ogni r.
- Verosimiglianza: la politica del Dottore è una funzione
      L(r) = P(offre cambio | tuo pacco = rango r)
  modellata come sigmoide della posizione relativa:
      t = (r - 1) / (N - 1)          # 0 se r=1, 1 se r=N
      L(r) = sigmoid(alpha + beta * t)
- Posterior via Bayes:
      P(r | cambio offerto) ∝ L(r) * P(r)
- Da r risaliamo al valore effettivo: l'r-esimo valore più alto in gioco.

Interpretazione dei parametri:

- alpha controlla la probabilità media di offrire il cambio
- beta > 0: il Dottore è malevolo (offre più spesso se il tuo pacco è alto)
- beta < 0: il Dottore è benevolo (offre più spesso se il tuo pacco è basso)
- beta = 0: politica neutrale, il cambio è ininfluente in EV

Riferimenti:
- Bayes (1763), teorema di Bayes.
- Kamenica & Gentzkow (2011), Bayesian persuasion.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from affari_tuoi.core.partita import Partita


# ---------------------------------------------------------------------------
# Enum del consiglio
# ---------------------------------------------------------------------------

class ConsiglioCambio(Enum):
    """Esito del consiglio sul cambio."""

    ACCETTA_CAMBIO = auto()
    RIFIUTA_CAMBIO = auto()
    INDIFFERENTE = auto()

    def __str__(self) -> str:
        return {
            ConsiglioCambio.ACCETTA_CAMBIO: "ACCETTA IL CAMBIO",
            ConsiglioCambio.RIFIUTA_CAMBIO: "RIFIUTA IL CAMBIO",
            ConsiglioCambio.INDIFFERENTE: "INDIFFERENTE",
        }[self]


# ---------------------------------------------------------------------------
# Politica del Dottore
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PoliticaCambio:
    """
    Politica del Dottore riguardo all'offerta del cambio.

    La verosimiglianza è modellata come:
        L(r) = sigmoid(alpha + beta * (r - 1) / (N - 1))

    dove r è il rango del pacco del giocatore (1 = più alto, N = più basso).

    Attributes:
        alpha: offset della sigmoide. Con alpha = 0 la probabilità media
            di offrire il cambio è 50%.
        beta: pendenza. beta > 0 = malevola (offre più spesso se il tuo
            pacco è alto); beta < 0 = benevola; beta = 0 = neutrale.
    """

    alpha: float = 0.0
    beta: float = 0.0

    def verosimiglianza(self, rango: int, n_pacchi: int) -> float:
        """
        P(offre cambio | rango del tuo pacco = rango).

        Il parametro beta descrive la dipendenza dal VALORE del pacco:
        - beta > 0: il Dottore offre il cambio più spesso se il tuo pacco
          è alto (malevola)
        - beta < 0: il Dottore offre il cambio più spesso se il tuo pacco
          è basso (benevola)
        - beta = 0: neutrale

        Args:
            rango: rango del pacco del giocatore (1 = più alto, N = più basso).
            n_pacchi: numero totale di pacchi chiusi.
        """
        if n_pacchi < 2:
            raise ValueError(f"n_pacchi deve essere >= 2, ricevuto {n_pacchi}")
        if not 1 <= rango <= n_pacchi:
            raise ValueError(
                f"rango fuori intervallo: {rango} non in [1, {n_pacchi}]"
            )
        # t = 1 se rango=1 (pacco più alto), t = 0 se rango=N (pacco più basso)
        if n_pacchi == 2:
            t = 1.0 if rango == 1 else 0.0
        else:
            t = 1.0 - (rango - 1) / (n_pacchi - 1)
        z = self.alpha + self.beta * t
        return _sigmoid(z)

# ---------------------------------------------------------------------------
# Preset di politiche
# ---------------------------------------------------------------------------

def politica_neutrale() -> PoliticaCambio:
    """
    Il Dottore offre il cambio con la stessa probabilità per ogni rango.

    Il cambio è ininfluente in EV: posterior = prior.
    """
    return PoliticaCambio(alpha=0.0, beta=0.0)


def politica_malevola(intensita: float = 2.0) -> PoliticaCambio:
    """
    Il Dottore offre il cambio più spesso quando il tuo pacco è ALTO.

    Se osservi un'offerta di cambio, la probabilità che il tuo pacco
    sia quello alto aumenta → meglio rifiutare il cambio.

    Args:
        intensita: quanto è forte la dipendenza dal rango (beta).
    """
    return PoliticaCambio(alpha=0.0, beta=intensita)


def politica_benevola(intensita: float = 2.0) -> PoliticaCambio:
    """
    Il Dottore offre il cambio più spesso quando il tuo pacco è BASSO.

    Se osservi un'offerta di cambio, la probabilità che il tuo pacco
    sia quello basso aumenta → meglio accettare il cambio.
    """
    return PoliticaCambio(alpha=0.0, beta=-intensita)


def _sigmoid(z: float) -> float:
    """Sigmoide numericamente stabile."""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


# ---------------------------------------------------------------------------
# Analisi bayesiana
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AnalisiCambio:
    """
    Risultato dell'analisi bayesiana del cambio.

    Attributes:
        n_pacchi: numero di pacchi chiusi al momento dell'offerta.
        valori_in_gioco: valori (ordinati decrescenti) dei pacchi chiusi.
        probabilita_per_rango: posterior su ogni rango (1..N), somma a 1.0.
        probabilita_per_valore: posterior sul valore del pacco del giocatore.
        ev_tuo_pacco: EV posterior del pacco del giocatore.
        ev_pacco_alternativo: EV posterior del pacco alternativo (complementare).
        consiglio: ACCETTA_CAMBIO, RIFIUTA_CAMBIO, o INDIFFERENTE.
        margine: differenza di EV (alternativo - tuo). Positivo = conviene cambiare.
        motivo: spiegazione leggibile.
    """

    n_pacchi: int
    valori_in_gioco: tuple[int, ...]
    probabilita_per_rango: dict[int, float]
    probabilita_per_valore: dict[int, float]
    ev_tuo_pacco: float
    ev_pacco_alternativo: float
    consiglio: ConsiglioCambio
    margine: float
    motivo: str
    dettagli: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return (
            f"{self.consiglio} — "
            f"EV tuo pacco {self.ev_tuo_pacco:,.0f} EUR, "
            f"EV alternativo {self.ev_pacco_alternativo:,.0f} EUR "
            f"(margine {self.margine:+,.0f})"
        )


# ---------------------------------------------------------------------------
# Calcolo principale
# ---------------------------------------------------------------------------

def analizza_cambio(
    partita: Partita,
    politica: PoliticaCambio,
    *,
    cambio_offerto: bool = True,
    tolleranza: float = 0.0,
) -> AnalisiCambio:
    """
    Analizza il cambio applicando Bayes alla politica del Dottore.

    Args:
        partita: stato della partita (almeno 2 pacchi chiusi).
        politica: politica del Dottore.
        cambio_offerto: se True, condiziona sull'offerta osservata; se
            False, restituisce il prior (nessuna informazione).
        tolleranza: margine in euro sotto il quale il consiglio è
            INDIFFERENTE (default 0 = mai indifferente).

    Returns:
        AnalisiCambio con posterior, EV e consiglio.

    Raises:
        ValueError: se ci sono meno di 2 pacchi chiusi.
    """
    valori = sorted(partita.stato_pacchi.valori_chiusi(), reverse=True)
    n = len(valori)
    if n < 2:
        raise ValueError(
            f"servono almeno 2 pacchi chiusi per il cambio, trovati {n}"
        )

    # Prior uniforme su ogni rango
    prior = {r: 1.0 / n for r in range(1, n + 1)}

    # Verosimiglianza
    if cambio_offerto:
        verosim = {r: politica.verosimiglianza(r, n) for r in range(1, n + 1)}
    else:
        verosim = {r: 1.0 for r in range(1, n + 1)}

    # Posterior non normalizzato
    non_norm = {r: prior[r] * verosim[r] for r in range(1, n + 1)}
    z = sum(non_norm.values())
    if z <= 0:
        raise RuntimeError(
            "posterior degenere: la verosimiglianza è 0 per tutti i ranghi. "
            "Controlla la politica (alpha/beta)."
        )
    posterior = {r: non_norm[r] / z for r in range(1, n + 1)}

    # Mappa rango -> valore
    valore_per_rango = {r: valori[r - 1] for r in range(1, n + 1)}

    # Posterior sul valore del pacco del giocatore
    prob_per_valore: dict[int, float] = {}
    for r, p in posterior.items():
        v = valore_per_rango[r]
        prob_per_valore[v] = prob_per_valore.get(v, 0.0) + p

    # EV tuo pacco (posterior)
    ev_tuo = sum(v * p for v, p in prob_per_valore.items())

    # EV del pacco alternativo: se il tuo pacco è il r-esimo,
    # l'alternativo è uno qualsiasi degli altri n-1 pacchi rimasti,
    # uniformemente. In particolare, il "pacco alternativo" che il
    # Dottore ti fa scegliere è il pacchetto di tutti i pacchi NON tuoi.
    # Se ci sono n pacchi e n-1 sono alternativi, l'EV dell'alternativo
    # è la media degli altri.
    ev_totale = sum(valori) / n
    ev_alternativo = (n * ev_totale - ev_tuo) / (n - 1) if n > 1 else 0.0

    margine = ev_alternativo - ev_tuo
    if margine > tolleranza:
        consiglio = ConsiglioCambio.ACCETTA_CAMBIO
        motivo = (
            f"EV alternativo ({ev_alternativo:,.0f}) > "
            f"EV tuo pacco ({ev_tuo:,.0f}): il cambio è favorevole"
        )
    elif margine < -tolleranza:
        consiglio = ConsiglioCambio.RIFIUTA_CAMBIO
        motivo = (
            f"EV tuo pacco ({ev_tuo:,.0f}) > "
            f"EV alternativo ({ev_alternativo:,.0f}): il cambio è sfavorevole"
        )
    else:
        consiglio = ConsiglioCambio.INDIFFERENTE
        motivo = "il cambio è indifferente in EV"

    return AnalisiCambio(
        n_pacchi=n,
        valori_in_gioco=tuple(valori),
        probabilita_per_rango=posterior,
        probabilita_per_valore=prob_per_valore,
        ev_tuo_pacco=ev_tuo,
        ev_pacco_alternativo=ev_alternativo,
        consiglio=consiglio,
        margine=margine,
        motivo=motivo,
        dettagli={
            "prior": prior,
            "verosimiglianza": verosim,
            "valore_per_rango": valore_per_rango,
            "cambio_offerto": cambio_offerto,
            "politica": {"alpha": politica.alpha, "beta": politica.beta},
        },
    )


# ---------------------------------------------------------------------------
# Decisione a tre vie (denaro vs cambio vs tenere)
# ---------------------------------------------------------------------------

class SceltaFinale(Enum):
    """Scelta a tre vie quando il Dottore offre sia denaro che cambio."""

    ACCETTA_DENARO = auto()
    ACCETTA_CAMBIO = auto()
    RIFIUTA_TUTTO = auto()

    def __str__(self) -> str:
        return {
            SceltaFinale.ACCETTA_DENARO: "ACCETTA IL DENARO",
            SceltaFinale.ACCETTA_CAMBIO: "ACCETTA IL CAMBIO",
            SceltaFinale.RIFIUTA_TUTTO: "RIFIUTA TUTTO (tieni il pacco)",
        }[self]


@dataclass(frozen=True, slots=True)
class AnalisiFinale:
    """Analisi completa a tre vie: denaro vs cambio vs tenere."""

    scelta: SceltaFinale
    ev_denaro: float
    ev_tuo_pacco: float
    ev_alternativo: float
    dettaglio: str

    def __str__(self) -> str:
        return (
            f"{self.scelta} — "
            f"denaro {self.ev_denaro:,.0f} | "
            f"tuo pacco {self.ev_tuo_pacco:,.0f} | "
            f"alternativo {self.ev_alternativo:,.0f}"
        )


def analizza_scelta_finale(
    partita: Partita,
    offerta_denaro: int,
    politica: PoliticaCambio,
    *,
    tolleranza: float = 0.0,
) -> AnalisiFinale:
    """
    Confronta le tre opzioni finali: denaro, cambio, tenere.

    Args:
        partita: stato della partita.
        offerta_denaro: offerta in denaro del Dottore (0 se assente).
        politica: politica del Dottore.
        tolleranza: margine di indifferenza.

    Returns:
        AnalisiFinale con la scelta consigliata.
    """
    analisi = analizza_cambio(partita, politica, cambio_offerto=True)

    opzioni = {
        SceltaFinale.ACCETTA_DENARO: float(offerta_denaro),
        SceltaFinale.ACCETTA_CAMBIO: analisi.ev_pacco_alternativo,
        SceltaFinale.RIFIUTA_TUTTO: analisi.ev_tuo_pacco,
    }

    scelta = max(opzioni, key=opzioni.get)  # type: ignore[arg-type]
    # Verifica indifferenza
    massimo = opzioni[scelta]
    altri = [v for k, v in opzioni.items() if k != scelta]
    if altri and abs(massimo - max(altri)) <= tolleranza:
        # Ambiguo: preferisci denaro > cambio > tenere per prudenza
        scelta = SceltaFinale.ACCETTA_DENARO

    return AnalisiFinale(
        scelta=scelta,
        ev_denaro=float(offerta_denaro),
        ev_tuo_pacco=analisi.ev_tuo_pacco,
        ev_alternativo=analisi.ev_pacco_alternativo,
        dettaglio=analisi.motivo,
    )


__all__ = [
    "ConsiglioCambio",
    "PoliticaCambio",
    "politica_neutrale",
    "politica_malevola",
    "politica_benevola",
    "AnalisiCambio",
    "analizza_cambio",
    "SceltaFinale",
    "AnalisiFinale",
    "analizza_scelta_finale",
]