"""List role names with their counts and show near-duplicates, so you can merge them.

  python -m jobscraper.roles

To merge two roles, add a line to data/aliases.json under "role", e.g.
  {"role": {"software engineer": "Software Developer", "back-end developer": "Backend Developer"}}
and the next extract uses it. For jobs already in the database, run:  python -m jobscraper.roles --apply
"""
import argparse
import difflib
import re

from .db import connect
from .normalize import normalize


def _key(role):
    """Spelling-insensitive form: 'Back-end Developers' and 'backend developer' give the same key."""
    k = re.sub(r"[^\w\s]", "", role.casefold().replace("-", ""))
    k = re.sub(r"\bsoftware\b", "", k)  # "Backend Software Developer" is just "Backend Developer"
    k = re.sub(r"\bdevelopers\b", "developer", k)
    k = re.sub(r"\bengineers\b", "engineer", k)
    k = re.sub(r"\banalysts\b", "analyst", k)
    return " ".join(sorted(k.split()))


def near_duplicates(counts, cutoff=0.82):
    roles = sorted(counts, key=counts.get, reverse=True)
    pairs = []
    for i, a in enumerate(roles):
        for b in roles[i + 1 :]:
            same = _key(a) == _key(b)
            ratio = difflib.SequenceMatcher(None, a.casefold(), b.casefold()).ratio()
            if same or ratio >= cutoff:
                pairs.append((a, counts[a], b, counts[b], 1.0 if same else round(ratio, 2)))
    return pairs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="re-apply data/aliases.json and spelling merges to jobs already stored")
    a = ap.parse_args()
    conn = connect()
    if a.apply:
        counts = dict(conn.execute("SELECT role, COUNT(*) FROM jobs WHERE role IS NOT NULL GROUP BY role"))
        canon = {}
        for role in sorted(counts, key=counts.get, reverse=True):  # the most common spelling of each key wins
            canon.setdefault(_key(role), role)
        changed = 0
        for role in counts:
            new = normalize("role", canon[_key(role)])
            if new != role:
                changed += conn.execute("UPDATE jobs SET role = ? WHERE role = ?", (new, role)).rowcount
        conn.commit()
        print(f"merged {changed} jobs into their grouped role names")
    counts = dict(conn.execute("SELECT role, COUNT(*) FROM jobs WHERE role IS NOT NULL GROUP BY role"))
    print(f"{len(counts)} distinct roles over {sum(counts.values())} jobs. Top 25:")
    for r, n in sorted(counts.items(), key=lambda x: -x[1])[:25]:
        print(f"  {n:4d}  {r}")
    pairs = near_duplicates(counts)
    print(f"\n{len(pairs)} similar pairs you may want to merge (add to data/aliases.json under \"role\"):")
    for a_, na, b_, nb, ratio in pairs[:40]:
        print(f"  {a_!r} ({na})  ~  {b_!r} ({nb})   similarity {ratio}")


if __name__ == "__main__":
    main()
