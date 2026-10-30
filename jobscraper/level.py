"""Seniority level of a job, read from its title (free, no AI tokens) and used to clean up role names.

Levels, lowest to highest: Intern, Junior, Middle, Senior, Lead, Head.
Azerbaijani words are included because the channels post in it. "Baş" (chief) and "Aparıcı" (leading) are
counted as Senior, which is a judgement call: edit LEVEL_PATTERNS if you read them differently.
"""
import re

LEVELS = ["Intern", "Junior", "Middle", "Senior", "Lead", "Head"]

# Checked in this order; the first level whose pattern matches the title wins ("Senior Team Lead" -> Lead).
LEVEL_PATTERNS = [
    ("Intern", r"\bintern(?:ship)?s?\b|\btrainee\b|\btəcrübəçi\w*|\bstajyor\w*"),
    ("Junior", r"\bjunior\b|\bjr\b\.?|\bentry[\s-]*level\b|\bkiçik\b|\bbaşlanğıc\b"),
    ("Lead", r"(?:qrup|komanda|texniki)\s+rəhbər\w*|\bteam\s+leader\b"),
    ("Head", r"\bhead\s+of\b|\bdirector\b|\bchief\b|\bvp\b|\bmüdir\w*|\bdirektor\w*|(?:şöbə|bölmə|departament|idarə)\w*\s+rəhbər\w*"),
    ("Lead", r"\blead\b|\bleader\b|\bteam\s*lead\b|\btech\s*lead\b|\bprincipal\b|\bstaff\b"),
    ("Senior", r"\bsenior\b|\bsr\b\.?|\bleading\b|\baparıcı\b|\bbaş\b"),
    ("Middle", r"\bmiddle\b|\bmid[\s-]*level\b|\bmid\b|\borta\s+səviyyə\w*"),
]
_COMPILED = [(lvl, re.compile(p, re.I)) for lvl, p in LEVEL_PATTERNS]
_ANY_LEVEL = re.compile("|".join(p for _, p in LEVEL_PATTERNS), re.I)


def detect_level(title):
    """Level named in a job title, or None."""
    if not title:
        return None
    for level, pattern in _COMPILED:
        if pattern.search(title):
            return level
    return None


def clean_level(value):
    """Map whatever the AI returned onto our scale; None when it is not one of the levels."""
    if not value:
        return None
    v = str(value).strip().casefold()
    for level in LEVELS:
        if v == level.casefold():
            return level
    aliases = {"mid": "Middle", "mid-level": "Middle", "junior/entry": "Junior", "entry": "Junior", "entry-level": "Junior",
               "trainee": "Intern", "internship": "Intern", "sr": "Senior", "jr": "Junior", "director": "Head", "principal": "Lead"}
    return aliases.get(v)


def strip_level(text):
    """Remove seniority words (and brackets left empty) from a role name: 'Senior QA Engineer (E2E)' -> 'QA Engineer (E2E)'."""
    if not text:
        return text
    out = _ANY_LEVEL.sub(" ", text)
    out = re.sub(r"\(\s*[-/,;]*\s*\)", " ", out)       # "()" left behind by "(Entry-level)"
    out = re.sub(r"\s*[-/,–]\s*(?=[-/,–]|$)", " ", out)  # dangling separators
    out = re.sub(r"\s+", " ", out).strip(" -/,–")
    if out.count("(") != out.count(")"):  # a bracket lost its partner when a word inside was removed
        out = out.replace("(", "").replace(")", "").strip()
    return out or text


_INTERN_WORDS = re.compile(r"\bintern\w*|\btrainee\b|\btəcrübə\w*|\bstajyor\w*", re.I)


def grounded_level(title, ai_level, text, channel=""):
    """The level to show. A level written in the title always wins. A level that only the AI supplied is kept
    only if the post itself backs it up (the word appears in the post text, or it is an internship in the
    internship channel); otherwise it is dropped, because a level we cannot point to in the post is a guess."""
    found = detect_level(title)
    if found:
        return found
    level = clean_level(ai_level)
    if not level:
        return None
    if level == "Intern":
        return level if _INTERN_WORDS.search(text or "") or "intern" in (channel or "").casefold() else None
    pattern = dict((lvl, p) for lvl, p in _COMPILED).get(level)
    return level if pattern and pattern.search(text or "") else None
