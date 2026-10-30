"""Fetch the vacancy pages linked from posts to get the job's city and company.

Posts often have only a title and a link; the place lives on the linked page.
Currently supports cyberjob.az/vacancies/<id>. The site only keeps active vacancies,
so old links 404: they're recorded as 'expired' (never retried) and keep no city.
"""
import argparse
import html
import re
import time
import urllib.error
import urllib.request

from .db import connect
from .normalize import normalize

URL_RE = re.compile(r"https?://(?:www\.)?cyberjob\.az/vacancies/\d+")
DELAY = 0.5  # seconds between requests, to be polite to the site


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "ignore")


def parse_cyberjob(page):
    """Return dict(title, company, city, job_type, deadline) from a vacancy page."""
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    title = html.unescape(re.sub(r"<[^>]+>", "", h1.group(1))).strip() if h1 else None
    body = re.sub(r"<(script|style).*?</\1>", "", page, flags=re.S)
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body)))

    def field(label, stop):
        m = re.search(rf"{label} (.+?) {stop}", text)
        return m.group(1).strip() if m else None

    company = None
    if title:
        m = re.search(re.escape(title) + r" (.+?) Son tarix:", text)
        company = m.group(1).strip() if m else None
    return {
        "title": title,
        "company": company,
        "city": field("Şəhər", "İş növü"),
        "job_type": field("İş növü", "İş təcrübəsi"),
        "deadline": (re.search(r"Son tarix:? (\d{2}\.\d{2}\.\d{4})", text) or [None, None])[1],
    }


def enrich(conn=None):
    conn = conn or connect()
    urls = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT url FROM jobs WHERE url IS NOT NULL"
            " AND url NOT IN (SELECT url FROM vacancies)"
        )
        if URL_RE.fullmatch(r[0].rstrip("/"))
    ]
    print(f"{len(urls)} vacancy pages to fetch")
    ok = expired = 0
    for n, url in enumerate(urls, 1):
        try:
            d = parse_cyberjob(_fetch(url.rstrip("/")))
            conn.execute(
                "INSERT OR REPLACE INTO vacancies VALUES (?, 'ok', ?, ?, ?, ?, ?)",
                (url, d["title"], normalize("company", d["company"]), normalize("location", d["city"]), d["job_type"], d["deadline"]),
            )
            ok += 1
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                conn.execute("INSERT OR REPLACE INTO vacancies (url, status) VALUES (?, 'expired')", (url,))
                expired += 1
            else:
                print(f"  {url}: HTTP {e.code}, will retry next run")
        except Exception as e:
            print(f"  {url}: {type(e).__name__}, will retry next run")
        if n % 25 == 0:
            conn.commit()
            print(f"  {n}/{len(urls)}")
        time.sleep(DELAY)
    conn.commit()
    return ok, expired


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    ok, expired = enrich()
    print(f"{ok} fetched, {expired} expired (no city available)")
