"""ATS board crawlers that work from anywhere (including GitHub Actions).

Each crawler takes a board identifier and returns a list of normalized job dicts:
    {company, platform, title, location, url, date_posted, description,
     salary_min, salary_max, salary_currency, salary_text, workplace_type}

Salary / workplace fields are best-effort: populated only when the platform's
public API exposes them (Ashby compensation, Lever salaryRange, Jibe salary
bounds). Greenhouse's boards API and SmartRecruiters expose no salary;
Workable's widget API exposes no description (title-only matching).

Workday is NOT here — it lives in crawler/workday.py because Workday blocks
datacenter IPs. See that module for details.
"""
import html
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests

UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) jobhunter/1.0'}
TIMEOUT = 25
MAX_TRIES = 3


def _get(url, params=None):
    """GET with retry/backoff for transient failures (429 / 5xx / connection
    errors). Raises on the final attempt so the caller can record the board
    as errored instead of silently dropping it."""
    last = None
    for attempt in range(MAX_TRIES):
        try:
            r = requests.get(url, headers=UA, params=params, timeout=TIMEOUT)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f'HTTP {r.status_code}')
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 - retried below
            last = e
            if attempt < MAX_TRIES - 1:
                time.sleep((2 ** attempt) + random.uniform(0, 1))
    raise last


def _strip_html(s):
    if not isinstance(s, str):
        return ''
    s = re.sub(r'<[^>]*>', ' ', s)
    s = html.unescape(s)
    return re.sub(r'\s+', ' ', s).strip()


def _salary_text(mn, mx, cur):
    """Human-readable salary, or None when nothing is known."""
    if mn is None and mx is None:
        return None
    fmt = lambda v: f'{v:,.0f}' if isinstance(v, (int, float)) else str(v)  # noqa: E731
    if mn is not None and mx is not None and mn != mx:
        s = f'{fmt(mn)}-{fmt(mx)}'
    else:
        s = fmt(mn if mn is not None else mx)
    return f'{s} {cur}'.strip() if cur else s


