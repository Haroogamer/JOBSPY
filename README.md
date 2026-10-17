# ServiceNow Job Crawler

Finds ServiceNow jobs faster than Indeed. Crawls Indeed directly (jobspy)
+ career boards + free job APIs, matches ServiceNow-family roles, and pings
Discord within hours of posting. Zero paid APIs.
Runs on GitHub Actions (4x daily) — see "GitHub Actions" below. The local
cron + Workday sweep path still works for residential-IP runs.

## The rules

- **Relevance:** two tracks, either qualifies —
  - *ServiceNow:* any ServiceNow / Service Now / Now Platform mention in the
    title or description. No title restrictions, no seniority filters.
    ServiceNow-product titles ("Now Assist", "AI Control Tower") also match
    without the brand in the title. Generic AI titles ("GenAI Engineer")
    match only when the description shows ServiceNow involvement.
  - *Forward Deployed:* title mention always matches; otherwise the
    description must name a forward-deployed role (engineer, architect,
    developer, consultant, …). Passing mentions of a deployment model don't.
- **Freshness:** posted within the last 30 days. Stale jobs are dropped,
  no matter how good the match.
- **Location:** United States or Canada. Toronto/GTA hits get a 🌆 badge.
- **Remote:** on-site / hybrid only — remote-only postings are rejected.
- **Government:** US federal / clearance roles out. Canadian government and
  Canadian clearance (Reliability, etc.) are fine.
- **Fit ranking:** matches are scored 0–100 for the senior, AI-heavy target
  profile (senior titles + specialty clusters: AI, GRC/IRM, ITOM/CMDB,
  SAM/HAM, integrations, SPM, upgrades). Ranking never filters — junior
  and generic ServiceNow roles still match, they just surface lower.
  Alerts show a 🎯 Fit field (High/Standard/Low + score).

## How it runs

Two sweeps, each every ~6 hours via local cron:

| Sweep | Coverage |
|---|---|
| `run.py` | 2,248 boards across 6 ATS platforms (Greenhouse / Lever / Ashby / SmartRecruiters / Workable / Jibe-iCIMS) + free APIs (Jobicy, Adzuna, USAJobs) |
| `workday_sweep.py` | 24 priority Workday boards + 30 rotating (full 205-board list every ~36h) |

Workday is split out because it blocks datacenter IPs — it only works from a
residential connection. Both post new matches to the same Discord webhook.

Dedupe is two-layered. Per-URL: `jobs.db` (SQLite) for ATS,
`workday_seen.json` for Workday notified URLs, `workday_checked.json` for
evaluated-but-rejected URLs (so repeat sweeps don't re-fetch descriptions).
The checked cache is keyed by `MATCHER_VERSION` in `crawler/match.py` —
bump the version when the rules change and everything is re-evaluated once.
Cross-source: a canonical key (normalized company + title + city) suppresses
the same role mirrored on two platforms, so a job on Workday + Lever alerts
once. The Workday sweep records its matches in `jobs.db` too, so dedup is
bidirectional. Within one platform the URL hash still governs, so distinct
reqs on the same board still alert.

Enrichment: salary/comp and workplace type are extracted wherever the source
API publishes them (Ashby compensation tiers, Lever salaryRange, Jibe salary
bounds) and stored on the job record; Discord alerts show a 💰 Salary field
when present. Greenhouse's boards API and SmartRecruiters publish no salary.
Workable's widget API publishes no description, so Workable jobs match on
title only. Jibe boards are keyword-narrowed server-side (`servicenow`,
`forward deployed`) because unfiltered boards are enormous.

Two board-level special cases (both live in `companies.json`, neither touches
the matcher in `match.py`):
- **Ashby location fix:** the API returns `location` + a postal address,
  not `locationName` — the old field name silently yielded 'Not specified'
  for every Ashby job, so Ashby roles only matched when the title itself
  named a city. Secondary locations are excluded so a multi-office posting
  (Toronto + London) isn't killed by the matcher's blocked-location check.
- **`title_only` boards:** `"title_only": true` blanks descriptions so only
  title matches pass. Used for the vendor's own board (ServiceNow on
  SmartRecruiters) — its descriptions are saturated with the brand, which
  defeats description matching (a full crawl returned 141 matches, mostly
  marketing/strategy roles). Title-only yields its genuine FD + ServiceNow
  roles. Also skips SmartRecruiters detail fetches, so the board is cheap.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in DISCORD_WEBHOOK_URL + free API keys
