"""
Stato e logica di una partita di Affari Tuoi.

Questo modulo definisce:
- Pacco: singolo pacco con id e valore nascosto
- FasePartita: enum delle fasi del gioco
- Partita: stato completo di una partita

Non contiene logica decisionale né di offerta: quelle vivono in
moduli separati (decisione.py, offerte.py).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Iterator

from affari_tuoi.core.premi import carica_configurazione_premi


# ---------------------------------------------------------------------------
# Eccezioni specifiche del dominio
# ---------------------------------------------------------------------------

class ErrorePartita(Exception):
    """Eccezione base per errori nel flusso di una partita."""


class FaseNonValida(ErrorePartita):
    """Sollevata quando si tenta un'azione non consentita nella fase corrente."""


class PaccoNonDisponibile(ErrorePartita):
    """Sollevata quando si tenta di aprire un pacco già aperto o non valido."""


# ---------------------------------------------------------------------------
# Enum delle fasi
# ---------------------------------------------------------------------------

class FasePartita(Enum):
    """Fasi attraversate da una partita, in ordine."""

    INIZIO = auto()              # prima della scelta del pacco
    SCELTA_PACCO = auto()        # il giocatore scegle il suo pacco
    APERTURA = auto()            # il giocatore apre pacchi a turno
    OFFERTA = auto()             # il Dottore fa un'offerta
    CAMBIO = auto()              # il Dottore propone il cambio finale
    CONCLUSIONE = auto()         # partita terminata, premio rivelato


# ---------------------------------------------------------------------------
# Pacco
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Pacco:
    """
    Un singolo pacco della partita.

    Attributes:
        id: identificatore del pacco (0-based, fino a NUM_PACCHI_STANDARD-1).
        valore: valore in euro contenuto nel pacco (nascosto al giocatore).
    """

    id: int
    valore: int

    def __post_init__(self) -> None:
        if self.id < 0:
            raise ValueError(f"id pacco non valido: {self.id}")
        if self.valore < 0:
            raise ValueError(f"valore pacco non valido: {self.valore}")

    def __repr__(self) -> str:  # evita di leakare il valore nei log
        return f"Pacco(id={self.id})"


# ---------------------------------------------------------------------------
# Stato dei pacchi
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class StatoPacchi:
    """
    Tiene traccia dei pacchi chiusi, aperti e del pacco del giocatore.

    Internamente mantiene:
    - _pacchi: tutti i pacchi della partita, per id
    - _aperti: set degli id dei pacchi aperti
    - _pacco_giocatore_id: id del pacco scelto dal giocatore, o None
    """

    _pacchi: dict[int, Pacco] = field(default_factory=dict)
    _aperti: set[int] = field(default_factory=set)
    _pacco_giocatore_id: int | None = None

    # -- costruzione ---------------------------------------------------------

    @classmethod
    def da_premi(
        cls,
        premi: tuple[int, ...],
        rng: random.Random | None = None,
    ) -> "StatoPacchi":
        """
        Crea lo stato assegnando i premi ai pacchi in ordine casuale.

        Args:
            premi: valori da distribuire nei pacchi.
            rng: generatore casuale opzionale (utile per test deterministici).
        """
        rng = rng or random.Random()
        valori = list(premi)
        rng.shuffle(valori)
        pacchi = {i: Pacco(id=i, valore=v) for i, v in enumerate(valori)}
        return cls(_pacchi=pacchi)

    # -- query ---------------------------------------------------------------

    @property
    def ids_totali(self) -> tuple[int, ...]:
        return tuple(self._pacchi.keys())

    @property
    def ids_aperti(self) -> frozenset[int]:
        return frozenset(self._aperti)

    @property
    def ids_chiusi(self) -> tuple[int, ...]:
        return tuple(i for i in self._pacchi if i not in self._aperti)

    @property
    def pacco_giocatore_id(self) -> int | None:
        return self._pacco_giocatore_id

    @property
    def pacco_giocatore(self) -> Pacco | None:
        if self._pacco_giocatore_id is None:
            return None
        return self._pacchi[self._pacco_giocatore_id]

    def pacco(self, id_pacco: int) -> Pacco:
        """Restituisce il pacco con l'id dato (anche se aperto)."""
        if id_pacco not in self._pacchi:
            raise PaccoNonDisponibile(f"id pacco inesistente: {id_pacco}")
        return self._pacchi[id_pacco]

    def valore_di(self, id_pacco: int) -> int:
        """Valore del pacco indicato (attenzione: è il valore nascosto)."""
        return self.pacco(id_pacco).valore

    def valori_chiusi(self) -> tuple[int, ...]:
        """Valori ancora in gioco (esclusi i pacchi aperti)."""
        return tuple(self._pacchi[i].valore for i in self.ids_chiusi)

    def e_aperto(self, id_pacco: int) -> bool:
        return id_pacco in self._aperti

    # -- mutazioni -----------------------------------------------------------

    def assegna_pacco_giocatore(self, id_pacco: int) -> None:
        """Imposta il pacco scelto dal giocatore (deve essere chiuso)."""
        if id_pacco not in self._pacchi:
            raise PaccoNonDisponibile(f"id pacco inesistente: {id_pacco}")
        if id_pacco in self._aperti:
            raise PaccoNonDisponibile(f"pacco già aperto: {id_pacco}")
        if self._pacco_giocatore_id is not None:
            raise ErrorePartita("pacco del giocatore già assegnato")
        self._pacco_giocatore_id = id_pacco

    def apri(self, id_pacco: int) -> int:
        """
        Apre il pacco e restituisce il valore rivelato.

        Raises:
            PaccoNonDisponibile: se il pacco è già aperto, non esiste,
                o è il pacco del giocatore.
        """
        if id_pacco not in self._pacchi:
            raise PaccoNonDisponibile(f"id pacco inesistente: {id_pacco}")
        if id_pacco in self._aperti:
            raise PaccoNonDisponibile(f"pacco già aperto: {id_pacco}")
        if id_pacco == self._pacco_giocatore_id:
            raise PaccoNonDisponibile(
                "non puoi aprire il pacco del giocatore durante la partita"
            )
        self._aperti.add(id_pacco)
        return self._pacchi[id_pacco].valore


