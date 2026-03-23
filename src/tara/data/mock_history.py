import json
from pathlib import Path

_DATA_DIR = Path(__file__).parent

NEGOTIATION_HISTORY_DB: dict[str, list[dict]] = json.loads(
    (_DATA_DIR / "negotiation_history.json").read_text()
)
