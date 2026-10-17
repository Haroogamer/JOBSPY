"""Workday CXS crawler — LOCAL USE ONLY.

Why this is a separate module: Workday aggressively blocks datacenter IPs.
Every Workday board returns HTTP 400 from GitHub Actions / any cloud runner.
This crawler only works from a residential IP, so it runs on a local machine
(see workday_sweep.py) — never in CI.

Board spec format: "<domain>|<board>"
  e.g. "abbott.wd5.myworkdayjobs.com|abbottcareers"

How it works:
  1. POST to /wday/cxs/<tenant>/<board>/jobs for the listing.
     The listing gives title + location only — no usable description.
  2. For titles that look like plausible matches (cheap pre-filter via
     match.title_might_match), GET the detail endpoint at
     /wday/cxs/<tenant>/<board>/<externalPath> for the full jobDescription.
  3. Jobs whose detail fetch fails fall back to listing-level data rather
     than killing the board.

Rate limiting: Workday throttles aggressive clients. Listing POSTs retry with
backoff on 400/429; detail fetches are paced at ~2/sec; boards are paced
several seconds apart. Do not parallelize Workday requests.
"""
import html
import random
import re
import time

import requests

from .boards import UA, TIMEOUT, _strip_html

# Imported lazily to avoid a hard dependency cycle at module load.
# (match.py doesn't import this module, so a top-level import would also work,
# but lazy keeps the separation explicit.)


def _post_with_retry(url, headers, payload, tries=3):
    """POST with backoff — Workday throttles aggressive clients with 400/429."""
    for i in range(tries):
        r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
        if r.status_code in (400, 429) and i < tries - 1:
            time.sleep(4 * (i + 1) + random.uniform(0, 2))
            continue
        r.raise_for_status()
        return r.json()
    return {}


def crawl_workday(company, board_spec):
    """Crawl one Workday board. Returns a list of normalized job dicts."""
    from .match import title_might_match

    domain, board = board_spec.split('|', 1)
    tenant = domain.split('.')[0]
    base = f'https://{domain}/wday/cxs/{tenant}/{board}'
    headers = {**UA, 'Content-Type': 'application/json', 'Accept': 'application/json'}
    jobs, offset = [], 0
    while True:
        payload = {'searchText': '', 'appliedFacets': {}, 'limit': 50, 'offset': offset}
        data = _post_with_retry(f'{base}/jobs', headers, payload)
        postings = data.get('jobPostings', [])
        if not postings:
            break
        for j in postings:
            title = j.get('title', '')
            ext_path = (j.get('externalPath') or '').lstrip('/')
            url = f'https://{domain}/en-US/{board}/' + ext_path
            location = j.get('locationsText') or 'Not specified'
            description = ''
            date_posted = j.get('postedOn') or j.get('startDate')
            # Only spend a detail request on titles that could plausibly match.
            if title_might_match(title) and ext_path:
                try:
                    dr = requests.get(
                        f'{base}/{ext_path}',
                        headers={**UA, 'Accept': 'application/json'},
                        timeout=TIMEOUT,
                    )
                    dr.raise_for_status()
                    info = dr.json().get('jobPostingInfo', {})
                    description = _strip_html(info.get('jobDescription') or '')
                    location = info.get('location') or location
                    date_posted = info.get('postedOn') or date_posted
                except Exception:
                    pass  # fall back to listing-level data
                time.sleep(0.5)
            jobs.append({
                'company': company, 'platform': 'workday',
                'title': title, 'location': location,
                'url': url,
                'date_posted': date_posted,
                'description': description,
            })
        offset += len(postings)
        if offset >= data.get('total', 0):
            break
        time.sleep(1.0)
    return jobs


def search_workday(company, board_spec, query='servicenow', limit=20,
                   max_results=40, skip_urls=()):
    """Search one Workday board for a query; return matched job dicts.

    Fetches details for EVERY search result before matching: Workday's query
    already narrows to ServiceNow-related postings, but the good ones often
    have generic titles ("Business Systems Analyst") with the ServiceNow
    experience requirement only in the description. Title pre-filtering would
    silently drop those. Used by workday_sweep.py for the periodic local sweep.

    Paging: results are fetched page by page (offset) up to max_results, so
    big boards (Accenture: 1600+ ServiceNow hits) don't hide fresh postings
    past the first page.

    skip_urls: posting URLs the caller has already evaluated (notified or
    checked-and-rejected). Their detail pages are NOT re-fetched — the
    listing already gives us the URL, so skipping costs nothing and saves
    the 2s-per-result detail crawl on repeat sweeps.

    Returns (matched, evaluated_urls, err): matched jobs, every posting URL
    whose detail page was fetched this call (matched or not — the caller
    records rejections so they aren't re-fetched), and an error string.
    """
    from .match import job_matches

    domain, board = board_spec.split('|', 1)
    tenant = domain.split('.')[0]
    base = f'https://{domain}/wday/cxs/{tenant}/{board}'
    headers = {**UA, 'Content-Type': 'application/json', 'Accept': 'application/json'}
    skip = set(skip_urls or ())

    def _search_page(offset):
        for attempt in range(3):
            try:
                r = requests.post(
                    f'{base}/jobs', headers=headers,
                    json={'searchText': query, 'appliedFacets': {},
                          'limit': limit, 'offset': offset},
                    timeout=TIMEOUT,
                )
                if r.status_code in (400, 429):
                    time.sleep(6 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json(), None
            except Exception as e:
                if attempt == 2:
                    return None, f'search failed: {e}'[:120]
                time.sleep(6 * (attempt + 1))
        return None, 'search blocked after retries'

    matched, fetched, err = [], set(), None
    offset = 0
    while offset < max_results:
        data, page_err = _search_page(offset)
        if page_err:
            err = page_err
            break
        postings = data.get('jobPostings', [])
        if not postings:
            break
        for p in postings:
            title = p.get('title', '')
            ext = (p.get('externalPath') or '').lstrip('/')
            if not ext:
                continue
            url = f'https://{domain}/en-US/{board}/{ext}'
            if url in skip or url in fetched:
                continue
            fetched.add(url)
            time.sleep(2)
            try:
                dr = requests.get(f'{base}/{ext}',
                                  headers={**UA, 'Accept': 'application/json'},
                                  timeout=TIMEOUT)
                dr.raise_for_status()
                info = dr.json().get('jobPostingInfo', {})
                job = {
                    'company': company, 'platform': 'workday',
                    'title': title,
                    'location': info.get('location') or p.get('locationsText') or 'Not specified',
                    'description': _strip_html(info.get('jobDescription') or ''),
                    'url': url,
                    'date_posted': info.get('postedOn') or p.get('postedOn'),
                }
                ok, _ = job_matches(job)
                if ok:
                    matched.append(job)
            except Exception:
                pass
        offset += len(postings)
        if offset >= data.get('total', 0):
            break
    return matched, fetched, err
