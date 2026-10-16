"""
Definizione dei premi di Affari Tuoi e caricamento da JSON.

Il tabellone 2026/27 è composto da 20 pacchi:
- 17 pacchi numerici (valori noti)
- 2 pacchi oggetto (Tommasino, Ballerina)
- 1 pacco jolly (Pacco Nero, valore sorteggiato dal notaio)

Questo modulo è volutamente privo di dipendenze esterne: solo stdlib.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------

#: Nome del file di configurazione dei premi.
PREMI_FILENAME: Final[str] = "premi.json"

#: Numero atteso di valori numerici nel tabellone 2026/27.
NUM_VALORI_NUMERICI: Final[int] = 17

#: Numero atteso di pacchi speciali (Tommasino, Ballerina, Pacco Nero).
NUM_PACCHI_SPECIALI: Final[int] = 3

#: Numero atteso di pacchi totali in una partita.
NUM_PACCHI_TOTALI: Final[int] = 20


# ---------------------------------------------------------------------------
# Percorso della root del progetto
# ---------------------------------------------------------------------------

def _trova_root_progetto() -> Path:
    """Risale l'albero per trovare la cartella `data/`."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "data").is_dir():
            return parent
    raise FileNotFoundError(
        "Impossibile trovare la cartella 'data/' risalendo da "
        f"{current}. Assicurati che la struttura del progetto sia intatta."
    )


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PaccoSpeciale:
    """
    Un pacco speciale (Tommasino, Ballerina, Pacco Nero).

    Attributes:
        id: identificatore interno ("tommasino", "ballerina", "pacco_nero").
        label: etichetta da mostrare nel bottone Telegram.
        descrizione: descrizione estesa.
        tipo: "oggetto" o "jolly".
    """

    id: str
    label: str
    descrizione: str
    tipo: str

    @property
    def e_jolly(self) -> bool:
        """True se è un pacco jolly (Pacco Nero)."""
        return self.tipo == "jolly"

    @property
    def e_oggetto(self) -> bool:
        """True se è un pacco oggetto (Tommasino, Ballerina)."""
        return self.tipo == "oggetto"


@dataclass(frozen=True, slots=True)
class ConfigurazionePremi:
    """
    Configurazione immutabile dei premi di una partita.

    Attributes:
        versione: etichetta della versione (es. "2026-27").
        valuta: codice valuta ISO 4217 (es. "EUR").
        premi: tupla dei 17 valori numerici.
        pacchi_speciali: tupla dei 3 pacchi speciali.
    """

    versione: str
    valuta: str
    premi: tuple[int, ...]
    pacchi_speciali: tuple[PaccoSpeciale, ...] = ()

    def __post_init__(self) -> None:
        if len(self.premi) != NUM_VALORI_NUMERICI:
            raise ValueError(
                f"Attesi {NUM_VALORI_NUMERICI} valori numerici, "
                f"trovati {len(self.premi)}."
            )
        if len(self.pacchi_speciali) != NUM_PACCHI_SPECIALI:
            raise ValueError(
                f"Attesi {NUM_PACCHI_SPECIALI} pacchi speciali, "
                f"trovati {len(self.pacchi_speciali)}."
            )
        if len(set(self.premi)) != len(self.premi):
            raise ValueError("I premi numerici devono essere tutti distinti.")
        if any(p < 0 for p in self.premi):
            raise ValueError("I premi non possono essere negativi.")
        ids_speciali = [s.id for s in self.pacchi_speciali]
        if len(set(ids_speciali)) != len(ids_speciali):
            raise ValueError("Gli id dei pacchi speciali devono essere distinti.")

    @property
    def premio_massimo(self) -> int:
        return max(self.premi)

    @property
    def premio_minimo(self) -> int:
        return min(self.premi)

    @property
    def numero_valori(self) -> int:
        return len(self.premi)

    @property
    def numero_pacchi(self) -> int:
        return len(self.premi) + len(self.pacchi_speciali)

    def pacco_speciale(self, id_pacco: str) -> PaccoSpeciale | None:
        """Restituisce il pacco speciale con l'id dato, o None."""
        for p in self.pacchi_speciali:
            if p.id == id_pacco:
                return p
        return None


# ---------------------------------------------------------------------------
# Caricamento
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def carica_configurazione_premi(
    filename: str = PREMI_FILENAME,
) -> ConfigurazionePremi:
    """
    Carica la configurazione dei premi dal file JSON.

    Il risultato è memorizzato in cache: chiamate successive restituiscono
    lo stesso oggetto senza rileggere il disco.

    Args:
        filename: nome del file dentro `data/`.

    Returns:
        ConfigurazionePremi con i premi caricati.

    Raises:
        FileNotFoundError: se il file non esiste.
        ValueError: se il contenuto del file non è valido.
    """
    root = _trova_root_progetto()
    path = root / "data" / filename

    if not path.is_file():
        raise FileNotFoundError(f"File dei premi non trovato: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    try:
        versione = str(raw["versione"])
        valuta = str(raw["valuta"])
        premi = tuple(int(v) for v in raw["premi"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"Formato del file premi non valido: {path}"
        ) from exc

    # Pacchi speciali (opzionali, ma se presenti devono essere validi)
    speciali_raw = raw.get("pacchi_speciali", [])
    if not isinstance(speciali_raw, list):
        raise ValueError(
            f"'pacchi_speciali' deve essere una lista, "
            f"trovato {type(speciali_raw).__name__}"
        )

    speciali: list[PaccoSpeciale] = []
    for s in speciali_raw:
        if not isinstance(s, dict):
            raise ValueError(f"Pacco speciale malformato: {s!r}")
        try:
            speciali.append(PaccoSpeciale(
                id=str(s["id"]),
                label=str(s["label"]),
                descrizione=str(s.get("descrizione", "")),
                tipo=str(s.get("tipo", "oggetto")),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Pacco speciale malformato: {s!r}"
            ) from exc

    return ConfigurazionePremi(
        versione=versione,
        valuta=valuta,
        premi=premi,
        pacchi_speciali=tuple(speciali),
    )


# ---------------------------------------------------------------------------
# Utility di comodo
# ---------------------------------------------------------------------------

def premi_ordinati_decrescenti() -> tuple[int, ...]:
    """Restituisce i premi ordinati dal più alto al più basso."""
    return tuple(sorted(carica_configurazione_premi().premi, reverse=True))


def premi_ordinati_crescenti() -> tuple[int, ...]:
    """Restituisce i premi ordinati dal più basso al più alto."""
    return tuple(sorted(carica_configurazione_premi().premi))


def pacchi_speciali() -> tuple[PaccoSpeciale, ...]:
    """Restituisce i pacchi speciali configurati."""
    return carica_configurazione_premi().pacchi_speciali


__all__ = [
    "PREMI_FILENAME",
    "NUM_VALORI_NUMERICI",
    "NUM_PACCHI_SPECIALI",
    "NUM_PACCHI_TOTALI",
    "PaccoSpeciale",
    "ConfigurazionePremi",
    "carica_configurazione_premi",
    "premi_ordinati_decrescenti",
    "premi_ordinati_crescenti",
    "pacchi_speciali",
]