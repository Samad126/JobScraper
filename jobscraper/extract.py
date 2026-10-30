"""Extract job title / category / location from posts with the Gemini API (free tier).

Only posts without a row in `jobs` are sent, so re-runs cost nothing.
Env: GEMINI_API_KEY (required), GEMINI_MODEL (default gemini-2.5-flash).
"""
import argparse
import json
import os
import re
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

from .db import connect
from .level import clean_level, detect_level, strip_level
from .normalize import normalize
from .stack import detect_stack

load_dotenv()

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
BATCH_SIZE = 25
MAX_CHARS = 700  # per post sent to Gemini: company, job title and place are at the top

PROMPT = """Each item below is one message from a WhatsApp job channel (any language, e.g. Azerbaijani, English).
A single message can advertise SEVERAL jobs, often a title line followed by its link, or one job as a
full description with labelled lines (Azerbaijani: "Şirkət" = company, "Vakansiya" = job title,
"Vəzifə öhdəlikləri" = duties, "Yer"/"Şəhər" = place; Bakı = Baku).
For every item return a list of the jobs in it, one entry per job:
- job_title: the position exactly as advertised but in English, including any seniority word (e.g. "Senior QA Engineer").
  Keep acronyms (GRC, SOC, IT).
- role: the kind of work WITHOUT seniority, so similar positions share one name. "Senior QA Engineer", "QA Automation
  Engineer" and "Junior QA Engineer" are all role "QA Engineer"; "Backend Software Developer" and "Back-end Developer"
  are both "Backend Developer". Short, singular, English, Title Case, keep acronyms.
- level: one of "Intern", "Junior", "Middle", "Senior", "Lead", "Head", or null when the post does not say.
  Azerbaijani: "Təcrübəçi" = Intern, "Kiçik" = Junior, "Aparıcı"/"Baş" = Senior, "Şöbə müdiri" = Head. "Entry-level" = Junior.
  Do not guess a level from the years of experience or the company; only use what is stated.
- category: a broad field in English, singular (e.g. "Accounting", "IT", "Cybersecurity", "Teaching").
- location: the city/place of the job as written, in English if you can; null if none is given.
- company: employer if named, else null.
- url: the link that belongs to that job, copied exactly from the text; null if it has none.
If an item is not a job posting, return an empty jobs list.
Return one result per item, with the same "id" as the input."""

_JOB = {
    "type": "OBJECT",
    "properties": {
        "job_title": {"type": "STRING"},
        "role": {"type": "STRING"},
        "level": {"type": "STRING", "nullable": True},
        "category": {"type": "STRING", "nullable": True},
        "location": {"type": "STRING", "nullable": True},
        "company": {"type": "STRING", "nullable": True},
        "url": {"type": "STRING", "nullable": True},
    },
    "required": ["job_title", "role", "level", "category", "location", "company", "url"],
}
SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {"id": {"type": "STRING"}, "jobs": {"type": "ARRAY", "items": _JOB}},
        "required": ["id", "jobs"],
    },
}


def known_roles_note(known_roles):
    if not known_roles:
        return ""
    return ("\nRole names already in use. If a job is the same kind of work as one of these, reuse that name EXACTLY; "
            "only invent a new role when none fits:\n" + json.dumps(list(known_roles), ensure_ascii=False))


def top_roles(conn, limit=80):
    return [r for (r,) in conn.execute(
        "SELECT role FROM jobs WHERE role IS NOT NULL GROUP BY role ORDER BY COUNT(*) DESC LIMIT ?", (limit,))]


def _call(client, batch, known_roles=()):
    items = [{"id": pid, "text": text} for pid, text in batch]
    config = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=SCHEMA, temperature=0
    )
    for attempt in range(6):
        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=PROMPT + known_roles_note(known_roles) + "\n\n" + json.dumps(items, ensure_ascii=False),
                config=config,
            )
            return json.loads(resp.text)
        except Exception as e:  # rate limit / transient errors
            wait = 2 ** attempt * 5
            print(f"  request failed ({type(e).__name__}: {str(e)[:120]}); retrying in {wait}s")
            time.sleep(wait)
    raise RuntimeError("Gemini request kept failing; run again later to resume.")


class Throttle:
    """Keeps requests under a tokens-per-minute and requests-per-minute budget (sliding 60 s window).
    Token counts are estimates (about 2.5 characters per token, pessimistic for non-English text)."""

    def __init__(self, tpm, rpm, clock=time.monotonic, sleep=time.sleep):
        self.tpm, self.rpm, self.clock, self.sleep = tpm, rpm, clock, sleep
        self.sent = []  # (time, tokens)

    def wait(self, tokens):
        while True:
            now = self.clock()
            self.sent = [(t, n) for t, n in self.sent if now - t < 60]
            used = sum(n for _, n in self.sent)
            if len(self.sent) < self.rpm and (used + tokens <= self.tpm or not self.sent):
                self.sent.append((now, tokens))
                return
            pause = max(60 - (now - self.sent[0][0]), 0.5)
            print(f"  pacing: waiting {pause:.0f}s to stay under {self.tpm:,} tokens/min and {self.rpm} requests/min")
            self.sleep(pause)


