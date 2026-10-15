"""
Storage SQLite per le partite.

Schema:
- `partite`: una riga per partita (anche interrotta).
- `eventi`: una riga per evento rilevante (pacco aperto, offerta, decisione).

Uso tipico:
    db = Database(config.db_path)
    db.inizializza()
    pid = db.crea_partita(user_id=123)
    db.salva_stato(pid, stato_json, ...)
    db.aggiungi_evento(pid, "pacco_aperto", {"valore": 5000})
    db.chiudi_partita(pid, premio=35000, via_uscita="offerta")
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from affari_tuoi.utils.logger import get_logger

_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS partite (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    data_inizio   TEXT NOT NULL,
    data_fine     TEXT,
    premio_finale INTEGER,
    via_uscita    TEXT,
    pacco_reale   INTEGER,
    stato_json    TEXT NOT NULL,
    note          TEXT
);

CREATE INDEX IF NOT EXISTS idx_partite_user ON partite(user_id);
CREATE INDEX IF NOT EXISTS idx_partite_data ON partite(data_inizio);

CREATE TABLE IF NOT EXISTS eventi (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    partita_id  INTEGER NOT NULL,
    timestamp   TEXT NOT NULL,
    tipo        TEXT NOT NULL,
    dati_json   TEXT NOT NULL,
    FOREIGN KEY (partita_id) REFERENCES partite(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_eventi_partita ON eventi(partita_id);
"""


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PartitaDB:
    """Riga della tabella `partite`."""

    id: int
    user_id: int
    data_inizio: str
    data_fine: str | None
    premio_finale: int | None
    via_uscita: str | None
    pacco_reale: int | None
    stato_json: str
    note: str | None

    @property
    def e_conclusa(self) -> bool:
        return self.data_fine is not None

    @property
    def stato(self) -> dict[str, Any]:
        return json.loads(self.stato_json)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

