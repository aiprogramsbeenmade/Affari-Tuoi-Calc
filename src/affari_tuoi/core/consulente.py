"""
Consulente per partite in tempo reale.

L'utente segue la trasmissione e segnala al bot quali pacchi escono.
Il consulente lavora su uno stato parziale (valori rimasti, offerta
corrente) e restituisce un'analisi sintetica: EV, probabilità,
soglie, decisioni per i criteri selezionati.

Internamente costruisce una `Partita` virtuale a partire dai valori
rimasti, così può riutilizzare tutta la logica di `statistiche.py`,
`decisione.py` e `cambio.py`.
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


# ---------------------------------------------------------------------------
# Stato del consulente
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class StatoConsulente:
    """
    Stato parziale di una partita seguita in TV.

    Attributes:
        valori_rimasti: valori dei pacchi ancora chiusi (incluso quello
            del giocatore, anche se non sappiamo quale sia).
        valori_aperti: valori già usciti, in ordine di apertura.
        offerta_corrente: ultima offerta del Dottore, o None.
        politica_cambio: politica del Dottore per l'analisi del cambio.
    """

    valori_rimasti: tuple[int, ...]
    valori_aperti: tuple[int, ...] = ()
    offerta_corrente: int | None = None
    politica_cambio: PoliticaCambio = field(default_factory=politica_neutrale)

    def __post_init__(self) -> None:
        if len(self.valori_rimasti) < 1:
            raise ValueError("servono almeno 1 valore rimasto")
        # Ordine decrescente per comodità
        self.valori_rimasti = tuple(sorted(self.valori_rimasti, reverse=True))

    @classmethod
    def iniziale(cls) -> "StatoConsulente":
        """Stato iniziale con tutti i 20 premi."""
        config = carica_configurazione_premi()
        return cls(
            valori_rimasti=tuple(sorted(config.premi, reverse=True)),
            valori_aperti=(),
        )

    # -- mutazioni -----------------------------------------------------------

    def apri_pacco(self, valore: int) -> None:
        """Rimuove un valore dai rimasti e lo aggiunge agli aperti."""
        if valore not in self.valori_rimasti:
            raise ValueError(
                f"valore {valore} non è tra i pacchi rimasti"
            )
        lista = list(self.valori_rimasti)
        lista.remove(valore)
        self.valori_rimasti = tuple(lista)
        self.valori_aperti = self.valori_aperti + (valore,)

    def annulla_ultimo(self) -> int | None:
        """Annulla l'ultima apertura. Restituisce il valore ripristinato."""
        if not self.valori_aperti:
            return None
        ultimo = self.valori_aperti[-1]
        self.valori_aperti = self.valori_aperti[:-1]
        self.valori_rimasti = tuple(
            sorted(self.valori_rimasti + (ultimo,), reverse=True)
        )
        return ultimo

    def reset(self) -> None:
        """Riporta lo stato a inizio partita."""
        config = carica_configurazione_premi()
        self.valori_rimasti = tuple(sorted(config.premi, reverse=True))
        self.valori_aperti = ()
        self.offerta_corrente = None

    # -- query ---------------------------------------------------------------

    @property
    def n_rimasti(self) -> int:
        return len(self.valori_rimasti)

    @property
    def n_aperti(self) -> int:
        return len(self.valori_aperti)

    @property
    def in_fase_finale(self) -> bool:
        """True se restano 2 o 3 pacchi (fase cambio)."""
        return self.n_rimasti <= 3


# ---------------------------------------------------------------------------
# Partita virtuale
# ---------------------------------------------------------------------------

def costruisci_partita_virtuale(stato: StatoConsulente) -> Partita:
    """
    Costruisce una Partita 'virtuale' a partire dai valori rimasti.

    I pacchi chiusi sono i valori rimasti; i pacchi aperti sono i
    valori già usciti. Il pacco del giocatore è il primo dei chiusi
    (arbitrario, perché tutti i calcoli statistici sono simmetrici).
    """
    # Creiamo 20 pacchi: prima i rimasti, poi gli aperti
    valori_tutti = list(stato.valori_rimasti) + list(stato.valori_aperti)
    # Padding: se mancano valori (partita custom), riempiamo con 0
    config = carica_configurazione_premi()
    while len(valori_tutti) < len(config.premi):
        valori_tutti.append(0)
    valori_tutti = valori_tutti[: len(config.premi)]

    pacchi = {
        i: type("Pacco", (), {"id": i, "valore": v})()
        for i, v in enumerate(valori_tutti)
    }
    stato_pacchi = StatoPacchi(
        _pacchi=pacchi,
        _aperti=set(range(len(stato.valori_rimasti), len(valori_tutti))),
        _pacco_giocatore_id=0,  # primo dei rimasti
    )
    return Partita(stato_pacchi=stato_pacchi)


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
        soglia_equa: EV (offerta equa).
        soglia_prudente: 70% dell'EV.
        soglia_aggressiva: 130% dell'EV.
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
    """
    Criteri mostrati di default durante la partita.

    Sono scelti per coprire tre profili:
    - EV puro (aggressivo)
    - Prob 30% (bilanciato)
    - SogliaAd 30->80 (realistico, cresce con la prudenza)
    """
    return [
        CRITERI_DISPONIBILI["ev"](),
        DecisioneProbabilistica(soglia=0.30),
        DecisioneSogliaAdattiva(frazione_iniziale=0.30, frazione_finale=0.80),
    ]


def analizza_stato(
    stato: StatoConsulente,
    criteri: list[CriterioDecisione] | None = None,
) -> AnalisiConsulente:
    """
    Analizza lo stato parziale e restituisce un'analisi sintetica.

    Args:
        stato: stato della partita in TV.
        criteri: criteri di decisione da applicare. Se None, usa
            `criteri_default()`.

    Returns:
        AnalisiConsulente con tutti i numeri e le decisioni.
    """
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
# Messaggi sintetici
# ---------------------------------------------------------------------------

def commento_rapido(analisi: AnalisiConsulente) -> str:
    """
    Restituisce un commento breve (1-2 righe) da mostrare durante la partita.

    Non è formattazione Telegram: solo il testo. La formattazione (emoji,
    Markdown) vive in `bot/formatters.py`.
    """
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

    # Con offerta: cerca il criterio "Prob 30%" per un consiglio
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
    "commento_rapido",
]