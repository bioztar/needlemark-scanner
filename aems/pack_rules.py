"""Versioned, dated thresholds for the query pack (aems/data/pack_rules.json)."""
from __future__ import annotations

import json
from pathlib import Path

PACK_RULES_PATH = Path(__file__).parent / "data" / "pack_rules.json"


def load_pack_rules(path: Path | None = None) -> dict:
    return json.loads((path or PACK_RULES_PATH).read_text())
