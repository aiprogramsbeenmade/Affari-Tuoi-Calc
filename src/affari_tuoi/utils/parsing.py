"""
Parsing di importi scritti in vari formati.

Supporta:
- numeri puri: "35000"
- con separatori: "35.000", "35 000", "35,000"
- con suffisso k/K: "35k", "1.5k", "100k"
- con suffisso M/m: "1.5M" (milioni, raro)
- con valuta: "35000 EUR", "€ 35.000", "35k eur"

Restituisce un int, oppure None se il testo non è interpretabile.
"""

from __future__ import annotations

import re

# Limite massimo accettato (10 milioni di euro). Protezione contro input assurdi.
MAX_IMPORTO: int = 10_000_000

# Pattern: numero (con eventuale parte decimale) + suffisso opzionale (k, M)
_PATTERN = re.compile(
    r"""
    (?P<segno>[+-]?)                         # segno opzionale
    (?P<numero>\d+(?:[.,]\d+)?)              # numero, con eventuale parte decimale
    \s*
    (?P<suffisso>[kKmM])?                    # suffisso k/M opzionale
    """,
    re.VERBOSE,
)


def parse_importo(testo: str) -> int | None:
    """
    Interpreta un testo come importo in euro.

    Args:
        testo: stringa scritta dall'utente.

    Returns:
        Importo in euro, o None se non interpretabile.
    """
    if not testo:
        return None

    # Normalizza: rimuovi spazi, simboli di valuta, prefissi
    pulito = testo.strip().lower()
    for rimuovi in ("€", "eur", "euro", "circa", "~"):
        pulito = pulito.replace(rimuovi, "")
    pulito = pulito.strip()

    if not pulito:
        return None

    match = _PATTERN.search(pulito)
    if not match:
        return None

    # Verifica che dopo il match non ci siano altre lettere
    # (es. "35kk" -> match su "35k", resto = "k" -> None)
    resto = pulito[match.end():]
    if re.search(r"[a-zA-Z]", resto):
        return None

    numero_str = match.group("numero")
    segno = match.group("segno") or ""
    suffisso = (match.group("suffisso") or "").lower()

    # Gestione decimali vs separatori migliaia
    if "," in numero_str or "." in numero_str:
        parti = re.split(r"[.,]", numero_str)
        if len(parti) == 2 and len(parti[1]) <= 2:
            # È un decimale: "1.5" -> 1.5, "1,5" -> 1.5
            numero = float(f"{parti[0]}.{parti[1]}")
        else:
            # È un separatore migliaia: "35.000" -> 35000, "1,500" -> 1500
            numero = float(numero_str.replace(".", "").replace(",", ""))
    else:
        numero = float(numero_str)

    # Applica suffisso
    if suffisso == "k":
        numero *= 1_000
    elif suffisso == "m":
        numero *= 1_000_000

    # Applica segno
    if segno == "-":
        numero = -numero

    # Arrotonda
    valore = int(round(numero))

    # Validazione finale
    if valore < 0:
        return None
    if valore > MAX_IMPORTO:
        return None

    return valore


__all__ = ["parse_importo", "MAX_IMPORTO"]