def _clean_num(v):
    """Salary bounds: ints/floats pass through; 0 / '' / None -> None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and v:
        return v
    try:
        f = float(v)
        return f if f else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Greenhouse — boards-api.greenhouse.io, free public JSON API.
# No salary / workplace fields in this API.
# ---------------------------------------------------------------------------
def crawl_greenhouse(company, board_token, title_only=False):
    """boards-api.greenhouse.io — free public JSON API."""
    data = _get(f'https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs',
                params={'content': 'true'})
    jobs = []
    for j in data.get('jobs', []):
        loc = j.get('location', {}).get('name', '')
        offices = '; '.join(o.get('name', '') for o in j.get('offices', []) if o.get('name'))
        location = '; '.join(x for x in [loc, offices] if x) or 'Not specified'
        jobs.append({
            'company': company, 'platform': 'greenhouse',
            'title': j.get('title', ''), 'location': location,
            'url': j.get('absolute_url') or f'https://boards.greenhouse.io/{board_token}/jobs/{j["id"]}',
            'date_posted': j.get('first_published') or j.get('updated_at'),
            'description': _strip_html(j.get('content')),
            'salary_min': None, 'salary_max': None, 'salary_currency': None,
            'salary_text': None, 'workplace_type': None,
        })
    return jobs


# ---------------------------------------------------------------------------
# Lever — api.lever.co, free public JSON API.
# salaryRange + workplaceType parsed when the board publishes them.
# ---------------------------------------------------------------------------
def crawl_lever(company, slug, title_only=False):
    """api.lever.co — free public JSON API."""
    data = _get(f'https://api.lever.co/v0/postings/{slug}', params={'mode': 'json'})
    jobs = []
    for j in data:
        cats = j.get('categories', {})
        location = cats.get('location') or j.get('workplaceType') or 'Not specified'
        desc = _strip_html(j.get('description') or j.get('content'))
        lists = ' '.join(_strip_html(x.get('content', '')) for x in j.get('lists', []))
        sr = j.get('salaryRange') or {}
        mn, mx = _clean_num(sr.get('min')), _clean_num(sr.get('max'))
        jobs.append({
            'company': company, 'platform': 'lever',
            'title': j.get('text', ''), 'location': location,
            'url': j.get('hostedUrl'),
            'date_posted': j.get('createdAt'),
            'description': f'{desc} {lists}'.strip(),
            'salary_min': mn, 'salary_max': mx,
            'salary_currency': sr.get('currency'),
            'salary_text': _salary_text(mn, mx, sr.get('currency')),
            'workplace_type': j.get('workplaceType'),
        })
    return jobs


# ---------------------------------------------------------------------------
# Ashby — api.ashbyhq.com posting API, free public JSON API.
# Location: the API returns `location` + a postal address + secondary
# locations — NOT `locationName` (the old field name silently yielded
# 'Not specified' for every Ashby job, so Ashby roles only matched when
# the title itself named a city). includeCompensation=true exposes the
# compensation tiers when the board publishes them.
# ---------------------------------------------------------------------------
def _ashby_location(j):
    # Primary location + postal address only. Secondary locations are
    # deliberately EXCLUDED: a posting mirrored across offices (e.g. Toronto
    # + London) would otherwise trip the matcher's blocked-location check
    # on the non-US/CA office and the whole role would be rejected, even
    # though the US/CA posting is one Haris could take.
    parts = []
    loc = (j.get('location') or '').strip()
    if loc:
        parts.append(loc)
    addr = ((j.get('address') or {}).get('postalAddress') or {})
    for k in ('addressLocality', 'addressRegion', 'addressCountry'):
        v = (addr.get(k) or '').strip()
        if v and v not in parts:
            parts.append(v)
    return '; '.join(parts) or 'Not specified'


def _ashby_compensation(j):
    comp = j.get('compensation') or {}
    summary = comp.get('compensationTierSummary')
    if isinstance(summary, str) and summary.strip():
        return None, None, None, summary.strip()
    if isinstance(summary, dict):
        mn = _clean_num(summary.get('min') or summary.get('minValue'))
        mx = _clean_num(summary.get('max') or summary.get('maxValue'))
        cur = summary.get('currency') or summary.get('currencyCode')
        if mn is not None or mx is not None:
            return mn, mx, cur, _salary_text(mn, mx, cur)
    for tier in comp.get('compensationTiers') or []:
        if not isinstance(tier, dict):
            continue
        mn = _clean_num(tier.get('min') or tier.get('minValue'))
        mx = _clean_num(tier.get('max') or tier.get('maxValue'))
        cur = tier.get('currency') or tier.get('currencyCode')
        if mn is not None or mx is not None:
            return mn, mx, cur, _salary_text(mn, mx, cur)
    return None, None, None, None


def crawl_ashby(company, org_slug, title_only=False):
    """api.ashbyhq.com posting API — free public JSON API."""
    data = _get(f'https://api.ashbyhq.com/posting-api/job-board/{org_slug}',
                params={'includeCompensation': 'true'})
    jobs = []
    for j in data.get('jobs', []):
        mn, mx, cur, text = _ashby_compensation(j)
        jobs.append({
            'company': company, 'platform': 'ashby',
            'title': j.get('title', ''), 'location': _ashby_location(j),
            'url': j.get('jobUrl'),
            'date_posted': j.get('publishedAt'),
            'description': _strip_html(j.get('descriptionPlain') or j.get('description')),
            'salary_min': mn, 'salary_max': mx, 'salary_currency': cur,
            'salary_text': text, 'workplace_type': j.get('workplaceType'),
        })
    return jobs


# ---------------------------------------------------------------------------
# SmartRecruiters — api.smartrecruiters.com, free public JSON API.
# The list endpoint returns NO description, so each posting's detail
# endpoint is fetched (in parallel) for the description. No salary data.
# Slugs are case-sensitive (e.g. 'ServiceNow', not 'servicenow').
# ---------------------------------------------------------------------------
def _sr_detail(company, slug, item):
    pid = item.get('id')
    try:
        d = _get(f'https://api.smartrecruiters.com/v1/companies/{slug}/postings/{pid}')
    except Exception:
        d = item  # fall back to list-level data, title-only match
    sections = ((d.get('jobAd') or {}).get('sections') or {})
    # Section values are {'title': ..., 'text': '<html>'} dicts (or plain
    # strings on older postings) — extract the text either way.
    desc_parts = []
    for k in ('jobDescription', 'qualifications'):
        v = sections.get(k) or ''
        if isinstance(v, dict):
            v = v.get('text') or v.get('content') or ''
        desc_parts.append(_strip_html(v))
    desc = ' '.join(p for p in desc_parts if p)
    loc = d.get('location') or item.get('location') or {}
    location = (loc.get('fullLocation') or '').strip()
    if not location:
        location = ', '.join(x for x in [loc.get('city'), loc.get('country')] if x) or 'Not specified'
    wt = None
    if loc.get('remote'):
        wt = 'Remote'
    elif loc.get('hybrid'):
        wt = 'Hybrid'
    return {
        'company': company, 'platform': 'smartrecruiters',
        'title': d.get('name') or item.get('name') or '',
        'location': location,
        'url': d.get('postingUrl') or f'https://jobs.smartrecruiters.com/{slug}/{pid}',
        'date_posted': d.get('releasedDate') or item.get('releasedDate'),
        'description': desc.strip(),
        'salary_min': None, 'salary_max': None, 'salary_currency': None,
        'salary_text': None, 'workplace_type': wt,
    }


def crawl_smartrecruiters(company, slug, title_only=False):
    """api.smartrecruiters.com — free public JSON API, paged list + details.

    title_only (used for the vendor's own board): skip detail fetches and
    return list-level jobs with blank descriptions, so only title matches
    pass. ServiceNow's own descriptions are saturated with the brand
    ("every role uses ServiceNow"), which defeats description matching.
    """
    items, offset, total = [], 0, None
    while total is None or offset < total:
        data = _get(f'https://api.smartrecruiters.com/v1/companies/{slug}/postings',
                    params={'limit': 100, 'offset': offset})
        batch = data.get('content', [])
        if not batch:
            break
        items.extend(batch)
        total = data.get('totalFound', len(batch))
        offset += len(batch)
        if offset >= 10000:  # safety cap
            break
    seen, uniq = set(), []
    for it in items:
        if it.get('id') and it['id'] not in seen:
            seen.add(it['id'])
            uniq.append(it)
    if title_only:
        jobs = []
        for it in uniq:
            loc = it.get('location') or {}
            location = (loc.get('fullLocation') or '').strip()
            if not location:
                location = ', '.join(x for x in [loc.get('city'), loc.get('country')] if x) or 'Not specified'
            jobs.append({
                'company': company, 'platform': 'smartrecruiters',
                'title': it.get('name') or '',
                'location': location,
                'url': f'https://jobs.smartrecruiters.com/{slug}/{it.get("id")}',
                'date_posted': it.get('releasedDate'),
                'description': '',
                'salary_min': None, 'salary_max': None, 'salary_currency': None,
                'salary_text': None,
                'workplace_type': 'Remote' if loc.get('remote') else ('Hybrid' if loc.get('hybrid') else None),
            })
        return jobs
    with ThreadPoolExecutor(max_workers=6) as ex:
        jobs = list(ex.map(lambda it: _sr_detail(company, slug, it), uniq))
    return jobs


# ---------------------------------------------------------------------------
# Workable — apply.workable.com widget API, free public JSON, no auth.
# The widget list exposes NO description, so jobs match on title only.
# No salary data.
# ---------------------------------------------------------------------------
def crawl_workable(company, slug, title_only=False):
    """apply.workable.com/api/v1/widget/accounts/{slug} — free public JSON."""
    data = _get(f'https://apply.workable.com/api/v1/widget/accounts/{slug}')
    jobs = []
    for j in data.get('jobs', []):
        locs = []
        for l in j.get('locations') or []:
            loc = ', '.join(x for x in [l.get('city'), l.get('country')] if x)
            if loc:
                locs.append(loc)
        if not locs:
            loc = ', '.join(x for x in [j.get('city'), j.get('country')] if x)
            if loc:
                locs.append(loc)
        jobs.append({
            'company': company, 'platform': 'workable',
            'title': j.get('title', ''),
            'location': '; '.join(locs) or 'Not specified',
            'url': j.get('url') or j.get('shortlink'),
            'date_posted': j.get('published_on') or j.get('created_at'),
            'description': '',
            'salary_min': None, 'salary_max': None, 'salary_currency': None,
            'salary_text': None,
            'workplace_type': 'Remote' if j.get('telecommuting') else None,
        })
    return jobs


# ---------------------------------------------------------------------------
# Jibe (iCIMS) — {slug}.jibeapply.com/api/jobs, free public JSON, no auth.
# The unfiltered board is enormous (FedEx: 136k postings), so the API's
# server-side keyword search narrows to ServiceNow / Forward Deployed
# before paging. The matcher still applies on top.
# ---------------------------------------------------------------------------
JIBE_KEYWORDS = ['servicenow', 'forward deployed']


def crawl_jibe(company, slug, title_only=False):
    """{slug}.jibeapply.com/api/jobs — free public JSON, keyword-narrowed."""
    jobs, seen_urls = [], set()
    for kw in JIBE_KEYWORDS:
        page = 1
        while page <= 10:  # safety cap: 1000 results per keyword
            data = _get(f'https://{slug}.jibeapply.com/api/jobs',
                        params={'limit': 100, 'page': page, 'keywords': kw})
            batch = data.get('jobs', [])
            if not batch:
                break
            for item in batch:
                j = item.get('data') or {}
                url = j.get('apply_url')
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                mn = _clean_num(j.get('salary_min_value'))
                mx = _clean_num(j.get('salary_max_value'))
                jobs.append({
                    'company': company, 'platform': 'jibe',
                    'title': j.get('title', ''),
                    'location': (j.get('full_location') or '').strip()
                    or ', '.join(x for x in [j.get('city'), j.get('country')] if x)
                    or 'Not specified',
                    'url': url,
                    'date_posted': j.get('posted_date'),
                    'description': _strip_html(j.get('description')),
                    'salary_min': mn, 'salary_max': mx,
                    'salary_currency': None,
                    'salary_text': _salary_text(mn, mx, None),
                    'workplace_type': j.get('location_type'),
                })
            if len(batch) < 100:
                break
            page += 1
    return jobs


CRAWLERS = {
    'greenhouse': crawl_greenhouse,
    'lever': crawl_lever,
    'ashby': crawl_ashby,
    'smartrecruiters': crawl_smartrecruiters,
    'workable': crawl_workable,
    'jibe': crawl_jibe,
}


def crawl_company(entry, delay=0.2):
    """entry = {company, platform, board}. Returns (jobs, error)."""
    fn = CRAWLERS.get(entry['platform'])
    if not fn:
        return [], f"no crawler for platform {entry['platform']}"
    try:
        jobs = fn(entry['company'], entry['board'],
                  title_only=entry.get('title_only', False))
        if entry.get('title_only'):
            for j in jobs:
                j['description'] = ''
        time.sleep(delay)
        return jobs, None
    except Exception as e:  # noqa: BLE001 - per-board failures must not kill a run
        return [], f'{entry["company"]}: {e}'