class Database:
    """Wrapper SQLite con utility per partite ed eventi."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: sqlite3.Connection | None = None

    # -- connessione ---------------------------------------------------------

    def connetti(self) -> sqlite3.Connection:
        """Apre (o restituisce) la connessione SQLite."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                self.path,
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
            _log.info("DB connesso: %s", self.path)
        return self._conn

    def chiudi(self) -> None:
        """Chiude la connessione se aperta."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            _log.info("DB chiuso")

    @contextmanager
    def transazione(self) -> Iterator[sqlite3.Connection]:
        """Context manager per una transazione."""
        conn = self.connetti()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def inizializza(self) -> None:
        """Crea le tabelle se non esistono."""
        with self.transazione() as conn:
            conn.executescript(SCHEMA_SQL)
        _log.info("Schema DB inizializzato")

    # -- partite -------------------------------------------------------------

    def crea_partita(
        self,
        user_id: int,
        stato_json: str,
        note: str | None = None,
    ) -> int:
        """
        Crea una nuova partita.

        Returns:
            L'id della partita creata.
        """
        data = _now_iso()
        with self.transazione() as conn:
            cur = conn.execute(
                """
                INSERT INTO partite
                    (user_id, data_inizio, stato_json, note)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, data, stato_json, note),
            )
            pid = cur.lastrowid
        _log.info("Partita creata id=%s user=%s", pid, user_id)
        return pid

    def aggiorna_stato(self, partita_id: int, stato_json: str) -> None:
        """Aggiorna lo stato serializzato di una partita."""
        with self.transazione() as conn:
            conn.execute(
                "UPDATE partite SET stato_json = ? WHERE id = ?",
                (stato_json, partita_id),
            )

    def chiudi_partita(
        self,
        partita_id: int,
        premio: int,
        via_uscita: str,
        pacco_reale: int | None = None,
        stato_json: str | None = None,
    ) -> None:
        """Marca la partita come conclusa."""
        data = _now_iso()
        with self.transazione() as conn:
            if stato_json is not None:
                conn.execute(
                    """
                    UPDATE partite
                    SET data_fine = ?, premio_finale = ?, via_uscita = ?,
                        pacco_reale = ?, stato_json = ?
                    WHERE id = ?
                    """,
                    (data, premio, via_uscita, pacco_reale, stato_json, partita_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE partite
                    SET data_fine = ?, premio_finale = ?, via_uscita = ?,
                        pacco_reale = ?
                    WHERE id = ?
                    """,
                    (data, premio, via_uscita, pacco_reale, partita_id),
                )
        _log.info(
            "Partita chiusa id=%s premio=%s via=%s",
            partita_id, premio, via_uscita,
        )

    def partita(self, partita_id: int) -> PartitaDB | None:
        """Restituisce una partita per id."""
        conn = self.connetti()
        cur = conn.execute(
            "SELECT * FROM partite WHERE id = ?", (partita_id,)
        )
        row = cur.fetchone()
        return _row_a_partita(row) if row else None

    def partite_utente(
        self,
        user_id: int,
        *,
        solo_concluse: bool = False,
        limite: int = 20,
    ) -> list[PartitaDB]:
        """Restituisce le ultime partite di un utente."""
        conn = self.connetti()
        sql = "SELECT * FROM partite WHERE user_id = ?"
        params: list[Any] = [user_id]
        if solo_concluse:
            sql += " AND data_fine IS NOT NULL"
        sql += " ORDER BY data_inizio DESC LIMIT ?"
        params.append(limite)
        cur = conn.execute(sql, params)
        return [_row_a_partita(r) for r in cur.fetchall()]

    def partita_in_corso(self, user_id: int) -> PartitaDB | None:
        """Restituisce la partita non conclusa più recente di un utente."""
        conn = self.connetti()
        cur = conn.execute(
            """
            SELECT * FROM partite
            WHERE user_id = ? AND data_fine IS NULL
            ORDER BY data_inizio DESC LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()
        return _row_a_partita(row) if row else None

    # -- eventi --------------------------------------------------------------

    def aggiungi_evento(
        self,
        partita_id: int,
        tipo: str,
        dati: dict[str, Any],
    ) -> int:
        """Aggiunge un evento alla partita."""
        with self.transazione() as conn:
            cur = conn.execute(
                """
                INSERT INTO eventi (partita_id, timestamp, tipo, dati_json)
                VALUES (?, ?, ?, ?)
                """,
                (partita_id, _now_iso(), tipo, json.dumps(dati, ensure_ascii=False)),
            )
            return cur.lastrowid

    def eventi_partita(self, partita_id: int) -> list[dict[str, Any]]:
        """Restituisce tutti gli eventi di una partita."""
        conn = self.connetti()
        cur = conn.execute(
            "SELECT * FROM eventi WHERE partita_id = ? ORDER BY id",
            (partita_id,),
        )
        return [
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "tipo": r["tipo"],
                "dati": json.loads(r["dati_json"]),
            }
            for r in cur.fetchall()
        ]

    # -- manutenzione --------------------------------------------------------

    def reset(self) -> None:
        """
        Svuota completamente il DB (partite ed eventi).

        Operazione irreversibile.
        """
        with self.transazione() as conn:
            conn.execute("DELETE FROM eventi")
            conn.execute("DELETE FROM partite")
            # Reset degli autoincrement
            conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN ('partite', 'eventi')"
            )
        _log.warning("DB resettato: tutte le partite e gli eventi eliminati")

    def statistiche_globali(self, user_id: int | None = None) -> dict[str, Any]:
        """Statistiche aggregate sulle partite concluse."""
        conn = self.connetti()
        sql = """
            SELECT
                COUNT(*) AS n,
                AVG(premio_finale) AS media,
                MIN(premio_finale) AS minimo,
                MAX(premio_finale) AS massimo,
                SUM(CASE WHEN via_uscita = 'offerta' THEN 1 ELSE 0 END) AS n_offerte,
                SUM(CASE WHEN via_uscita = 'cambio' THEN 1 ELSE 0 END) AS n_cambi,
                SUM(CASE WHEN via_uscita = 'pacco_finale' THEN 1 ELSE 0 END) AS n_pacchi
            FROM partite
            WHERE data_fine IS NOT NULL
        """
        params: list[Any] = []
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(user_id)
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        return {
            "n": row["n"] or 0,
            "media": row["media"] or 0.0,
            "minimo": row["minimo"] or 0,
            "massimo": row["massimo"] or 0,
            "n_offerte": row["n_offerte"] or 0,
            "n_cambi": row["n_cambi"] or 0,
            "n_pacchi": row["n_pacchi"] or 0,
        }


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Timestamp ISO 8601 UTC."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_a_partita(row: sqlite3.Row) -> PartitaDB:
    """Converte una row SQLite in una PartitaDB."""
    return PartitaDB(
        id=row["id"],
        user_id=row["user_id"],
        data_inizio=row["data_inizio"],
        data_fine=row["data_fine"],
        premio_finale=row["premio_finale"],
        via_uscita=row["via_uscita"],
        pacco_reale=row["pacco_reale"],
        stato_json=row["stato_json"],
        note=row["note"],
    )


__all__ = ["Database", "PartitaDB", "SCHEMA_SQL"]