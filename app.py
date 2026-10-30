import plotly.express as px
import streamlit as st

from jobscraper.stats import (
    count_by,
    count_stack,
    group_level_matrix,
    level_counts,
    load_jobs,
    per_month,
    role_level_matrix,
    title_groups,
)


def level_heatmap(matrix):
    """Rows = groups (the label shows the group's total), columns = levels. Colours are scaled to the named levels so
    the 'Not stated' column does not wash them out; the numbers are exact."""
    heat = matrix.drop(columns="Total")
    heat.index = [f"{name} ({total})" for name, total in zip(matrix.index, matrix["Total"])]
    known_levels = heat.drop(columns="Not stated", errors="ignore")
    cap = int(known_levels.values.max()) if known_levels.size else 0
    st.plotly_chart(
        px.imshow(heat, text_auto=True, aspect="auto", color_continuous_scale="Blues", zmin=0, zmax=cap or None,
                  labels={"x": "Level", "y": "Position (total)", "color": "Jobs"}),
        width="stretch",
    )
    if "Not stated" in heat.columns:
        st.caption("Colours are scaled to the levels that are named, so the 'Not stated' column (usually the largest) does not wash them out. The numbers are exact.")


st.set_page_config(page_title="Job Channel Stats", layout="wide")
st.title("Job channel statistics")

df = load_jobs()
if df.empty:
    st.info("No data yet. Run ingest and extract first (see README).")
    st.stop()

with st.sidebar:
    channels = st.multiselect("Channel", sorted(df["channel"].unique()), default=sorted(df["channel"].unique()))
    dated = df["posted_at"].dropna()
    if not dated.empty:
        lo, hi = dated.min().date(), dated.max().date()
        picked = st.date_input("Date range", (lo, hi), min_value=lo, max_value=hi)
        start, end = picked if len(picked) == 2 else (lo, hi)  # while only one end is picked, show everything
        # Jobs whose post has no date are shown only for the full range; a narrower range cannot include them.
        in_range = True if (start, end) == (lo, hi) else df["posted_at"].dt.date.between(start, end)
        if df["posted_at"].isna().any():
            st.caption(f"{int(df['posted_at'].isna().sum())} jobs have no date; they appear only with the full date range.")
    else:
        in_range = True
    levels_present = [x for x in ["Intern", "Junior", "Middle", "Senior", "Lead", "Head"] if x in set(df["level"].dropna())]
    levels = st.multiselect("Level (empty = all)", levels_present + ["Not stated"])
    show_all = st.checkbox("Show all (no limit)")
    top = None if show_all else st.slider("Show top N", 5, 100, 15)

in_level = df["level"].fillna("Not stated").isin(levels) if levels else True
f = df[df["channel"].isin(channels) & in_range & in_level]

c1, c2, c3 = st.columns(3)
c1.metric("Jobs", len(f))
c2.metric("Categories", f["category"].nunique())
c3.metric("Places", f["location"].nunique())

left, right = st.columns(2)
with left:
    st.subheader("Jobs by category")
    d = count_by(f, "category", top)
    st.plotly_chart(px.bar(d, x="jobs", y="category", orientation="h").update_yaxes(autorange="reversed"), width="stretch")
with right:
    st.subheader("Jobs by place")
    known = f[f["location"].notna()]
    no_place = len(f) - len(known)
    if no_place:
        st.caption(f"{no_place:,} of {len(f):,} jobs ({no_place / len(f):.0%}) name no place in the post or its link, so they are not in this chart.")
    if known.empty:
        st.caption("No place known for the selected jobs.")
    else:
        st.plotly_chart(px.bar(count_by(known, "location", top), x="jobs", y="location", orientation="h").update_yaxes(autorange="reversed"), width="stretch")

left, right = st.columns(2)
with left:
    st.subheader("Jobs by channel")
    st.plotly_chart(px.pie(count_by(f, "channel"), names="channel", values="jobs"), width="stretch")
with right:
    st.subheader("Jobs per month")
    m = per_month(f)
    if m.empty:
        st.caption("No dated posts.")
    else:
        st.plotly_chart(px.bar(m, x="month", y="jobs"), width="stretch")
        undated = int(f["posted_at"].isna().sum())
        if undated:
            st.caption(f"{undated} jobs have no date and are not in this chart.")

st.subheader("Positions: what is hiring, and at which level")
left, right = st.columns(2)
with left:
    st.caption("Most advertised roles (similar titles grouped, seniority removed)")
    st.plotly_chart(px.bar(count_by(f, "role", top), x="jobs", y="role", orientation="h").update_yaxes(autorange="reversed"), width="stretch")
with right:
    st.caption("Seniority levels")
    st.plotly_chart(px.bar(level_counts(f), x="level", y="jobs"), width="stretch")
matrix = role_level_matrix(f, top)
if not matrix.empty:
    st.caption("Jobs per role and level (for ranking positions by how many are hiring at your level)")
    level_heatmap(matrix)

st.subheader("Developer positions by technology")
dev = f.dropna(subset=["specialization"])
if dev.empty:
    st.caption("No developer jobs in the selected data.")
else:
    unstated = int(dev["specialization"].str.contains("not stated").sum())
    st.caption(
        "Developer roles split by their main technology, e.g. .NET Backend, Java Backend, React Frontend. The technology comes from "
        "the job title, or, when the post advertises a single job, from the technology mentioned most in its text. A .NET, Java, Python "
        "or PHP developer counts as a backend job. "
        f"{unstated} of {len(dev)} developer jobs name no technology, mostly posts that only list job titles and links. "
        "Every position is shown here, whatever the 'Show top N' setting."
    )
    st.plotly_chart(
        px.bar(count_by(dev, "specialization"), x="jobs", y="specialization", orientation="h").update_yaxes(autorange="reversed"),
        width="stretch",
    )
    st.caption("Jobs per technology position and level")
    level_heatmap(group_level_matrix(dev, "specialization", None))

st.subheader("Technologies in job posts")
tech = count_stack(f, top)
if tech.empty:
    st.caption("No technologies mentioned in the selected jobs.")
else:
    st.plotly_chart(px.bar(tech, x="jobs", y="stack", orientation="h").update_yaxes(autorange="reversed"), width="stretch")
    st.caption("A job can mention several technologies, so these bars add up to more than the number of jobs.")

st.subheader("Job titles")
st.caption("Spelling variants are counted together (Front-End / Frontend, Help Desk / Helpdesk, İT / IT).")
st.dataframe(title_groups(f, None if show_all else 200), width="stretch", hide_index=True)

with st.expander("All jobs"):
    st.dataframe(
        f[["channel", "posted_at", "job_title", "role", "specialization", "level", "category", "location", "company", "stack", "text"]],
        width="stretch", hide_index=True,
        column_config={"posted_at": st.column_config.DateColumn("posted")},
    )