# ---------------------------------------------------------------------------
# Partita
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Partita:
    """
    Stato completo di una partita di Affari Tuoi.

    La Partita non prende decisioni: espone operazioni che il chiamante
    (simulatore o bot) applica in base alla strategia scelta.
    """

    stato_pacchi: StatoPacchi
    fase: FasePartita = FasePartita.INIZIO
    pacchi_aperti_in_turno: int = 0
    turni_completati: int = 0
    premio_finale: int | None = None

    # -- costruzione ---------------------------------------------------------

    @classmethod
    def nuova(
        cls,
        rng: random.Random | None = None,
    ) -> "Partita":
        """Crea una nuova partita con premi standard."""
        config = carica_configurazione_premi()
        stato = StatoPacchi.da_premi(config.premi, rng=rng)
        return cls(stato_pacchi=stato)

    # -- query di comodo -----------------------------------------------------

    @property
    def pacco_giocatore(self) -> Pacco | None:
        return self.stato_pacchi.pacco_giocatore

    @property
    def pacchi_chiusi(self) -> tuple[int, ...]:
        return self.stato_pacchi.ids_chiusi

    @property
    def pacchi_chiusi_escluso_giocatore(self) -> tuple[int, ...]:
        return tuple(
            i for i in self.stato_pacchi.ids_chiusi
            if i != self.stato_pacchi.pacco_giocatore_id
        )

    @property
    def n_pacchi_chiusi(self) -> int:
        return len(self.stato_pacchi.ids_chiusi)

    @property
    def n_pacchi_rimasti_da_aprire(self) -> int:
        return len(self.pacchi_chiusi_escluso_giocatore)

    @property
    def e_conclusa(self) -> bool:
        return self.fase is FasePartita.CONCLUSIONE

    # -- azioni --------------------------------------------------------------

    def scegli_pacco_iniziale(self, id_pacco: int) -> None:
        """Fase SCELTA_PACCO: il giocatore scegle il suo pacco."""
        if self.fase is not FasePartita.INIZIO:
            raise FaseNonValida(
                f"scelta pacco non consentita in fase {self.fase.name}"
            )
        self.stato_pacchi.assegna_pacco_giocatore(id_pacco)
        self.fase = FasePartita.APERTURA
        self.pacchi_aperti_in_turno = 0

    def apri_pacco(self, id_pacco: int) -> int:
        """
        Fase APERTURA: apre un pacco e restituisce il valore rivelato.

        Aggiorna il contatore dei pacchi aperti nel turno corrente.
        """
        if self.fase is not FasePartita.APERTURA:
            raise FaseNonValida(
                f"apertura pacco non consentita in fase {self.fase.name}"
            )
        valore = self.stato_pacchi.apri(id_pacco)
        self.pacchi_aperti_in_turno += 1
        return valore

    def concludi_turno(self) -> None:
        """
        Chiude il turno corrente e passa alla fase OFFERTA.

        Da chiamare quando il chiamante ritiene che siano stati aperti
        abbastanza pacchi per il turno corrente.
        """
        if self.fase is not FasePartita.APERTURA:
            raise FaseNonValida(
                f"chiusura turno non consentita in fase {self.fase.name}"
            )
        self.turni_completati += 1
        self.pacchi_aperti_in_turno = 0
        self.fase = FasePartita.OFFERTA

    def accetta_offerta(self, valore: int) -> None:
        """Il giocatore accetta l'offerta del Dottore: partita finita."""
        if self.fase is not FasePartita.OFFERTA:
            raise FaseNonValida(
                f"accettazione offerta non consentita in fase {self.fase.name}"
            )
        self.premio_finale = valore
        self.fase = FasePartita.CONCLUSIONE

    def rifiuta_offerta(self) -> None:
        """Il giocatore rifiuta l'offerta: si torna ad aprire."""
        if self.fase is not FasePartita.OFFERTA:
            raise FaseNonValida(
                f"rifiuto offerta non consentito in fase {self.fase.name}"
            )
        self.fase = FasePartita.APERTURA

    def apri_pacco_finale(self) -> int:
        """
        Apri il pacco finale del giocatore e concludi la partita.

        Da usare quando restano 2 pacchi (giocatore + 1) e si decide di
        non accettare né cambiare.
        """
        if self.fase not in (FasePartita.APERTURA, FasePartita.CAMBIO):
            raise FaseNonValida(
                f"apertura finale non consentita in fase {self.fase.name}"
            )
        pacco = self.stato_pacchi.pacco_giocatore
        if pacco is None:
            raise ErrorePartita("nessun pacco assegnato al giocatore")
        self.premio_finale = pacco.valore
        self.fase = FasePartita.CONCLUSIONE
        return pacco.valore

    # -- utility -------------------------------------------------------------

    def itera_pacchi_chiusi_escluso_giocatore(self) -> Iterator[int]:
        """Itera gli id dei pacchi ancora apribili (esclude quello del giocatore)."""
        return iter(self.pacchi_chiusi_escluso_giocatore)


__all__ = [
    "ErrorePartita",
    "FaseNonValida",
    "PaccoNonDisponibile",
    "FasePartita",
    "Pacco",
    "StatoPacchi",
    "Partita",
]