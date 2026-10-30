"""Load posts from a JSON file into SQLite.

Input format: a list of {"channel": str, "date": "YYYY-MM-DD" | null, "text": str}.
Re-running is safe: posts are deduplicated by a hash of channel + date + text.
"""
import argparse
import hashlib
import json
import re

from .db import connect


# A post cut off by WhatsApp ends with "... Read more" (label depends on the phone language).
_CUT = re.compile(r"(?:…|\.\.\.)\s*(?:read more|daha çox oxu|daha çox|devamını oku|читать далее|ещё|leer más|اقرأ المزيد)\s*$", re.I)


def post_id(channel, date, text):
    return hashlib.sha1(f"{channel}|{date or ''}|{text}".encode()).hexdigest()


def ingest(path, conn=None):
    conn = conn or connect()
    with open(path, encoding="utf-8") as f:
        posts = json.load(f)
    added = 0
    for p in posts:
        text = (p.get("text") or "").strip()
        if not text:
            continue
        cut = _CUT.search(text)
        head = (_CUT.sub("", text).rstrip() if cut else text)[:80]
        if cut and conn.execute(
            "SELECT 1 FROM posts WHERE channel = ? AND substr(text, 1, ?) = ? AND length(text) > ? LIMIT 1",
            (p["channel"], len(head), head, len(text)),
        ).fetchone():
            continue  # a fuller copy of this post is already stored
        if not cut:  # drop shortened copies of this post, e.g. from an earlier phone scrape
            for (old,) in conn.execute(
                "SELECT id FROM posts WHERE channel = ? AND substr(text, 1, ?) = ? AND length(text) < ?",
                (p["channel"], len(head), head, len(text)),
            ).fetchall():
                row = conn.execute("SELECT text FROM posts WHERE id = ?", (old,)).fetchone()
                if row and _CUT.search(row[0]):
                    for table, col in (("jobs", "post_id"), ("extracted", "post_id"), ("posts", "id")):
                        conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (old,))
        cur = conn.execute(
            "INSERT OR IGNORE INTO posts (id, channel, posted_at, text) VALUES (?, ?, ?, ?)",
            (post_id(p["channel"], p.get("date"), text), p["channel"], p.get("date"), text),
        )
        added += cur.rowcount
    conn.commit()
    return added, len(posts)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file")
    args = ap.parse_args()
    added, total = ingest(args.file)
    print(f"{added} new posts ({total - added} duplicates/empty) from {total}")
