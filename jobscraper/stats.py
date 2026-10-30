import re
import unicodedata

import pandas as pd

from .categories import category_for
from .db import connect
from .title_rules import role_for_title
from .normalize import normalize
from .level import LEVELS, grounded_level
from .specialization import specialization


_OTHER_CITIES = ("naxçıvan", "ucar", "ağcəbədi", "ağdaş", "gəncə", "sumqayıt", "şəki", "lənkəran", "mingəçevir", "şirvan", "xankəndi")


def group_place(value):
    """'Bakı, Çinar Plaza' and 'Bakı Şəhəri' are Baku; a list of several cities is not one place."""
    if not isinstance(value, str):
        return value
    v = value.strip()
    if re.match(r"(?i)^(bakı|baku)\b", v):
        rest = [p.strip().casefold() for p in re.split(r"[,/]", v)[1:]]
        return "Multiple cities" if any(c in p for p in rest for c in _OTHER_CITIES) else "Baku"
    return v


def load_jobs(conn=None):
    """One row per job (a post can contain several). The linked page's city/company win."""
    conn = conn or connect()
    df = pd.read_sql_query(
        """SELECT p.id AS post_id, p.channel, p.posted_at, p.text,
                  j.job_title, j.role, j.level, j.category,
                  COALESCE(v.city, j.location)   AS location,
                  COALESCE(v.company, j.company) AS company,
                  j.url, j.stack
           FROM posts p
           JOIN jobs j ON j.post_id = p.id
           LEFT JOIN vacancies v ON v.url = j.url AND v.status = 'ok'
           WHERE j.job_title IS NOT NULL""",
        conn,
    )
    df["posted_at"] = pd.to_datetime(df["posted_at"], errors="coerce")
    for column in ("role", "location", "category"):  # apply data/aliases.json to what is already stored
        df[column] = df[column].map(lambda v, c=column: normalize(c, v) if isinstance(v, str) else v)
    df["location"] = df["location"].map(group_place)
    df["role"] = [role_for_title(t, r) for t, r in zip(df["job_title"], df["role"])]  # specific titles win
    df["level"] = [grounded_level(t, l, x, ch) for t, l, x, ch in zip(df["job_title"], df["level"], df["text"], df["channel"])]
    jobs_in_post = df.groupby("post_id")["job_title"].transform("count")
    df["specialization"] = [specialization(r, t, x, n) for r, t, x, n in zip(df["role"], df["job_title"], df["text"], jobs_in_post)]
    df["category"] = [category_for(r, c) for r, c in zip(df["role"], df["category"])]  # field follows the role
    return df


def count_by(df, column, top=None):
    s = df[column].fillna("Unknown").value_counts()
    if top:
        s = s.head(top)
    return s.rename_axis(column).reset_index(name="jobs")


def per_month(df):
    d = df.dropna(subset=["posted_at"])
    return (
        d.groupby(d["posted_at"].dt.to_period("M").dt.to_timestamp())
        .size()
        .reset_index(name="jobs")
        .rename(columns={"posted_at": "month"})
    )


def count_stack(df, top=None):
    """Jobs per technology; a job listing several technologies counts once for each."""
    tech = df["stack"].dropna().str.split(", ").explode()
    out = tech.value_counts().rename_axis("stack").reset_index(name="jobs")
    return out.head(top) if top else out


NO_LEVEL = "Not stated"


def level_counts(df):
    """Jobs per seniority level, in ladder order, with the posts that name no level last."""
    c = df["level"].fillna(NO_LEVEL).value_counts()
    order = LEVELS + [NO_LEVEL]
    return c.reindex([x for x in order if x in c.index]).rename_axis("level").reset_index(name="jobs")


def group_level_matrix(df, column, top=15):  # top=None: every group
    """Rows = the most common values of `column` (role, specialization...), columns = levels: how many jobs of
    each group are open at each level."""
    d = df.dropna(subset=[column]).copy()
    d["level"] = d["level"].fillna(NO_LEVEL)
    counts = d[column].value_counts()
    keep = (counts if top is None else counts.head(top)).index
    m = d[d[column].isin(keep)].pivot_table(index=column, columns="level", values="job_title", aggfunc="count", fill_value=0)
    cols = [c for c in LEVELS + [NO_LEVEL] if c in m.columns]
    m = m.reindex(keep)[cols]
    m.insert(0, "Total", m.sum(axis=1))
    return m


def role_level_matrix(df, top=15):
    return group_level_matrix(df, "role", top)



def _title_key(title):
    """Spelling-insensitive key: 'Front-End Developer', 'Frontend Developer' and 'FRONTEND developer' match,
    and so do 'İT' and 'IT' (accents and punctuation are ignored)."""
    t = unicodedata.normalize("NFKD", title)
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold()
    return "".join(c for c in t if c.isalnum())


def title_groups(df, top=200):
    """Job titles with spelling variants counted together. Shows the most common spelling, its role, how many jobs,
    and how many different spellings were combined."""
    d = df.dropna(subset=["job_title"]).copy()
    d["key"] = d["job_title"].map(_title_key)
    rows = []
    for _, g in d.groupby("key"):
        spellings = g["job_title"].value_counts()
        best = sorted(spellings.index, key=lambda t: (-spellings[t], not t.isascii(), t))[0]
        rows.append({"title": best, "role": g["role"].mode().iat[0] if g["role"].notna().any() else None, "jobs": len(g), "spellings merged": len(spellings)})
    out = pd.DataFrame(rows, columns=["title", "role", "jobs", "spellings merged"])
    out = out.sort_values(["jobs", "title"], ascending=[False, True])
    return (out if top is None else out.head(top)).reset_index(drop=True)
