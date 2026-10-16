"""
Consulente per partite in tempo reale.

L'utente segue la trasmissione e segnala al bot quali pacchi escono.
Il consulente lavora su uno stato parziale (valori rimasti, offerta
corrente) e restituisce un'analisi sintetica: EV, probabilità,
soglie, decisioni per i criteri selezionati.

Sono supportati due tipi di stato:
- `StatoConsulente`: stato "semplice" con soli valori numerici
  (usato dalle simulazioni Monte Carlo).
- `StatoEsteso`: stato con pacchi numerici + speciali + jolly
  (usato dal bot in tempo reale per l'edizione 2026/27).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from affari_tuoi.core.cambio import (
    AnalisiCambio,
    PoliticaCambio,
    analizza_cambio,
    politica_neutrale,
)
from affari_tuoi.core.decisione import (
    CRITERI_DISPONIBILI,
    CriterioDecisione,
    Decisione,
    DecisioneProbabilistica,
    DecisioneSogliaAdattiva,
)
from affari_tuoi.core.partita import Partita, StatoPacchi
from affari_tuoi.core.premi import carica_configurazione_premi
from affari_tuoi.core.statistiche import (
    calcola_soglie,
    distribuzione_pacco_giocatore,
    probabilita_pacco_giocatore_almeno,
)
from affari_tuoi.core.stato_esteso import StatoEsteso


# ---------------------------------------------------------------------------
# Stato "semplice" (per le simulazioni)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class StatoConsulente:
    """
    Stato parziale di una partita seguita in TV (solo valori numerici).

    Usato dalle simulazioni Monte Carlo e da chi vuole una versione
    semplificata senza pacchi speciali.
    """

    valori_rimasti: tuple[int, ...]
    valori_aperti: tuple[int, ...] = ()
    offerta_corrente: int | None = None
    politica_cambio: PoliticaCambio = field(default_factory=politica_neutrale)

    def __post_init__(self) -> None:
        if len(self.valori_rimasti) < 1:
            raise ValueError("servono almeno 1 valore rimasto")
        self.valori_rimasti = tuple(sorted(self.valori_rimasti, reverse=True))

    @classmethod
    def iniziale(cls) -> "StatoConsulente":
        """Stato iniziale con tutti i premi numerici."""
        config = carica_configurazione_premi()
        return cls(
            valori_rimasti=tuple(sorted(config.premi, reverse=True)),
            valori_aperti=(),
        )

    def apri_pacco(self, valore: int) -> None:
        if valore not in self.valori_rimasti:
            raise ValueError(f"valore {valore} non è tra i pacchi rimasti")
        lista = list(self.valori_rimasti)
        lista.remove(valore)
        self.valori_rimasti = tuple(lista)
        self.valori_aperti = self.valori_aperti + (valore,)

    def annulla_ultimo(self) -> int | None:
        if not self.valori_aperti:
            return None
        ultimo = self.valori_aperti[-1]
        self.valori_aperti = self.valori_aperti[:-1]
        self.valori_rimasti = tuple(
            sorted(self.valori_rimasti + (ultimo,), reverse=True)
        )
        return ultimo

    def reset(self) -> None:
        config = carica_configurazione_premi()
        self.valori_rimasti = tuple(sorted(config.premi, reverse=True))
        self.valori_aperti = ()
        self.offerta_corrente = None

    @property
    def n_rimasti(self) -> int:
        return len(self.valori_rimasti)

    @property
    def n_aperti(self) -> int:
        return len(self.valori_aperti)

    @property
    def in_fase_finale(self) -> bool:
        return self.n_rimasti <= 3


# ---------------------------------------------------------------------------
# Analisi
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AnalisiConsulente:
    """
    Analisi sintetica di uno stato parziale.

    Attributes:
        n_rimasti: numero di pacchi ancora chiusi.
        ev: valore atteso dei pacchi rimasti.
        massimo: valore più alto rimasto.
        minimo: valore più basso rimasto.
        probabilita_almeno_ev: P(pacco giocatore >= EV).
        soglia_equa, soglia_prudente, soglia_aggressiva: soglie di riferimento.
        offerta: offerta corrente del Dottore, se presente.
        probabilita_battere_offerta: P(pacco giocatore >= offerta), se offerta.
        decisioni: dict {nome_criterio: Decisione} per ogni criterio.
        analisi_cambio: analisi bayesiana, se in fase finale.
    """

    n_rimasti: int
    ev: float
    massimo: int
    minimo: int
    probabilita_almeno_ev: float
    soglia_equa: float
    soglia_prudente: float
    soglia_aggressiva: float
    offerta: int | None
    probabilita_battere_offerta: float | None
    decisioni: dict[str, Decisione] = field(default_factory=dict)
    analisi_cambio: AnalisiCambio | None = None


def criteri_default() -> list[CriterioDecisione]:
    """Criteri mostrati di default durante la partita."""
    return [
        CRITERI_DISPONIBILI["ev"](),
        DecisioneProbabilistica(soglia=0.30),
        DecisioneSogliaAdattiva(frazione_iniziale=0.30, frazione_finale=0.80),
    ]


# ---------------------------------------------------------------------------
# Partita virtuale (per compatibilità con i criteri esistenti)
# ---------------------------------------------------------------------------

def _partita_virtuale_da_stato_esteso(stato: StatoEsteso) -> Partita:
    """
    Costruisce una Partita virtuale da uno StatoEsteso.

    I pacchi jolly vengono rappresentati con il loro valore atteso corrente.
    La Partita conterrà esattamente i pacchi chiusi (numerici + jolly),
    senza padding.
    """
    valori = list(stato.valori_disponibili)
    n_jolly = sum(1 for s in stato.speciali_chiusi if _id_e_jolly(s))
    if n_jolly > 0 and valori:
        ev_jolly = int(round(stato.valore_atteso_jolly()))
        valori.extend([ev_jolly] * n_jolly)

    stato_pacchi = StatoPacchi.da_liste(
        valori_rimasti=tuple(valori),
        valori_aperti=(),
        id_pacco_giocatore=0,
    )
    return Partita(stato_pacchi=stato_pacchi)


def _id_e_jolly(id_speciale: str) -> bool:
    config = carica_configurazione_premi()
    p = config.pacco_speciale(id_speciale)
    return p is not None and p.e_jolly


def costruisci_partita_virtuale(stato: StatoConsulente) -> Partita:
    """Costruisce una Partita virtuale da uno StatoConsulente."""
    valori_tutti = list(stato.valori_rimasti) + list(stato.valori_aperti)
    config = carica_configurazione_premi()
    while len(valori_tutti) < config.numero_pacchi:
        valori_tutti.append(0)
    valori_tutti = valori_tutti[: config.numero_pacchi]

    pacchi = {
        i: type("Pacco", (), {"id": i, "valore": v})()
        for i, v in enumerate(valori_tutti)
    }
    stato_pacchi = StatoPacchi(
        _pacchi=pacchi,
        _aperti=set(range(len(stato.valori_rimasti), len(valori_tutti))),
        _pacco_giocatore_id=0,
    )
    return Partita(stato_pacchi=stato_pacchi)


# ---------------------------------------------------------------------------
# Analisi: StatoConsulente (semplice)
# ---------------------------------------------------------------------------

def analizza_stato(
    stato: StatoConsulente,
    criteri: list[CriterioDecisione] | None = None,
) -> AnalisiConsulente:
    """Analizza uno StatoConsulente (solo valori numerici)."""
    criteri = criteri or criteri_default()
    partita = costruisci_partita_virtuale(stato)
    valori = stato.valori_rimasti
    ev = sum(valori) / len(valori)
    massimo = max(valori)
    minimo = min(valori)

    dist = distribuzione_pacco_giocatore(partita)
    p_almeno_ev = sum(p for v, p in dist.items() if v >= ev)
    soglie = calcola_soglie(partita)

    p_battere: float | None = None
    decisioni: dict[str, Decisione] = {}
    if stato.offerta_corrente is not None:
        p_battere = sum(
            p for v, p in dist.items() if v >= stato.offerta_corrente
        )
        for criterio in criteri:
            decisioni[criterio.nome] = criterio.decidi(
                partita, stato.offerta_corrente
            )

    analisi_cambio = None
    if stato.in_fase_finale:
        analisi_cambio = analizza_cambio(
            partita, stato.politica_cambio, cambio_offerto=True
        )

    return AnalisiConsulente(
        n_rimasti=len(valori),
        ev=ev,
        massimo=massimo,
        minimo=minimo,
        probabilita_almeno_ev=p_almeno_ev,
        soglia_equa=soglie.soglia_equa,
        soglia_prudente=soglie.soglia_prudente,
        soglia_aggressiva=soglie.soglia_aggressiva,
        offerta=stato.offerta_corrente,
        probabilita_battere_offerta=p_battere,
        decisioni=decisioni,
        analisi_cambio=analisi_cambio,
    )


# ---------------------------------------------------------------------------
# Analisi: StatoEsteso (con jolly)
# ---------------------------------------------------------------------------

def analizza_stato_esteso(
    stato: StatoEsteso,
    criteri: list[CriterioDecisione] | None = None,
) -> AnalisiConsulente:
    """
    Analizza uno StatoEsteso (con pacchi speciali e jolly).

    Le decisioni dei criteri vengono calcolate direttamente sulla
    distribuzione reale di `StatoEsteso`, non su una partita virtuale.
    Questo garantisce coerenza tra `probabilita_battere_offerta` e le
    decisioni mostrate.
    """
    criteri = criteri or criteri_default()
    n = stato.n_pacchi_chiusi
    valori_noti = stato.valori_numerici_rimasti
    ev = stato.valore_atteso_totale()
    dist = stato.distribuzione_pacco_giocatore()

    # Soglie
    soglia_equa = ev
    soglia_prudente = 0.7 * ev
    soglia_aggressiva = 1.3 * ev

    # P(pacco >= EV)
    p_almeno_ev = sum(p for v, p in dist.items() if v >= ev) if dist else 0.0

    p_battere: float | None = None
    decisioni: dict[str, Decisione] = {}
    if stato.offerta_corrente is not None:
        offerta = stato.offerta_corrente
        p_battere = sum(p for v, p in dist.items() if v >= offerta) if dist else 0.0

        # Calcola le decisioni direttamente sulla distribuzione reale
        for criterio in criteri:
            decisioni[criterio.nome] = _applica_criterio_a_distribuzione(
                criterio, dist, ev, offerta, n
            )

    # Analisi cambio
    analisi_cambio = None
    if stato.in_fase_finale:
        partita_virtuale = _partita_virtuale_da_stato_esteso(stato)
        analisi_cambio = analizza_cambio(
            partita_virtuale, politica_neutrale(), cambio_offerto=True
        )

    return AnalisiConsulente(
        n_rimasti=n,
        ev=ev,
        massimo=max(valori_noti) if valori_noti else 0,
        minimo=min(valori_noti) if valori_noti else 0,
        probabilita_almeno_ev=p_almeno_ev,
        soglia_equa=soglia_equa,
        soglia_prudente=soglia_prudente,
        soglia_aggressiva=soglia_aggressiva,
        offerta=stato.offerta_corrente,
        probabilita_battere_offerta=p_battere,
        decisioni=decisioni,
        analisi_cambio=analisi_cambio,
    )


def _applica_criterio_a_distribuzione(
    criterio: CriterioDecisione,
    dist: dict[int, float],
    ev: float,
    offerta: int,
    n_pacchi: int,
) -> Decisione:
    """
    Applica un criterio di decisione alla distribuzione reale del pacco
    del giocatore.

    Supporta i criteri più comuni (EV, Prob, SogliaAdattiva, CRRA, Kelly,
    SogliaFissa). Per criteri sconosciuti, ricade su una partita virtuale.
    """
    from affari_tuoi.core.decisione import (
        DecisioneCRRA, DecisioneEV, DecisioneKelly,
        DecisioneProbabilistica, DecisioneSogliaAdattiva,
        DecisioneSogliaFissa, certezza_equivalente,
    )

    if isinstance(criterio, DecisioneProbabilistica):
        p_battere = sum(p for v, p in dist.items() if v >= offerta)
        accetta = p_battere < criterio.soglia
        motivo = (
            f"P(pacco >= {offerta:,}) = {p_battere:.1%} < {criterio.soglia:.0%} → accetta"
            if accetta
            else f"P(pacco >= {offerta:,}) = {p_battere:.1%} >= {criterio.soglia:.0%} → rifiuta"
        )
        return Decisione(
            accetta=accetta,
            motivo=motivo,
            criterio=criterio.nome,
            confronto={
                "offerta": offerta,
                "p_battere": p_battere,
                "soglia": criterio.soglia,
            },
        )

    if isinstance(criterio, DecisioneEV):
        soglia = ev * (1.0 + criterio.tolleranza)
        accetta = offerta > soglia
        motivo = (
            f"offerta {offerta:,.0f} EUR > soglia {soglia:,.0f} EUR (EV)"
            if accetta
            else f"offerta {offerta:,.0f} EUR <= soglia {soglia:,.0f} EUR (EV)"
        )
        return Decisione(
            accetta=accetta,
            motivo=motivo,
            criterio=criterio.nome,
            confronto={"ev": ev, "soglia": soglia, "offerta": offerta},
        )

    if isinstance(criterio, DecisioneSogliaFissa):
        soglia = ev * criterio.frazione
        accetta = offerta >= soglia
        motivo = (
            f"offerta {offerta:,.0f} EUR >= {criterio.frazione:.0%} EV ({soglia:,.0f})"
            if accetta
            else f"offerta {offerta:,.0f} EUR < {criterio.frazione:.0%} EV ({soglia:,.0f})"
        )
        return Decisione(
            accetta=accetta,
            motivo=motivo,
            criterio=criterio.nome,
            confronto={
                "ev": ev,
                "frazione": criterio.frazione,
                "soglia": soglia,
                "offerta": offerta,
            },
        )

    if isinstance(criterio, DecisioneSogliaAdattiva):
        turno = max(0, 20 - n_pacchi - 1)
        frazione = criterio._frazione_corrente(turno)
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
            criterio=criterio.nome,
            confronto={
                "turno": turno,
                "frazione": frazione,
                "ev": ev,
                "soglia": soglia,
                "offerta": offerta,
            },
        )

    if isinstance(criterio, (DecisioneCRRA, DecisioneKelly)):
        gamma = getattr(criterio, "gamma", 1.0) if isinstance(criterio, DecisioneCRRA) else 1.0
        sussistenza = getattr(criterio, "sussistenza", 5000.0)
        scala = float(max(dist.keys())) if dist else 1.0
        ce = certezza_equivalente(dist, gamma, scala, sussistenza)
        accetta = offerta >= ce
        motivo = (
            f"offerta {offerta:,.0f} EUR >= CE {ce:,.0f} EUR"
            if accetta
            else f"offerta {offerta:,.0f} EUR < CE {ce:,.0f} EUR"
        )
        return Decisione(
            accetta=accetta,
            motivo=motivo,
            criterio=criterio.nome,
            confronto={"gamma": gamma, "ce": ce, "offerta": offerta},
        )

    # Fallback: criterio non supportato, ritorna una decisione neutra
    return Decisione(
        accetta=False,
        motivo=f"criterio {criterio.nome} non supportato su StatoEsteso",
        criterio=criterio.nome,
    )


# ---------------------------------------------------------------------------
# Messaggi sintetici
# ---------------------------------------------------------------------------

def commento_rapido(analisi: AnalisiConsulente) -> str:
    """Commento breve (1-2 righe) da mostrare durante la partita."""
    if analisi.n_rimasti <= 2:
        return (
            f"Fase finale: {analisi.n_rimasti} pacchi rimasti. "
            f"EV {analisi.ev:,.0f} EUR."
        )
    if analisi.offerta is None:
        return (
            f"EV {analisi.ev:,.0f} EUR, "
            f"P(pacco >= EV) {analisi.probabilita_almeno_ev:.0%}."
        )
    for nome, dec in analisi.decisioni.items():
        if "Prob" in nome:
            if dec.accetta:
                return (
                    f"Offerta {analisi.offerta:,.0f} EUR accettabile: "
                    f"P(battere) {analisi.probabilita_battere_offerta:.0%}."
                )
            return (
                f"Offerta {analisi.offerta:,.0f} EUR rifiutabile: "
                f"P(battere) {analisi.probabilita_battere_offerta:.0%}."
            )
    return f"Offerta {analisi.offerta:,.0f} EUR. EV {analisi.ev:,.0f} EUR."


__all__ = [
    "StatoConsulente",
    "costruisci_partita_virtuale",
    "AnalisiConsulente",
    "criteri_default",
    "analizza_stato",
    "analizza_stato_esteso",
    "commento_rapido",
]