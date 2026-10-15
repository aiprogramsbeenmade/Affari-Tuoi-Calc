"""
Configurazione globale del bot.

Legge le variabili d'ambiente dal file `.env` alla radice del progetto
e le espone come oggetto immutabile `Config`. Include validazione
all'avvio: se manca il token, il bot non parte.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Percorsi
# ---------------------------------------------------------------------------

def _trova_root_progetto() -> Path:
    """Risale l'albero per trovare la root (dove c'è `data/`)."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "data").is_dir():
            return parent
    raise FileNotFoundError(
        f"Impossibile trovare la root del progetto risalendo da {current}"
    )


ROOT_PROGETTO: Path = _trova_root_progetto()
"""Percorso assoluto della root del progetto."""


# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Config:
    """Configurazione immutabile del bot."""

    telegram_bot_token: str
    admin_user_id: int | None
    db_path: Path
    log_level: str

    @property
    def is_admin_configured(self) -> bool:
        return self.admin_user_id is not None

    def is_admin(self, user_id: int) -> bool:
        """True se l'utente è l'admin configurato."""
        if self.admin_user_id is None:
            return True  # se non configurato, tutti sono admin (uso personale)
        return user_id == self.admin_user_id


@lru_cache(maxsize=1)
def carica_config() -> Config:
    """
    Carica la configurazione dal file `.env` alla root del progetto.

    Variabili richieste:
        TELEGRAM_BOT_TOKEN: token fornito da @BotFather.

    Variabili opzionali:
        ADMIN_USER_ID: user id Telegram dell'admin (per /reset_db).
            Se assente, il bot considera tutti admin (uso personale).
        DB_PATH: percorso del DB SQLite (default: data/partite.db).
        LOG_LEVEL: livello di logging (default: INFO).
    """
    env_file = ROOT_PROGETTO / ".env"
    if env_file.is_file():
        load_dotenv(env_file)

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN non impostato. "
            f"Crealo su @BotFather e mettilo in {env_file}."
        )

    admin_raw = os.getenv("ADMIN_USER_ID", "").strip()
    admin_id: int | None = None
    if admin_raw:
        try:
            admin_id = int(admin_raw)
        except ValueError as exc:
            raise RuntimeError(
                f"ADMIN_USER_ID non è un intero valido: {admin_raw!r}"
            ) from exc

    db_path_raw = os.getenv("DB_PATH", "data/partite.db").strip()
    db_path = ROOT_PROGETTO / db_path_raw
    db_path.parent.mkdir(parents=True, exist_ok=True)

    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()

    return Config(
        telegram_bot_token=token,
        admin_user_id=admin_id,
        db_path=db_path,
        log_level=log_level,
    )


__all__ = ["Config", "carica_config", "ROOT_PROGETTO"]