_URL = re.compile(r"https?://\S+|(?:www\.)?[\w.-]+\.az/\S+")
_VACANCY = re.compile(r"(?:https?://)?(?:www\.)?cyberjob\.az/vacancies/\d+")


def clip(text, max_chars):
    """First max_chars of a post (company, title and place are at the top), plus any links that fall after the
    cut, so a job whose apply link is at the very end still gets it."""
    head = text[:max_chars]
    lost = [u for u in _URL.findall(text[max_chars:]) if u not in head]
    return head + ("\n" + "\n".join(dict.fromkeys(lost[:4])) if lost else "")


def attach_missing_links(conn):
    """A post with exactly one job that has no link, and exactly one cyberjob.az vacancy link in its text:
    the link belongs to that job. Returns how many were attached. Safe to run repeatedly."""
    fixed = 0
    for pid, text in conn.execute("SELECT p.id, p.text FROM posts p JOIN extracted e ON e.post_id = p.id").fetchall():
        links = list(dict.fromkeys(m.group(0) for m in _VACANCY.finditer(text)))
        jobs = conn.execute("SELECT id, url FROM jobs WHERE post_id = ?", (pid,)).fetchall()
        if len(links) == 1 and len(jobs) == 1 and not jobs[0][1]:
            conn.execute("UPDATE jobs SET url = ? WHERE id = ?", (links[0], jobs[0][0]))
            fixed += 1
    conn.commit()
    return fixed


def pending_posts(conn, since=None, include_undated=False):
    """Posts not extracted yet, optionally only those from `since` (YYYY-MM-DD) onwards."""
    sql = "SELECT id, text, posted_at FROM posts WHERE id NOT IN (SELECT post_id FROM extracted)"
    args = []
    if since:
        sql += " AND (posted_at >= ?" + (" OR posted_at IS NULL)" if include_undated else ")")
        args.append(since)
    return conn.execute(sql, args).fetchall()


def extract(conn=None, since=None, include_undated=False, max_chars=MAX_CHARS, dry_run=False, tpm=150_000, rpm=10):
    conn = conn or connect()
    pending = pending_posts(conn, since, include_undated)
    sent = [(pid, clip(text, max_chars)) for pid, text, _ in pending]
    chars = sum(len(t) for _, t in sent) + len(PROMPT) * -(-len(sent) // BATCH_SIZE)
    print(f"{len(pending)} posts to extract with {MODEL}: ~{chars:,} characters, about {chars // 3:,} tokens"
          f" in {-(-len(sent) // BATCH_SIZE)} requests (only the first {max_chars} characters of each post are sent)")
    if dry_run:
        return 0
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    full = {pid: text for pid, text, _ in pending}
    done = 0
    throttle = Throttle(tpm, rpm)
    for i in range(0, len(sent), BATCH_SIZE):
        batch = sent[i : i + BATCH_SIZE]
        throttle.wait(int((sum(len(t) for _, t in batch) + len(PROMPT)) / 2.5))
        results = {r["id"]: r for r in _call(client, batch, top_roles(conn))}
        texts = dict(batch)
        for pid, _ in batch:
            r = results.get(pid)
            if r is None:
                continue  # missing from the reply; will be retried next run
            jobs = r["jobs"]
            for job in jobs:
                url = job.get("url")
                if url and url not in texts[pid]:
                    url = None  # model altered the link; don't trust it
                title = normalize("job_title", job.get("job_title"))
                # Level: an explicit word in the title is more reliable than the model's guess.
                level = detect_level(title) or clean_level(job.get("level"))
                role = normalize("role", strip_level(job.get("role") or title))
                # One job in the post: the whole post describes it, so look for technologies in all of it.
                # Several jobs: only their own titles say anything about the stack.
                stack = detect_stack(full[pid] if len(jobs) == 1 else (title or ""))
                conn.execute(
                    "INSERT OR IGNORE INTO jobs (post_id, job_title, category, location, company, url, stack, role, level)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        pid,
                        title,
                        normalize("category", job.get("category")),
                        normalize("location", job.get("location")),
                        normalize("company", job.get("company")),
                        url,
                        ", ".join(stack) or None,
                        role,
                        level,
                    ),
                )
            conn.execute("INSERT OR IGNORE INTO extracted VALUES (?)", (pid,))
            done += 1
        conn.commit()
        print(f"  {min(i + BATCH_SIZE, len(sent))}/{len(sent)}")
    print(f"attached {attach_missing_links(conn)} missing vacancy links")
    return done


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", help="only posts dated on/after this day, e.g. 2026-01-01 (this year)")
    ap.add_argument("--include-undated", action="store_true", help="with --since, also posts whose date is unknown")
    ap.add_argument("--max-chars", type=int, default=MAX_CHARS, help="characters of each post sent to Gemini")
    ap.add_argument("--tpm", type=int, default=150_000, help="max tokens per minute to send (free tier is about 250k; default leaves headroom)")
    ap.add_argument("--rpm", type=int, default=10, help="max requests per minute to send (check your model's free-tier limit)")
    ap.add_argument("--dry-run", action="store_true", help="only print how many posts/tokens would be sent")
    a = ap.parse_args()
    print(f"extracted {extract(since=a.since, include_undated=a.include_undated, max_chars=a.max_chars, dry_run=a.dry_run, tpm=a.tpm, rpm=a.rpm)} posts")
