"""Indeed job source via python-jobspy (site_name=["indeed"] ONLY).

Free, no API key. Indeed's scraper uses their GraphQL API rather than HTML
scraping, which is why it's the primary source. jobspy has no built-in
retries (single ~15s timeout per request), so each query is retried here
with backoff.

NEVER add "linkedin" to SITE_NAME — absolute user rule (no LinkedIn in any
form). Glassdoor/ZipRecruiter are blocked upstream anyway.

One scrape_jobs call per query in QUERIES. hours_old=12: with 6-hour
sweeps, a 12h window means a single failed run never leaves a blind gap.
is_remote=False drops remote-only postings but keeps on-site + hybrid
(jobspy >= 1.3 fixed Indeed hybrid misclassification).

Geography: national US search. His states of interest (VA, DC, NY, LA,
TX, MI, NJ) are a RANKING preference, not a filter — anywhere US is
acceptable, and state-restricted queries would just multiply requests.
"""
import time

# Absolute rule — pinned by tests/test_jobspy_indeed.py. Do not add boards.
SITE_NAME = ['indeed']

QUERIES = [
    'ServiceNow developer',
    'ServiceNow administrator',
    'ServiceNow architect',
    'ServiceNow consultant',
    'ServiceNow business analyst',
]

PLATFORM = 'indeed-jobspy'
RESULTS_WANTED = 100
HOURS_OLD = 12
RETRIES = 3
RETRY_BACKOFF_S = 20
SLEEP_BETWEEN_QUERIES_S = 5


def _row_to_job(row):
    """Normalize one jobspy result row to the matcher job dict.

    row is a pandas Series in production; anything with .get() works
    (tests pass plain dicts). date_posted comes back 'YYYY-MM-DD', which
    match.parse_posted_date handles.
    """
    return {
        'company': row.get('company') or 'Unknown',
        'platform': PLATFORM,
        'title': row.get('title') or '',
        'location': row.get('location') or 'Not specified',
        'url': row.get('job_url'),
        'date_posted': row.get('date_posted'),
        'description': row.get('description') or '',
    }


def fetch_indeed_jobs(hours_old=HOURS_OLD):
    """Scrape Indeed via jobspy. Returns (jobs, errors).

    Never raises: per-source isolation. Each query is retried RETRIES
    times with backoff before being recorded as an error.
    """
    try:
        import jobspy
    except ImportError:
        return [], ['python-jobspy is not installed (pip install -r requirements.txt)']
    jobs, errors = [], []
    for qi, query in enumerate(QUERIES):
        df = None
        last_err = None
        for _ in range(RETRIES):
            try:
                df = jobspy.scrape_jobs(
                    site_name=SITE_NAME,  # Indeed ONLY — never linkedin
                    search_term=query,
                    location='United States',
                    country_indeed='usa',
                    results_wanted=RESULTS_WANTED,
                    hours_old=hours_old,
                    is_remote=False,
                    verbose=0,
                )
                break
            except Exception as e:  # noqa: BLE001 — network flakiness, keep sweeping
                last_err = str(e)[:160]
                time.sleep(RETRY_BACKOFF_S)
        if df is None:
            errors.append(f'{query}: {last_err or "unknown error"}')
            continue
        for _, row in df.iterrows():
            jobs.append(_row_to_job(row))
        if qi < len(QUERIES) - 1:
            time.sleep(SLEEP_BETWEEN_QUERIES_S)
    return jobs, errors
