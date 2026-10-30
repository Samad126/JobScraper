"""Merge spelling variants so counts group correctly.

Add your own variants to data/aliases.json:
  {"location": {"الرياض": "Riyadh"}, "category": {"dev": "Software Developer"}}
"""
import json
import re
from pathlib import Path

ALIASES_PATH = Path(__file__).resolve().parent.parent / "data" / "aliases.json"


def _load_aliases():
    if ALIASES_PATH.exists():
        raw = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
        return {
            field: {k.casefold().strip(): v for k, v in mapping.items()}
            for field, mapping in raw.items()
        }
    return {}


_ALIASES = _load_aliases()


def normalize(field, value):
    if not value:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    if not value or value.casefold() in {"unknown", "n/a", "none", "null"}:
        return None
    mapped = _ALIASES.get(field, {}).get(value.casefold())
    if mapped:
        return mapped
    # Capitalize all-lowercase words only, so acronyms (IT, GRC, SOC) and non-Latin text survive.
    return " ".join(w.capitalize() if w.islower() else w for w in value.split(" "))
