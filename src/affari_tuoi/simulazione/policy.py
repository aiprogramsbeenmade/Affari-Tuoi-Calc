"""
Policy di gioco: una strategia completa per un giocatore automatico.

Una Policy incapsula:
- come scegliere il pacco iniziale
- quali pacchi aprire ad ogni turno
- come decidere su un'offerta in denaro (CriterioDecisione)
- come decidere sul cambio finale (PoliticaCambio + analisi bayesiana)

La Policy è usata dal simulatore Monte Carlo per giocare partite
complete dall'inizio alla fine.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable

from affari_tuoi.core.cambio import (
    PoliticaCambio,
    analizza_cambio,
    politica_neutrale,
)
from affari_tuoi.core.decisione import CriterioDecisione, DecisioneEV
from affari_tuoi.core.partita import FasePartita, Partita


# ---------------------------------------------------------------------------
# Sequenza dei pacchi da aprire per turno
# ---------------------------------------------------------------------------

#: Numero di pacchi aperti in ciascun turno di una partita standard.
#: La somma è 18: 20 pacchi iniziali - 1 pacco del giocatore - 1 pacco finale = 18.
SEQUENZA_TURNI: tuple[int, ...] = (6, 4, 3, 2, 1, 1, 1)


# ---------------------------------------------------------------------------
# Eccezioni
# ---------------------------------------------------------------------------

class ErrorePolicy(Exception):
    """Errore nella configurazione o nell'uso di una Policy."""


# ---------------------------------------------------------------------------
# Decisione sulla scelta del pacco iniziale e dei pacchi da aprire
# ---------------------------------------------------------------------------

#: Funzione che, dato lo stato della partita, restituisce l'id del prossimo
#: pacco da aprire tra quelli disponibili.
ScegliPaccoFn = Callable[[Partita, random.Random], int]

#: Funzione che, data la partita, restituisce l'id del pacco iniziale.
ScegliPaccoInizialeFn = Callable[[Partita, random.Random], int]


def scegli_pacco_iniziale_casuale(partita: Partita, rng: random.Random) -> int:
    """Sceglie un pacco iniziale a caso tra tutti quelli disponibili."""
    return rng.choice(partita.stato_pacchi.ids_totali)


def scegli_pacco_iniziale_fisso(id_pacco: int) -> ScegliPaccoInizialeFn:
    """Restituisce una funzione che sceglie sempre lo stesso pacco iniziale."""
    def _scegli(partita: Partita, rng: random.Random) -> int:
        return id_pacco
    return _scegli


def apri_pacco_casuale(partita: Partita, rng: random.Random) -> int:
    """Sceglie un pacco da aprire a caso tra quelli disponibili."""
    disponibili = partita.pacchi_chiusi_escluso_giocatore
    if not disponibili:
        raise ErrorePolicy("nessun pacco disponibile da aprire")
    return rng.choice(disponibili)


def apri_pacco_estremo(sinistra: bool = True) -> ScegliPaccoFn:
    """
    Apre sempre il pacco più a sinistra (o più a destra) disponibile.

    Utile per policy "umane" prevedibili.
    """
    def _apri(partita: Partita, rng: random.Random) -> int:
        disponibili = partita.pacchi_chiusi_escluso_giocatore
        if not disponibili:
            raise ErrorePolicy("nessun pacco disponibile da aprire")
        return disponibili[0] if sinistra else disponibili[-1]
    return _apri


def apri_pacco_di_valore_minimo(partita: Partita, rng: random.Random) -> int:
    """
    Apre il pacco con il valore più basso tra quelli disponibili.

    Policy "cheating" (il giocatore non conosce i valori), utile solo
    per studi teorici sul limite superiore del payout.
    """
    disponibili = partita.pacchi_chiusi_escluso_giocatore
    if not disponibili:
        raise ErrorePolicy("nessun pacco disponibile da aprire")
    return min(disponibili, key=lambda i: partita.stato_pacchi.valore_di(i))


def apri_pacco_di_valore_massimo(partita: Partita, rng: random.Random) -> int:
    """
    Apre il pacco con il valore più alto tra quelli disponibili.

    Policy "sfortunata": utile come worst case.
    """
    disponibili = partita.pacchi_chiusi_escluso_giocatore
    if not disponibili:
        raise ErrorePolicy("nessun pacco disponibile da aprire")
    return max(disponibili, key=lambda i: partita.stato_pacchi.valore_di(i))


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Policy:
    """
    Strategia completa di gioco.

    Attributes:
        nome: etichetta della policy (per log e report).
        criterio: criterio di decisione per le offerte in denaro.
        politica_cambio: politica del Dottore per l'analisi del cambio.
        scegli_pacco_iniziale: funzione per la scelta iniziale del pacco.
        apri_pacco: funzione per scegliere quale pacco aprire ad ogni turno.
        decidi_cambio: se True, all'ultimo turno valuta anche il cambio.
        tolleranza_cambio: margine (in euro) sotto cui il cambio è indifferente.
    """

    nome: str
    criterio: CriterioDecisione = field(default_factory=DecisioneEV)
    politica_cambio: PoliticaCambio = field(default_factory=politica_neutrale)
    scegli_pacco_iniziale: ScegliPaccoInizialeFn = scegli_pacco_iniziale_casuale
    apri_pacco: ScegliPaccoFn = apri_pacco_casuale
    decidi_cambio: bool = True
    tolleranza_cambio: float = 0.0

    def __post_init__(self) -> None:
        if not self.nome:
            raise ErrorePolicy("Policy.nome non può essere vuoto")
        if self.tolleranza_cambio < 0:
            raise ErrorePolicy(
                f"tolleranza_cambio deve essere >= 0, ricevuto {self.tolleranza_cambio}"
            )


