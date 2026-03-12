import json
from pathlib import Path

_DATA_DIR = Path(__file__).parent

BORROWER_DB: dict[str, dict] = json.loads((_DATA_DIR / "borrowers.json").read_text())