python run.py --dry-run --limit 5   # test without touching jobs.db
python run.py                        # full run
```

Workday sweep (needs a residential IP):

```bash
python workday_sweep.py                  # priority + next rotation slice (cron default)
python workday_sweep.py --priority-only  # just the 23 priority boards
python workday_sweep.py --rotation-only  # just the next rotation slice
python workday_sweep.py --all            # all 204 boards (slow — manual use)
```

Board health audit (2,248 ATS boards — takes a few minutes):

```bash
python scripts/audit_boards.py           # summary of dead boards
python scripts/audit_boards.py --fix     # drop dead boards (keeps companies.json.bak)
```

## Indeed source (jobspy) + GitHub Actions

The primary source is Indeed via `python-jobspy`
(`crawler/sources/jobspy_indeed.py`) — free, no API key, `site_name=["indeed"]`
**only** (LinkedIn is banned by absolute user rule; a test pins this).
Five ServiceNow-family queries, national US search, `hours_old=12`
(6h sweeps → 12h window so one failed run leaves no blind gap),
`is_remote=False` (on-site/hybrid only). Queries are retried with backoff —
jobspy itself has no retries. If Indeed changes their API and jobspy breaks,
pin the version in `requirements.txt` and check the Indeed RSS fallback
(see `research-2026-10-16.md`).

### Source toggles (`crawler/config.py`)

Env flags, documented in `.env.example`. Defaults:

| Flag | Default | Meaning |
|---|---|---|
| `SOURCE_INDEED_JOBSPY` | 1 | Indeed via jobspy — primary source |
| `SOURCE_ATS_BOARDS` | 0 | ATS career boards (`companies.json`) — kept, off |
| `SOURCE_WORKDAY` | 0 | Workday sweep — kept, off (also datacenter-blocked) |
| `SOURCE_FREE_APIS` | 1 | Adzuna/USAJobs/Jobicy (key-gated, skip silently) |

### GitHub Actions

`.github/workflows/sweep.yml` runs `python run.py` every 6 hours
(`0 */6 * * *`, 4x daily) plus a manual trigger. One-time setup:

1. Create the repo, push this code.
2. Repo Settings → Secrets → Actions: add `DISCORD_WEBHOOK_URL`
   (required), `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` (optional, free).
3. Watch the first runs: confirm Indeed returns results from the runner
   (no 403/429 in the log) and Discord alerts arrive.

`jobs.db` is committed back at the end of each run (`git add -f`, it's
gitignored locally) so scheduled runs don't re-alert on the same jobs.
Actions free tier is 2,000 min/month; a 3–5 min sweep × 4/day ≈ 360–600.

## Project layout

```
crawler/
  boards.py    Greenhouse / Lever / Ashby / SmartRecruiters / Workable / Jibe crawlers
  sources/jobspy_indeed.py  Indeed via jobspy — primary source (free, no key)
  config.py    per-source enable/disable flags (ats/workday default OFF)
  workday.py   Workday crawler — LOCAL ONLY, see module docstring
  freeapis.py  Jobicy (keyless), Adzuna, USAJobs
  match.py     Matcher v9: relevance → location → remote → government → freshness + fit ranking
  store.py     SQLite dedupe (URL hash + canonical key) + run history + enrichment
  notify.py    Discord webhook alerts (attaches email format when known, salary when published, fit score)
  hiring.py    Company email patterns + address construction
