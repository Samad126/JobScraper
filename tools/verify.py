"""Check that nothing was dropped or wrongly merged between the scraped JSON files and what the dashboard shows.

  python tools/verify.py data/cyberjob_phone.json data/cyberjob_phone_intern.json

Prints PASS/FAIL per check (exit code 1 if any fails) and writes two files you can read:
  reports/jobs_audit.csv   one row per job: the line from the post it came from next to the title, role, level
  reports/role_groups.txt  for every role, the distinct titles that were grouped into it, with counts
"""
import csv
import difflib
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jobscraper.categories import category_for  # noqa: E402
from jobscraper.level import _ANY_LEVEL  # noqa: E402
from jobscraper.stats import count_by, level_counts, load_jobs  # noqa: E402

VAC = re.compile(r"cyberjob\.az/vacancies/(\d+)")
CUT = re.compile(r"(?:…|\.\.\.)\s*(?:read more|daha çox|devamını oku)\s*$", re.I)
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def source_title(text, url, title):
    """The line of the post this job came from, so it can be compared with the (English) title by eye."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if url:
        for i, ln in enumerate(lines):
            if url in ln:
                rest = ln.replace(url, "").strip(" :-–")
                return rest if rest else (lines[i - 1] if i else "")
    for ln in lines:
        m = re.match(r"(?:vakansiya|vəzifə|position|job title)\s*[:：-]\s*(.+)", ln, re.I)
        if m:
            return m.group(1).strip()
    return lines[0][:120] if lines else ""


def main(files):
    db = sqlite3.connect(f"file:{ROOT / 'data' / 'jobs.db'}?mode=ro", uri=True)
    posts = [p for f in files for p in json.load(open(f, encoding="utf-8"))]

    # 1. nothing from the files is missing from the database, and nothing extra is in it
    in_db = {(c, t) for c, t in db.execute("select channel, text from posts")}
    in_files = {(p["channel"], p["text"].strip()) for p in posts if p["text"].strip()}
    check("every scraped post is in the database", not (in_files - in_db), f"{len(in_files)} posts, missing {len(in_files - in_db)}")
    check("the database holds no post that is not in the files", not (in_db - in_files), f"extra {len(in_db - in_files)}")
    wrong_date = sum(1 for p in posts if db.execute("select posted_at from posts where channel=? and text=?", (p["channel"], p["text"].strip())).fetchone()[0] != p["date"])
    check("post dates are identical to the files", wrong_date == 0, f"{wrong_date} differ")
    check("no post is saved cut off at 'Read more'", not any(CUT.search(p["text"]) for p in posts))

    # 2. every post has been through extraction, and every job points at a real post
    unextracted = db.execute("select count(*) from posts where id not in (select post_id from extracted)").fetchone()[0]
    check("every post has been extracted", unextracted == 0, f"{unextracted} still waiting")
    orphans = db.execute("select count(*) from jobs where post_id not in (select id from posts)").fetchone()[0]
    check("every job belongs to a post", orphans == 0, f"{orphans} orphans")
    foreign = db.execute("select count(*) from jobs j join posts p on p.id=j.post_id where j.url is not null and instr(p.text, j.url)=0").fetchone()[0]
    check("every job link appears in its own post", foreign == 0, f"{foreign} do not")

    # 3. every vacancy link in a post became a job
    missing_links = []
    for pid, text in db.execute("select id, text from posts"):
        have = {u for (u,) in db.execute("select url from jobs where post_id=?", (pid,)) if u}
        for m in set(VAC.findall(text)):
            if not any(f"/vacancies/{m}" in u for u in have):
                missing_links.append((pid[:8], m))
    check("every cyberjob.az vacancy link in a post became a job", not missing_links, f"{len(missing_links)} links without a job {missing_links[:4]}")

    # 4. the dashboard shows exactly what is stored
    df = load_jobs()
    n_db = db.execute("select count(*) from jobs where job_title is not null").fetchone()[0]
    check("dashboard rows equal jobs in the database", len(df) == n_db, f"{len(df)} vs {n_db}")
    for col in ("role", "category", "level", "location"):
        total = int(count_by(df, col)["jobs"].sum())
        check(f"'{col}' chart adds up to every job", total == len(df), f"{total}")
    check("level chart adds up to every job", int(level_counts(df)["jobs"].sum()) == len(df))

    # 5. roles are clean
    with_level = sorted(r for r in df["role"].dropna().unique() if _ANY_LEVEL.search(r))
    check("no role name contains a seniority word", not with_level, str(with_level[:5]))
    no_category = sorted(r for r in df["role"].dropna().unique() if category_for(r) is None)
    check("every role has a category", not no_category, str(no_category[:5]))
    check("no job lacks a role", df["role"].isna().sum() == 0, f"{int(df['role'].isna().sum())} without")

    # 6. files to read by eye
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    similar = 0
    with open(out / "jobs_audit.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["date", "channel", "line from the post", "job title", "role", "level", "category", "url"])
        for _, r in df.sort_values(["posted_at", "channel"]).iterrows():
            url = r["url"] if isinstance(r["url"], str) else None
            src = source_title(r["text"], url, r["job_title"])
            similar += difflib.SequenceMatcher(None, src.casefold(), r["job_title"].casefold()).ratio() >= 0.8
            w.writerow([str(r["posted_at"])[:10], r["channel"], src, r["job_title"], r["role"], r["level"] or "", r["category"], url or ""])
    groups = defaultdict(Counter)
    for t, role in zip(df["job_title"], df["role"]):
        groups[role][t] += 1
    with open(out / "role_groups.txt", "w", encoding="utf-8") as f:
        for role, titles in sorted(groups.items(), key=lambda kv: -sum(kv[1].values())):
            f.write(f"{role}  ({sum(titles.values())} jobs, {len(titles)} distinct titles)\n")
            for t, n in titles.most_common():
                f.write(f"    {n:3d}  {t}\n")
            f.write("\n")
    print(f"\n{similar} of {len(df)} job titles are (nearly) identical to the line in the post; the rest are translations or rewordings.")
    print(f"Wrote {out / 'jobs_audit.csv'} and {out / 'role_groups.txt'}")
    failed = results.count(False)
    print(f"\n{len(results) - failed} checks passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1:]))
