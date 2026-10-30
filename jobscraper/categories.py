"""Broad field of a job, decided from its role instead of the AI's per-job guess (which was inconsistent:
most DevOps Engineers came back as plain "IT").

data/role_categories.json maps a role name to a category. Roles with "Instructor" or "Mentor" in the name are
Education. A role that is not listed keeps the category the AI wrote.
"""
import json
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "role_categories.json"
_MAP = {k.casefold(): v for k, v in json.loads(PATH.read_text(encoding="utf-8")).items()} if PATH.exists() else {}
EDUCATION_WORDS = ("instructor", "mentor", "trainer", "təlimçi", "müəllim")


def category_for(role, fallback=None):
    if not isinstance(role, str):
        return fallback
    if role.casefold() in _MAP:
        return _MAP[role.casefold()]
    if any(w in role.casefold() for w in EDUCATION_WORDS):
        return "Education"
    return fallback