# ---------------------------------------------------------------------------
# Risultato di una partita
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class RisultatoPartita:
    """Risultato completo di una singola partita simulata."""

    policy: str
    premio: int
    via_di_uscita: str
    """Una tra: 'offerta', 'cambio', 'pacco_finale'."""
    offerte_ricevute: tuple[int, ...]
    valori_aperti: tuple[int, ...]
    """Valori rivelati dai pacchi aperti durante la partita."""
    turno_uscita: int
    """Turno in cui la partita è terminata (0-based)."""

    @property
    def ha_accettato_offerta(self) -> bool:
        return self.via_di_uscita == "offerta"

    @property
    def ha_fatto_cambio(self) -> bool:
        return self.via_di_uscita == "cambio"


# ---------------------------------------------------------------------------
# Simulazione di una partita
# ---------------------------------------------------------------------------

def gioca_partita(
    policy: Policy,
    rng: random.Random,
    modello_offerta,
) -> RisultatoPartita:
    """
    Gioca una partita completa applicando la policy.

    Args:
        policy: strategia del giocatore.
        rng: generatore casuale (per scelte interne e modelli con rumore).
        modello_offerta: oggetto con metodo `calcola(partita) -> int`
            che produce l'offerta del Dottore.

    Returns:
        RisultatoPartita con premio finale, via di uscita, statistiche.
    """
    partita = Partita.nuova(rng=rng)

    # --- Scelta del pacco iniziale ---
    id_iniziale = policy.scegli_pacco_iniziale(partita, rng)
    partita.scegli_pacco_iniziale(id_iniziale)

    offerte_ricevute: list[int] = []
    valori_aperti: list[int] = []

    # --- Ciclo dei turni ---
    for turno, n_da_aprire in enumerate(SEQUENZA_TURNI):
        # Apri n_da_aprire pacchi
        for _ in range(n_da_aprire):
            disponibili = partita.pacchi_chiusi_escluso_giocatore
            if len(disponibili) <= 1:
                break
            id_pacco = policy.apri_pacco(partita, rng)
            valore = partita.apri_pacco(id_pacco)
            valori_aperti.append(valore)

        # Offerta del Dottore
        partita.concludi_turno()
        offerta = modello_offerta.calcola(partita)
        offerte_ricevute.append(offerta)

        # Decisione
        decisione = policy.criterio.decidi(partita, offerta)
        if decisione.accetta:
            partita.accetta_offerta(offerta)
            return RisultatoPartita(
                policy=policy.nome,
                premio=offerta,
                via_di_uscita="offerta",
                offerte_ricevute=tuple(offerte_ricevute),
                valori_aperti=tuple(valori_aperti),
                turno_uscita=turno,
            )

        # Se non accetta, torna in fase apertura
        partita.rifiuta_offerta()

        # Se restano solo 2 pacchi (giocatore + 1), esci dal ciclo
        if partita.n_pacchi_chiusi <= 2:
            break

    # --- Fase finale: 2 pacchi ---
    # (siamo in fase APERTURA, con 2 pacchi chiusi)

    # Se la policy valuta il cambio, analizziamo
    if policy.decidi_cambio and partita.n_pacchi_chiusi == 2:
        analisi = analizza_cambio(partita, policy.politica_cambio)

        if analisi.consiglio.name == "ACCETTA_CAMBIO":
            # Scambia: il "nuovo pacco" del giocatore è l'altro
            # Troviamo l'id dell'altro pacco
            id_giocatore = partita.stato_pacchi.pacco_giocatore_id
            id_altro = next(
                i for i in partita.stato_pacchi.ids_chiusi
                if i != id_giocatore
            )
            valore = partita.stato_pacchi.valore_di(id_altro)
            return RisultatoPartita(
                policy=policy.nome,
                premio=valore,
                via_di_uscita="cambio",
                offerte_ricevute=tuple(offerte_ricevute),
                valori_aperti=tuple(valori_aperti),
                turno_uscita=len(SEQUENZA_TURNI),
            )
        # Altrimenti tieni il pacco (fallthrough)

    # --- Apri il pacco finale (il tuo) ---
    premio = partita.apri_pacco_finale()
    return RisultatoPartita(
        policy=policy.nome,
        premio=premio,
        via_di_uscita="pacco_finale",
        offerte_ricevute=tuple(offerte_ricevute),
        valori_aperti=tuple(valori_aperti),
        turno_uscita=len(SEQUENZA_TURNI),
    )


__all__ = [
    "SEQUENZA_TURNI",
    "ErrorePolicy",
    "ScegliPaccoFn",
    "ScegliPaccoInizialeFn",
    "scegli_pacco_iniziale_casuale",
    "scegli_pacco_iniziale_fisso",
    "apri_pacco_casuale",
    "apri_pacco_estremo",
    "apri_pacco_di_valore_minimo",
    "apri_pacco_di_valore_massimo",
    "Policy",
    "RisultatoPartita",
    "gioca_partita",
]