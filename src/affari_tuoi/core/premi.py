"""
Definizione dei premi di Affari Tuoi e caricamento da JSON.

Questo modulo è volutamente privo di dipendenze esterne: solo stdlib.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# Costanti di percorso
# ---------------------------------------------------------------------------

#: Nome del file di configurazione dei premi.
PREMI_FILENAME: Final[str] = "premi.json"

#: Numero atteso di pacchi in una partita standard di Affari Tuoi.
NUM_PACCHI_STANDARD: Final[int] = 20


# ---------------------------------------------------------------------------
# Percorso della root del progetto
# ---------------------------------------------------------------------------

def _trova_root_progetto() -> Path:
    """
    Risale l'albero delle directory finché trova la cartella `data/`.

    Funziona sia quando il modulo è eseguito dal sorgente (PyCharm),
    sia quando è installato come pacchetto.

    Raises:
        FileNotFoundError: se non trova la cartella `data/`.
    """
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "data").is_dir():
            return parent
    raise FileNotFoundError(
        "Impossibile trovare la cartella 'data/' risalendo da "
        f"{current}. Assicurati che la struttura del progetto sia intatta."
    )


# ---------------------------------------------------------------------------
# Dataclass di configurazione
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ConfigurazionePremi:
    """
    Configurazione immutabile dei premi di una partita.

    Attributes:
        versione: etichetta della versione del set di premi (es. "classica").
        valuta: codice valuta ISO 4217 (es. "EUR").
        premi: tupla ordinata dei valori dei premi.
    """

    versione: str
    valuta: str
    premi: tuple[int, ...]

    def __post_init__(self) -> None:
        if len(self.premi) != NUM_PACCHI_STANDARD:
            raise ValueError(
                f"Attesi {NUM_PACCHI_STANDARD} premi, "
                f"trovati {len(self.premi)}."
            )
        if len(set(self.premi)) != len(self.premi):
            raise ValueError("I premi devono essere tutti distinti.")
        if any(p < 0 for p in self.premi):
            raise ValueError("I premi non possono essere negativi.")

    @property
    def premio_massimo(self) -> int:
        return max(self.premi)

    @property
    def premio_minimo(self) -> int:
        return min(self.premi)

    @property
    def numero_pacchi(self) -> int:
        return len(self.premi)


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

    return ConfigurazionePremi(
        versione=versione,
        valuta=valuta,
        premi=premi,
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


__all__ = [
    "PREMI_FILENAME",
    "NUM_PACCHI_STANDARD",
    "ConfigurazionePremi",
    "carica_configurazione_premi",
    "premi_ordinati_decrescenti",
    "premi_ordinati_crescenti",
]