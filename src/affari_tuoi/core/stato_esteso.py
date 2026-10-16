"""
Stato di una partita con supporto per pacchi jolly (Pacco Nero).

In questa edizione di Affari Tuoi (2026/27) il tabellone ha:
- 17 valori numerici noti
- 2 pacchi oggetto (Tommasino, Ballerina) senza valore monetario
- 1 pacco jolly (Pacco Nero) il cui valore è sorteggiato dal notaio
  e rimane ignoto a tutti finché non esce

Modello matematico:
- In ogni istante, i pacchi chiusi sono N numerici (valori noti) + J jolly.
- Il valore atteso di un jolly chiuso è la media dei valori numerici
  ancora non assegnati (cioè non rivelati in altri pacchi).
- L'EV del pacco del giocatore è la media dei valori attesi di tutti
  i pacchi chiusi.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from affari_tuoi.core.premi import (
    ConfigurazionePremi,
    carica_configurazione_premi,
)


# ---------------------------------------------------------------------------
# Stato
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class StatoEsteso:
    """
    Stato di una partita con pacchi numerici + speciali + jolly.

    Attributes:
        valori_disponibili: set dei valori numerici non ancora rivelati
            (né aperti come pacchi numerici, né rivelati dentro jolly).
        valori_aperti: lista dei valori numerici già rivelati, in ordine.
        speciali_chiusi: set degli id dei pacchi speciali ancora chiusi.
        speciali_aperti: lista degli id dei pacchi speciali già aperti,
            in ordine di apertura.
        valori_speciali_rivelati: {id_speciale: valore_numerico} per gli
            jolly aperti che hanno rivelato un valore numerico.
            Per Tommasino/Ballerina, il valore è None (non hanno valore).
        offerta_corrente: offerta del Dottore attualmente sul tavolo,
            o None se non c'è.
    """

    valori_disponibili: set[int] = field(default_factory=set)
    valori_aperti: list[int] = field(default_factory=list)
    speciali_chiusi: set[str] = field(default_factory=set)
    speciali_aperti: list[str] = field(default_factory=list)
    valori_speciali_rivelati: dict[str, int | None] = field(default_factory=dict)
    offerta_corrente: int | None = None

    # -- costruzione ---------------------------------------------------------

    @classmethod
    def iniziale(
        cls,
        config: ConfigurazionePremi | None = None,
    ) -> "StatoEsteso":
        """Crea uno stato iniziale con tutti i pacchi chiusi."""
        config = config or carica_configurazione_premi()
        return cls(
            valori_disponibili=set(config.premi),
            valori_aperti=[],
            speciali_chiusi={s.id for s in config.pacchi_speciali},
            speciali_aperti=[],
            valori_speciali_rivelati={},
            offerta_corrente=None,
        )

    # -- query ---------------------------------------------------------------

    @property
    def n_pacchi_chiusi(self) -> int:
        """Numero di pacchi ancora chiusi (numerici + speciali)."""
        return len(self.valori_disponibili) + len(self.speciali_chiusi)

    @property
    def n_speciali_chiusi(self) -> int:
        return len(self.speciali_chiusi)

    @property
    def n_numerici_chiusi(self) -> int:
        return len(self.valori_disponibili)

    @property
    def n_jolly_chiusi(self) -> int:
        """Numero di pacchi jolly ancora chiusi."""
        config = carica_configurazione_premi()
        return sum(
            1 for s in self.speciali_chiusi
            if (p := config.pacco_speciale(s)) is not None and p.e_jolly
        )

    @property
    def valori_numerici_rimasti(self) -> tuple[int, ...]:
        """Valori numerici ancora disponibili (ordinati decrescenti)."""
        return tuple(sorted(self.valori_disponibili, reverse=True))

    @property
    def in_fase_finale(self) -> bool:
        """True se restano 2 o 3 pacchi chiusi."""
        return self.n_pacchi_chiusi <= 3

    # -- valore atteso -------------------------------------------------------

    def valore_atteso_jolly(self) -> float:
        """
        EV di un pacco jolly chiuso.

        È la media dei valori numerici ancora disponibili. Se non ci sono
        valori disponibili, restituisce 0.
        """
        if not self.valori_disponibili:
            return 0.0
        return sum(self.valori_disponibili) / len(self.valori_disponibili)

    def valore_atteso_totale(self) -> float:
        """
        EV di un singolo pacco chiuso.

        Con N pacchi numerici chiusi (valori noti) e J pacchi jolly chiusi:
            EV = (sum(valori_numerici) + J * EV_jolly) / (N + J)

        Nota: i pacchi oggetto (Tommasino/Ballerina) chiusi non contribuiscono
        all'EV in quanto non hanno valore monetario. Ma contano nel numero
        totale di pacchi per il calcolo della probabilità.
        """
        n = self.n_pacchi_chiusi
        if n == 0:
            return 0.0
        n_jolly = self.n_jolly_chiusi
        somma_numerici = sum(self.valori_disponibili)
        ev_jolly = self.valore_atteso_jolly()
        return (somma_numerici + n_jolly * ev_jolly) / n

    # -- distribuzione -------------------------------------------------------

    def distribuzione_pacco_giocatore(self) -> dict[int, float]:
        """
        Distribuzione di probabilità sul valore del pacco del giocatore.

        Restituisce {valore: probabilità} per ogni valore numerico possibile.
        La somma delle probabilità è 1.0: la probabilità dei jolly viene
        distribuita uniformemente sui valori disponibili (approssimazione
        con il loro valore atteso).

        Se non ci sono valori disponibili, restituisce {}.
        """
        n = self.n_pacchi_chiusi
        if n == 0 or not self.valori_disponibili:
            return {}

        n_numerici = len(self.valori_disponibili)
        n_jolly = self.n_jolly_chiusi

        prob: dict[int, float] = {}

        # Ogni valore numerico ha probabilità 1/n di essere il pacco
        # del giocatore (perché ogni pacco ha la stessa probabilità).
        for v in self.valori_disponibili:
            prob[v] = 1.0 / n

        # I jolly aggiungono la loro probabilità distribuita uniformemente
        # sui valori disponibili.
        if n_jolly > 0:
            quota_per_valore = (n_jolly / n) / n_numerici
            for v in self.valori_disponibili:
                prob[v] += quota_per_valore

        return prob

    def probabilita_almeno(self, soglia: int) -> float:
        """
        P(pacco del giocatore >= soglia), considerando i jolly al loro EV.

        I jolly contribuiscono in proporzione al loro valore atteso: se
        EV_jolly >= soglia, contribuiscono con la loro probabilità piena;
        altrimenti con 0 (approssimazione conservativa).
        """
        n = self.n_pacchi_chiusi
        if n == 0:
            return 0.0
        count = sum(1 for v in self.valori_disponibili if v >= soglia)
        prob = count / n

        n_jolly = self.n_jolly_chiusi
        if n_jolly > 0 and self.valore_atteso_jolly() >= soglia:
            prob += n_jolly / n

        return min(prob, 1.0)

    # -- mutazioni -----------------------------------------------------------

    def apri_numerico(self, valore: int) -> None:
        """Apre un pacco numerico di valore noto."""
        if valore not in self.valori_disponibili:
            raise ValueError(f"Valore {valore} non disponibile")
        self.valori_disponibili.discard(valore)
        self.valori_aperti.append(valore)

    def apri_speciale(
            self,
            id_speciale: str,
            valore_rivelato: int | None = None,
            *,
            consenti_duplicati: bool = False,
    ) -> None:
        """
        Apre un pacco speciale.

        Args:
            id_speciale: id del pacco ("tommasino", "ballerina", "pacco_nero").
            valore_rivelato: se il pacco è un jolly e il valore numerico
                è stato rivelato, passarlo qui. Per Tommasino/Ballerina
                va lasciato None.
            consenti_duplicati: se True, il valore rivelato può essere anche
                un valore già uscito in un altro pacco (caso del Pacco Nero).
                In questo caso il valore NON viene rimosso da `valori_disponibili`
                (perché è già stato rimosso), ma viene solo registrato come
                "valore del pacco nero".

        Raises:
            ValueError: se il pacco non è chiuso o se il valore rivelato
                non è tra i disponibili (e `consenti_duplicati=False`).
        """
        if id_speciale not in self.speciali_chiusi:
            raise ValueError(f"Pacco speciale già aperto: {id_speciale}")
        self.speciali_chiusi.discard(id_speciale)
        self.speciali_aperti.append(id_speciale)

        if valore_rivelato is not None:
            if valore_rivelato in self.valori_disponibili:
                # Valore non ancora uscito: rimuovilo dai disponibili
                self.valori_disponibili.discard(valore_rivelato)
                self.valori_aperti.append(valore_rivelato)
            elif consenti_duplicati:
                # Valore già uscito in un altro pacco: non c'è nulla da
                # rimuovere, il valore è già "consumato". Lo registriamo
                # comunque come valore del pacco speciale.
                pass
            else:
                raise ValueError(
                    f"Valore rivelato {valore_rivelato} non disponibile"
                )

        self.valori_speciali_rivelati[id_speciale] = valore_rivelato

    def annulla_ultimo(self) -> tuple[str, int | None] | None:
        """
        Annulla l'ultima apertura.

        Returns:
            (tipo, valore) dove tipo è "numerico" o "speciale".
            None se non c'è nulla da annullare.

        Nota: dato che non conserviamo l'ordine cronologico preciso tra
        numerici e speciali, annulliamo prima gli speciali (se ce ne sono),
        poi i numerici. È un'approssimazione.
        """
        if self.speciali_aperti:
            id_ultimo = self.speciali_aperti.pop()
            valore = self.valori_speciali_rivelati.pop(id_ultimo, None)
            self.speciali_chiusi.add(id_ultimo)
            if valore is not None:
                self.valori_disponibili.add(valore)
                if valore in self.valori_aperti:
                    self.valori_aperti.remove(valore)
            return ("speciale", valore)

        if self.valori_aperti:
            valore = self.valori_aperti.pop()
            self.valori_disponibili.add(valore)
            return ("numerico", valore)

        return None

    def reset(self) -> None:
        """Riporta lo stato a inizio partita."""
        config = carica_configurazione_premi()
        self.valori_disponibili = set(config.premi)
        self.valori_aperti = []
        self.speciali_chiusi = {s.id for s in config.pacchi_speciali}
        self.speciali_aperti = []
        self.valori_speciali_rivelati = {}
        self.offerta_corrente = None

    # -- serializzazione -----------------------------------------------------

    def to_dict(self) -> dict:
        """Serializza lo stato in un dict (per il DB)."""
        return {
            "valori_disponibili": sorted(self.valori_disponibili),
            "valori_aperti": list(self.valori_aperti),
            "speciali_chiusi": sorted(self.speciali_chiusi),
            "speciali_aperti": list(self.speciali_aperti),
            "valori_speciali_rivelati": dict(self.valori_speciali_rivelati),
            "offerta_corrente": self.offerta_corrente,
        }

    @classmethod
    def from_dict(cls, dati: dict) -> "StatoEsteso":
        """Ricostruisce uno stato da un dict (dal DB)."""
        return cls(
            valori_disponibili=set(dati.get("valori_disponibili", [])),
            valori_aperti=list(dati.get("valori_aperti", [])),
            speciali_chiusi=set(dati.get("speciali_chiusi", [])),
            speciali_aperti=list(dati.get("speciali_aperti", [])),
            valori_speciali_rivelati=dict(dati.get("valori_speciali_rivelati", {})),
            offerta_corrente=dati.get("offerta_corrente"),
        )


__all__ = ["StatoEsteso"]