# JobScraper

Counts job posts from WhatsApp channels by job category, place, channel and month.
A post can list several jobs (title + link); the "amount" is the number of jobs. The place is read from the linked vacancy page (cyberjob.az) when it is still online.

## Setup
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-pipeline.txt   # requirements.txt alone is enough to run the dashboard
cp .env.example .env   # add your free GEMINI_API_KEY
```

## 1a. Get the posts with Node (no scrolling, try this first)
`collector/` reads channels straight from WhatsApp's servers with Baileys (unofficial, against WhatsApp's ToS,
so a ban is possible; it only reads, never sends; a secondary number is safer).
```bash
cd collector && npm install
node fetch_channel.js --probe --link https://whatsapp.com/channel/XXXX     # scan the QR once; shows what the server returns
node fetch_channel.js --channel "Jobs A" --link https://whatsapp.com/channel/XXXX --out ../data/jobs_a.json
```
It pages forward from `--since` (default 2025-01-01), saves as it goes, resumes if stopped (Ctrl+C is safe)
and gives exact dates. Whether the server returns posts that far back is untested, so run `--probe` first and
compare the oldest date with what you see on the phone. Add `--follow` if the account doesn't follow the channel.
If history stops too early, use the phone method below for the backlog.

## 1b. Get the posts from the phone (Android, over USB)
WhatsApp Web doesn't load old channel posts, the phone does, so the phone is scripted.
Ctrl+C is safe: progress is saved every 10 steps and on exit, and re-running resumes (`--fresh` starts over).
It scrolls in small steps (40% of the screen, change with `--step 0.3`), never goes back, and skips posts it has
already seen. "no overlap" warnings mean a step was too big; lower `--step`.
Posts cut off with "... Read more" are tapped open so the full text is saved. If your phone isn't in English,
add its label to `READ_MORE_LABELS` in the script; posts it can't expand are saved with `[cut off]` at the end.
1. Enable Developer options + USB debugging, connect, accept the prompt (`adb devices` should list it).
2. Open the channel in WhatsApp, scrolled to the newest post.
3. Check the script can see the posts: `.venv/bin/python tools/scrape_phone.py --inspect`
   (if no `message_text` or `caption` rows appear, edit `POST_IDS` in the script).
4. `.venv/bin/python tools/scrape_phone.py --channel "Jobs A" --out data/jobs_a.json`
5. Repeat for the second channel.

Any other source works too: a JSON list of `{"channel", "date": "YYYY-MM-DD", "text"}` (see `data/sample_posts.json`).

## 2. Load, extract, view
```bash
.venv/bin/python -m jobscraper.ingest data/jobs_a.json
.venv/bin/python -m jobscraper.ingest data/jobs_b.json
.venv/bin/python -m jobscraper.extract      # Gemini; only new posts are sent
.venv/bin/python -m jobscraper.enrich       # city/company from the vacancy links
.venv/bin/streamlit run app.py
```
Re-running any step is safe (posts are deduplicated, extraction is cached).
Add spelling variants to `data/aliases.json` so places/categories merge in the charts.


## Deploy the dashboard (Streamlit Community Cloud, free)
The dashboard only reads `data/jobs.db`; scraping the phone and calling Gemini stay on your computer.
1. Decide what goes public. `data/jobs.db` holds the full text of every post. If the repository is public, anyone can
   download it. Either keep the repository private, or deploy a copy of the database without the post text (not built yet).
2. Make the database part of the repository: delete the `data/jobs.db` line from `.gitignore`.
   Never commit `.env` (your Gemini key) or `collector/auth/` (the WhatsApp login); both are already ignored.
3. `git init`, commit, and push to a new GitHub repository.
4. Go to https://share.streamlit.io, sign in with GitHub, choose **New app**, pick the repository and branch, set the
   main file to `app.py`, and deploy. It installs `requirements.txt` (the three packages the dashboard needs).
5. To update the data: re-run scrape, ingest, extract and enrich on your computer, commit the new `data/jobs.db`, and push.
   The app redeploys by itself.
Other hosts work too (Hugging Face Spaces with the Streamlit SDK; Render, Railway or a server with
`streamlit run app.py --server.address 0.0.0.0 --server.port $PORT`).
