"""
Criteri di decisione per accettare o rifiutare un'offerta del Dottore.

Ogni criterio implementa la Protocol `CriterioDecisione` e restituisce
una `Decisione` (dataclass frozen) con:
- accetta: bool
- motivo: str leggibile
- confronto: dict con i numeri usati

Criteri implementati:
- DecisioneEV: puro valore atteso. Neutrale al rischio.
- DecisioneCRRA: utilità CRRA con sussistenza, output in certainty equivalent.
- DecisioneKelly: caso limite CRRA con gamma=1.
- DecisioneSogliaFissa: accetta se offerta >= x% dell'EV (baseline).

Modello di utilità (CRRA con sussistenza):
    u(x) = ((x + c) / scala)^(1 - gamma) / (1 - gamma)   se gamma != 1
    u(x) = log((x + c) / scala)                          se gamma == 1

dove:
- c: consumo di sussistenza in euro (default 5000). Sposta il punto di
  riferimento da 0 a -c, risolvendo il problema di u(0) -> -infinito per
  gamma > 1. È lo standard in macroeconomia (modelli con "subsistence
  consumption").
- scala: unità di riferimento (tipicamente il premio massimo in gioco).
  Rende l'utilità adimensionale e invariante per cambio di unità.

Il certainty equivalent (CE) è la cifra certa che rende il decisore
indifferente tra riceverla e affrontare la distribuzione rischiosa:
    CE = u^{-1}( E[u(X)] ) - c
(clippato a 0 se negativo.)

Riferimenti:
- von Neumann & Morgenstern (1944), teoria dell'utilità attesa.
- Arrow (1971) e Pratt (1964), avversione al rischio.
- Kelly (1956), crescita logaritmica ottimale.
- Ogaki & Zhang (2001), CRRA con sussistenza.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol

from affari_tuoi.core.partita import Partita
from affari_tuoi.core.statistiche import distribuzione_pacco_giocatore


# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------

SUSSISTENZA_DEFAULT: float = 5_000.0
"""Consumo di sussistenza di default, in euro."""


# ---------------------------------------------------------------------------
# Risultato
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Decisione:
    """Risultato di un criterio di decisione."""

    accetta: bool
    motivo: str
    criterio: str
    confronto: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        esito = "ACCETTA" if self.accetta else "RIFIUTA"
        return f"[{self.criterio}] {esito} — {self.motivo}"


# ---------------------------------------------------------------------------
# Interfaccia
# ---------------------------------------------------------------------------

class CriterioDecisione(Protocol):
    """Contratto per un criterio di decisione."""

    @property
    def nome(self) -> str: ...

    def decidi(self, partita: Partita, offerta: int) -> Decisione: ...


# ---------------------------------------------------------------------------
# Utilità CRRA con sussistenza
# ---------------------------------------------------------------------------

def utilita_crra(
    x: float,
    gamma: float,
    scala: float,
    sussistenza: float = SUSSISTENZA_DEFAULT,
) -> float:
    """
    Utilità CRRA con sussistenza.

    Formula:
        u(x) = ((x + c) / scala)^(1 - gamma) / (1 - gamma)   se gamma != 1
        u(x) = log((x + c) / scala)                          se gamma == 1

    Args:
        x: valore monetario (>= 0).
        gamma: avversione al rischio relativa costante.
            0 = neutrale (u lineare)
            1 = logaritmica (Kelly)
            >1 = sempre più avverso
        scala: unità di riferimento (deve essere > 0).
        sussistenza: valore c >= 0 in euro.

    Raises:
        ValueError: se x < 0, gamma < 0, scala <= 0, o sussistenza < 0.
    """
    if x < 0:
        raise ValueError(f"utilita_crra richiede x >= 0, ricevuto {x}")
    if gamma < 0:
        raise ValueError(f"gamma deve essere >= 0, ricevuto {gamma}")
    if scala <= 0:
        raise ValueError(f"scala deve essere > 0, ricevuto {scala}")
    if sussistenza < 0:
        raise ValueError(f"sussistenza deve essere >= 0, ricevuto {sussistenza}")

    y = (x + sussistenza) / scala
    if math.isclose(gamma, 1.0):
        return math.log(y)
    return (y ** (1.0 - gamma)) / (1.0 - gamma)


def inversa_utilita_crra(
    u: float,
    gamma: float,
    scala: float,
    sussistenza: float = SUSSISTENZA_DEFAULT,
) -> float:
    """
    Inversa dell'utilità CRRA con sussistenza.

    Dato u = utilita_crra(x, gamma, scala, sussistenza), restituisce x.

    Formula (con y = u):
        y_inv = e^u                            se gamma == 1
        y_inv = ((1 - gamma) * u)^(1/(1-gamma)) se gamma != 1
        x = y_inv * scala - sussistenza

    Il risultato può essere negativo per input di utilità molto bassi;
    il chiamante è responsabile di clipparlo a 0 se serve (es. per il CE).
    """
    if gamma < 0:
        raise ValueError(f"gamma deve essere >= 0, ricevuto {gamma}")
    if scala <= 0:
        raise ValueError(f"scala deve essere > 0, ricevuto {scala}")
    if sussistenza < 0:
        raise ValueError(f"sussistenza deve essere >= 0, ricevuto {sussistenza}")

    if math.isclose(gamma, 1.0):
        y_inv = math.exp(u)
    else:
        base = (1.0 - gamma) * u
        if base < 0:
            raise ValueError(
                f"argomento negativo nella potenza: (1-gamma)*u = {base}"
            )
        y_inv = base ** (1.0 / (1.0 - gamma))

    return y_inv * scala - sussistenza


def certezza_equivalente(
    distribuzione: dict[int, float],
    gamma: float,
    scala: float,
    sussistenza: float = SUSSISTENZA_DEFAULT,
) -> float:
    """
    Certainty Equivalent (CE) di una distribuzione di premi, sotto CRRA
    con sussistenza. Il CE è restituito in euro ed è sempre >= 0.

    Args:
        distribuzione: {valore: probabilità}, deve sommare a 1.0.
        gamma: avversione al rischio.
        scala: unità di riferimento.
        sussistenza: valore c in euro.

    Returns:
        CE in euro (clippato a 0 se la formula dà valore negativo).
    """
    if not distribuzione:
        raise ValueError("distribuzione vuota")
    if gamma < 0:
        raise ValueError(f"gamma deve essere >= 0, ricevuto {gamma}")

    somma_p = 0.0
    u_attesa = 0.0
    for v, p in distribuzione.items():
        if p <= 0:
            continue
        u_attesa += p * utilita_crra(float(v), gamma, scala, sussistenza)
        somma_p += p

    if somma_p == 0:
        return 0.0
    u_attesa /= somma_p

    ce = inversa_utilita_crra(u_attesa, gamma, scala, sussistenza)
    return max(0.0, ce)


# ---------------------------------------------------------------------------
# 1. EV puro (neutrale al rischio)
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class DecisioneSogliaAdattiva:
    """
    Accetta se offerta >= frazione(turno) * EV.

    La frazione cresce col turno: all'inizio il giocatore è aggressivo
    (accetta solo offerte molto alte), alla fine è prudente (accetta
    anche frazioni alte dell'EV).

    Simula il comportamento umano: la propensione al rischio diminuisce
    man mano che il pacco "si materializza".

    Args:
        frazione_iniziale: soglia al turno 0 (default 0.4).
        frazione_finale: soglia al turno finale (default 0.9).
        n_turni: numero di turni attesi (default 7).
    """

    frazione_iniziale: float = 0.4
    frazione_finale: float = 0.9
    n_turni: int = 7

    def __post_init__(self) -> None:
        if not 0.0 <= self.frazione_iniziale <= 2.0:
            raise ValueError("frazione_iniziale fuori range")
        if not 0.0 <= self.frazione_finale <= 2.0:
            raise ValueError("frazione_finale fuori range")
        if self.n_turni <= 0:
            raise ValueError("n_turni deve essere > 0")

    @property
    def nome(self) -> str:
        return f"SogliaAdattiva({self.frazione_iniziale:.0%}->{self.frazione_finale:.0%})"

    def _frazione_corrente(self, turno: int) -> float:
        t = min(max(turno / max(1, self.n_turni - 1), 0.0), 1.0)
        return self.frazione_iniziale + t * (self.frazione_finale - self.frazione_iniziale)

    def decidi(self, partita: Partita, offerta: int) -> Decisione:
        n_chiusi = partita.n_pacchi_chiusi
        turno = max(0, 20 - n_chiusi - 1)
        frazione = self._frazione_corrente(turno)

        dist = distribuzione_pacco_giocatore(partita)
        ev = sum(v * p for v, p in dist.items())
        soglia = ev * frazione
        accetta = offerta >= soglia
        motivo = (
            f"[turno≈{turno}, soglia={frazione:.0%} EV] "
            f"offerta {offerta:,.0f} EUR >= {soglia:,.0f} EUR"
            if accetta
            else f"[turno≈{turno}, soglia={frazione:.0%} EV] "
            f"offerta {offerta:,.0f} EUR < {soglia:,.0f} EUR"
        )
        return Decisione(
            accetta=accetta,
            motivo=motivo,
            criterio=self.nome,
            confronto={
                "turno": turno,
                "frazione": frazione,
                "ev": ev,
                "soglia": soglia,
                "offerta": offerta,
            },
        )

@dataclass(slots=True)
class DecisioneEV:
    """
    Accetta se offerta > EV * (1 + tolleranza).

    La tolleranza di default è piccola ma positiva per evitare
    accettazioni spurie dovute all'arrotondamento delle offerte in
    fase finale (EV molto piccoli).
    """

    tolleranza: float = 0.001

    @property
    def nome(self) -> str:
        return "EV"

    def decidi(self, partita: Partita, offerta: int) -> Decisione:
        dist = distribuzione_pacco_giocatore(partita)
        ev = sum(v * p for v, p in dist.items())
        soglia = ev * (1.0 + self.tolleranza)
        accetta = offerta > soglia
        motivo = (
            f"offerta {offerta:,.0f} EUR > soglia {soglia:,.0f} EUR (EV)"
            if accetta
            else f"offerta {offerta:,.0f} EUR <= soglia {soglia:,.0f} EUR (EV)"
        )
        return Decisione(
            accetta=accetta,
            motivo=motivo,
            criterio=self.nome,
            confronto={"ev": ev, "soglia": soglia, "offerta": offerta},
        )


# ---------------------------------------------------------------------------
# 2. CRRA con sussistenza
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DecisioneCRRA:
    """
    Accetta se offerta >= certainty equivalent del pacco del giocatore.

    Args:
        gamma: avversione al rischio (0 = neutrale, 1 = Kelly, >1 avverso).
        sussistenza: parametro c in euro.
    """

    gamma: float = 2.0
    sussistenza: float = SUSSISTENZA_DEFAULT

    def __post_init__(self) -> None:
        if self.gamma < 0:
            raise ValueError(f"gamma deve essere >= 0, ricevuto {self.gamma}")
        if self.sussistenza < 0:
            raise ValueError(
                f"sussistenza deve essere >= 0, ricevuto {self.sussistenza}"
            )

    @property
    def nome(self) -> str:
        return f"CRRA(gamma={self.gamma}, c={self.sussistenza:.0f})"

    def decidi(self, partita: Partita, offerta: int) -> Decisione:
        dist = distribuzione_pacco_giocatore(partita)
        scala = float(max(partita.stato_pacchi.valori_chiusi()))

        ce = certezza_equivalente(dist, self.gamma, scala, self.sussistenza)
        accetta = offerta >= ce
        motivo = (
            f"offerta {offerta:,.0f} EUR >= CE {ce:,.0f} EUR"
            if accetta
            else f"offerta {offerta:,.0f} EUR < CE {ce:,.0f} EUR"
        )
        return Decisione(
            accetta=accetta,
            motivo=motivo,
            criterio=self.nome,
            confronto={
                "gamma": self.gamma,
                "sussistenza": self.sussistenza,
                "scala": scala,
                "ce": ce,
                "offerta": offerta,
            },
        )


# ---------------------------------------------------------------------------
# 3. Kelly (CRRA con gamma=1)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DecisioneKelly:
    """Caso particolare CRRA con gamma=1 (utilità logaritmica)."""

    sussistenza: float = SUSSISTENZA_DEFAULT

    @property
    def nome(self) -> str:
        return "Kelly"

    def decidi(self, partita: Partita, offerta: int) -> Decisione:
        criterio = DecisioneCRRA(gamma=1.0, sussistenza=self.sussistenza)
        d = criterio.decidi(partita, offerta)
        return Decisione(
            accetta=d.accetta,
            motivo=d.motivo,
            criterio=self.nome,
            confronto=d.confronto,
        )


# ---------------------------------------------------------------------------
# 4. Soglia fissa rispetto all'EV
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DecisioneSogliaFissa:
    """Accetta se offerta >= frazione * EV."""

    frazione: float = 0.7

    def __post_init__(self) -> None:
        if not 0.0 <= self.frazione <= 2.0:
            raise ValueError(
                f"frazione deve essere in [0, 2], ricevuto {self.frazione}"
            )

    @property
    def nome(self) -> str:
        return f"SogliaFissa({self.frazione:.0%} EV)"

    def decidi(self, partita: Partita, offerta: int) -> Decisione:
        dist = distribuzione_pacco_giocatore(partita)
        ev = sum(v * p for v, p in dist.items())
        soglia = ev * self.frazione
        accetta = offerta >= soglia
        motivo = (
            f"offerta {offerta:,.0f} EUR >= {self.frazione:.0%} EV ({soglia:,.0f})"
            if accetta
            else f"offerta {offerta:,.0f} EUR < {self.frazione:.0%} EV ({soglia:,.0f})"
        )
        return Decisione(
            accetta=accetta,
            motivo=motivo,
            criterio=self.nome,
            confronto={
                "ev": ev,
                "frazione": self.frazione,
                "soglia": soglia,
                "offerta": offerta,
            },
        )

# ---------------------------------------------------------------------------
# 5. Decisione probabilistica
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DecisioneProbabilistica:
    """
    Accetta se P(pacco >= offerta) < soglia.

    Invece di confrontare medie o utilità, guarda direttamente la
    probabilità che il pacco del giocatore contenga un valore almeno
    pari all'offerta. Se questa probabilità è bassa, rifiutare non
    conviene: accetti.

    Interpretazione: "accetto se ho meno del X% di probabilità di
    fare meglio rifiutando".

    Valori tipici:
        soglia = 0.20 → aggressivo (rifiuta finché ha senso)
        soglia = 0.30 → bilanciato
        soglia = 0.50 → prudente (accetta solo se è quasi testa o croce)
        soglia = 0.60 → molto prudente

    È particolarmente adatta a simulare concorrenti umani perché
    produce comportamenti realistici: rifiuta all'inizio (varianza
    alta), accetta alla fine (varianza bassa).
    """

    soglia: float = 0.30

    def __post_init__(self) -> None:
        if not 0.0 <= self.soglia <= 1.0:
            raise ValueError(
                f"soglia deve essere in [0, 1], ricevuto {self.soglia}"
            )

    @property
    def nome(self) -> str:
        return f"Prob(soglia={self.soglia:.0%})"

    def decidi(self, partita: Partita, offerta: int) -> Decisione:
        dist = distribuzione_pacco_giocatore(partita)
        p_battere = sum(p for v, p in dist.items() if v >= offerta)
        accetta = p_battere < self.soglia
        motivo = (
            f"P(pacco >= {offerta:,}) = {p_battere:.1%} < {self.soglia:.0%} → accetta"
            if accetta
            else f"P(pacco >= {offerta:,}) = {p_battere:.1%} >= {self.soglia:.0%} → rifiuta"
        )
        return Decisione(
            accetta=accetta,
            motivo=motivo,
            criterio=self.nome,
            confronto={
                "offerta": offerta,
                "p_battere": p_battere,
                "soglia": self.soglia,
            },
        )


# ---------------------------------------------------------------------------
# 6. CRRA adattiva (gamma in funzione del turno)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DecisioneCRRAAdattiva:
    """
    CRRA con gamma che cresce col numero di pacchi aperti.

    Simula il comportamento umano: i concorrenti diventano più
    prudenti man mano che la partita avanza e il pacco "si materializza".

    Args:
        gamma_iniziale: gamma all'inizio della partita (turno 0).
        gamma_finale: gamma alla fine della partita (turno 6).
        n_turni: numero di turni attesi (default 7).
        sussistenza: parametro c in euro.
    """

    gamma_iniziale: float = 0.5
    gamma_finale: float = 4.0
    n_turni: int = 7
    sussistenza: float = SUSSISTENZA_DEFAULT

    def __post_init__(self) -> None:
        if self.gamma_iniziale < 0 or self.gamma_finale < 0:
            raise ValueError("gamma deve essere >= 0")
        if self.n_turni <= 0:
            raise ValueError("n_turni deve essere > 0")

    @property
    def nome(self) -> str:
        return f"CRRAAdattiva({self.gamma_iniziale}->{self.gamma_finale})"

    def _gamma_corrente(self, turno: int) -> float:
        # interpolazione lineare
        t = min(max(turno / max(1, self.n_turni - 1), 0.0), 1.0)
        return self.gamma_iniziale + t * (self.gamma_finale - self.gamma_iniziale)

    def decidi(self, partita: Partita, offerta: int) -> Decisione:
        # stima il turno corrente dal numero di pacchi chiusi
        n_chiusi = partita.n_pacchi_chiusi
        turno_stimato = max(0, 20 - n_chiusi - 1)
        gamma = self._gamma_corrente(turno_stimato)

        dist = distribuzione_pacco_giocatore(partita)
        scala = float(max(partita.stato_pacchi.valori_chiusi()))
        ce = certezza_equivalente(dist, gamma, scala, self.sussistenza)
        accetta = offerta >= ce
        motivo = (
            f"[turno≈{turno_stimato}, gamma={gamma:.2f}] "
            f"offerta {offerta:,.0f} EUR >= CE {ce:,.0f} EUR"
            if accetta
            else f"[turno≈{turno_stimato}, gamma={gamma:.2f}] "
            f"offerta {offerta:,.0f} EUR < CE {ce:,.0f} EUR"
        )
        return Decisione(
            accetta=accetta,
            motivo=motivo,
            criterio=self.nome,
            confronto={
                "turno": turno_stimato,
                "gamma": gamma,
                "scala": scala,
                "ce": ce,
                "offerta": offerta,
            },
        )

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

CRITERI_DISPONIBILI: dict[str, type] = {
    "ev": DecisioneEV,
    "crra": DecisioneCRRA,
    "kelly": DecisioneKelly,
    "soglia": DecisioneSogliaFissa,
    "prob": DecisioneProbabilistica,
    "crra_adattiva": DecisioneCRRAAdattiva,
    "soglia_adattiva": DecisioneSogliaAdattiva,
}


def criterio_da_nome(nome: str, **kwargs) -> CriterioDecisione:
    """Istanzia un criterio dal nome."""
    if nome not in CRITERI_DISPONIBILI:
        raise KeyError(
            f"Criterio '{nome}' non trovato. "
            f"Disponibili: {list(CRITERI_DISPONIBILI)}"
        )
    return CRITERI_DISPONIBILI[nome](**kwargs)


__all__ = [
    "SUSSISTENZA_DEFAULT",
    "Decisione",
    "CriterioDecisione",
    "DecisioneEV",
    "DecisioneCRRA",
    "DecisioneKelly",
    "DecisioneSogliaFissa",
    "utilita_crra",
    "inversa_utilita_crra",
    "certezza_equivalente",
    "CRITERI_DISPONIBILI",
    "criterio_da_nome",
    "DecisioneProbabilistica",
    "DecisioneCRRAAdattiva",
    "DecisioneSogliaAdattiva",
]