run.py                 ATS sweep entry point (skips Workday by design)
workday_sweep.py       Workday sweep: priority boards + rotation
scripts/audit_boards.py  board health checker
companies.json         2,248 ATS boards (greenhouse/lever/ashby/smartrecruiters/workable/jibe)
workday_boards.json    205 Workday boards ("priority": true = always swept)
tests/                 test_match.py, test_hiring.py, test_sweep.py, test_freeapis.py, test_boards_new.py, test_retarget.py
```

## The matcher

`crawler/match.py` — the whole rule set in one file, every tunable in a
CAPITALIZED list at the top. Pipeline (v9):

1. **relevance** — ServiceNow-family term in title, or STRONG description
   evidence (ServiceNow role noun / platform / module / product mention /
   sentence with a strong platform verb adjacent to the mention). Bare
   experience/familiarity wordings, nice-to-have clauses, end-user usage
   ("raise ServiceNow requests"), and "ServiceNow or equivalent" do NOT
   match. ServiceNow-product term ("Now Assist", "AI Control Tower") in
   title or description, or Forward Deployed (title auto-matches;
   description needs a role phrase)
2. **location** — US or Canada (GTA flagged, not filtered)
3. **remote** — remote-only postings rejected (on-site/hybrid only)
4. **government** — US federal/clearance rejected; Canadian passes
5. **freshness** — posted within 30 days (`MAX_AGE_DAYS`); unparseable dates
   pass optimistically rather than dropping the job
6. **fit** — `fit_score` 0–100 ranks matches for the senior AI-heavy
   profile (senior titles + AI/GRC/ITOM/SAM-HAM/integrations/SPM/upgrades
   clusters); ranking never filters

Date parsing handles epoch millis (Lever), ISO 8601, date-only strings, and
Workday relative dates ("Posted 4 Days Ago"). 178 regression tests pin the
behavior (`python tests/test_match.py`, `test_hiring.py`, `test_sweep.py`,
`test_freeapis.py`, `test_boards_new.py`, `test_retarget.py`).

## Adding a board

ATS:

1. Add `{"company": "...", "platform": "greenhouse|lever|ashby|smartrecruiters|workable|jibe", "board": "..."}`
   to `companies.json`. Platform slugs: SmartRecruiters is case-sensitive
   (`ServiceNow`, not `servicenow`); Jibe is the `{slug}.jibeapply.com`
   subdomain.
2. Verify the slug is alive: `python scripts/audit_boards.py --verbose`
   (or just crawl it directly):

```python
from crawler.boards import crawl_company
from crawler.match import job_matches
jobs, err = crawl_company({"company": "Acme", "platform": "lever", "board": "acme"})
print(err or f"{len(jobs)} jobs")
for j in jobs:
    ok, reason = job_matches(j)
    if ok: print("MATCH:", j["title"], j["location"])
```

Workday: find the tenant's `*.myworkdayjobs.com` domain and site name (the
careers-site URL usually reveals both), add
`{"company": "...", "board": "domain|site"}` to `workday_boards.json`, and
set `"priority": true` if it should run every sweep instead of rotating.

## Hiring-manager emails

`crawler/hiring.py` keeps a persistent cache (`email_patterns.json`) of
company email domains → address patterns, with optional Hunter.io Domain
Search lookup (`HUNTER_API_KEY`, 25 free/month, one lookup per company,
cached forever). Discord alerts include the company's email format when
known, so a researched name becomes an address in one step:

```python
from crawler.hiring import build_email
build_email('Taylor', 'Manfredi', 'snhu.edu')  # 't.manfredi@snhu.edu'
```

Identifying the hiring manager stays a manual research step (LinkedIn) —
auto-guessing a person per alert would attach wrong names to jobs.
Seed a verified pattern with `seed_pattern('domain.com', '{f}.{last}')`.

## Secrets

`.env` is gitignored and never leaves this machine. See `.env.example`:

- `DISCORD_WEBHOOK_URL` (required)
- `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` (optional — free at adzuna.com)
- `USAJOBS_API_KEY` / `USAJOBS_EMAIL` (optional — US federal feed)
- `HUNTER_API_KEY` (optional — email pattern lookup)
