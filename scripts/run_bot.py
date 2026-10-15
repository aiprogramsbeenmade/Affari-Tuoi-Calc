"""Avvia il bot Telegram da root del progetto."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from affari_tuoi.bot.main import main

if __name__ == "__main__":
    main()