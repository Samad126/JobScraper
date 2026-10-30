"""Specific job titles that deserve their own role, whatever the AI called them.

The AI sometimes files them under a vague or wrong role (Data Engineers under "Data Technology Specialist",
helpdesk staff under "System Administrator"). Rules in data/title_rules.json are checked in order against the job
title (case-insensitive regex); the first match sets the role. Each rule has:
  pattern  regex the title must match
  role     the role to assign
  from     (optional) only apply when the current role is one of these
  unless   (optional) regex; if the title matches it too, skip the rule (mixed titles stay as they are)
  force    (optional) also apply to teaching roles, which are otherwise left alone
"""
import json
import re
from pathlib import Path

from .categories import EDUCATION_WORDS

PATH = Path(__file__).resolve().parent.parent / "data" / "title_rules.json"


def _load():
    if not PATH.exists():
        return []
    out = []
    for r in json.loads(PATH.read_text(encoding="utf-8")):
        out.append((
            re.compile(r["pattern"], re.I),
            r["role"],
            {x.casefold() for x in r.get("from", [])},
            re.compile(r["unless"], re.I) if r.get("unless") else None,
            bool(r.get("force")),
        ))
    return out


_RULES = _load()


def role_for_title(title, role):
    if not isinstance(title, str):
        return role
    teaching = isinstance(role, str) and any(w in role.casefold() for w in EDUCATION_WORDS)
    for pattern, new_role, only_from, unless, force in _RULES:
        if teaching and not force:
            continue  # "Data Analytics Instructor" is not a Data Analyst
        if only_from and (not isinstance(role, str) or role.casefold() not in only_from):
            continue
        if not pattern.search(title) or (unless and unless.search(title)):
            continue
        return new_role
    return role
