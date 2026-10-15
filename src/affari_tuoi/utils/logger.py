"""
Logging centralizzato per il bot e i moduli interni.

Configura il logger root con un formato leggibile. Da chiamare una
volta sola all'avvio del bot.
"""

from __future__ import annotations

import logging
import sys
from typing import Final

_FORMATO: Final[str] = (
    "%(asctime)s | %(levelname)-7s | %(name)-25s | %(message)s"
)
_FORMATO_DATA: Final[str] = "%Y-%m-%d %H:%M:%S"


def configura_logging(level: str = "INFO") -> None:
    """
    Configura il logger root.

    Args:
        level: livello minimo ("DEBUG", "INFO", "WARNING", "ERROR").
    """
    livello = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    # Rimuovi handler esistenti (per evitare duplicazioni in caso di reload)
    for h in root.handlers[:]:
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMATO, datefmt=_FORMATO_DATA))
    root.addHandler(handler)
    root.setLevel(livello)

    # Riduci il rumore di httpx / telegram
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext").setLevel(logging.INFO)


def get_logger(nome: str) -> logging.Logger:
    """Restituisce un logger con il nome dato."""
    return logging.getLogger(nome)


__all__ = ["configura_logging", "get_logger"]