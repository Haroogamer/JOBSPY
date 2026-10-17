"""Free job API clients. All zero-cost. Adzuna + USAJobs need free keys
(env-gated: skipped silently if keys are absent). Jobicy is keyless.
"""
import os

import requests

UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) jobhunter/1.0'}
TIMEOUT = 30


def _norm(company, title, location, url, date_posted, description, platform):
    return {
        'company': company or 'Unknown', 'platform': platform,
        'title': title or '', 'location': location or 'Not specified',
        'url': url, 'date_posted': date_posted,
        'description': description or '',
    }


def fetch_jobicy():
    """Keyless. Remote-only, tag=servicenow actually filters server-side."""
    jobs = []
    try:
        r = requests.get('https://jobicy.com/api/v2/remote-jobs',
                         params={'tag': 'servicenow'}, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        items = data.get('jobs', data) if isinstance(data, dict) else data
        for j in items or []:
            jobs.append(_norm(
                j.get('companyName') or j.get('company'),
                j.get('jobTitle') or j.get('title'),
                j.get('jobGeo') or j.get('location') or 'Remote',
                j.get('url') or j.get('link'),
                j.get('pubDate') or j.get('date'),
                j.get('jobDescription') or j.get('description'),
                'jobicy'))
    except Exception as e:  # noqa: BLE001
        print(f'  ! jobicy: {str(e)[:120]}')
    return jobs


def fetch_adzuna():
    """Free tier: 250/day. Needs ADZUNA_APP_ID + ADZUNA_APP_KEY (free signup).

    Queries both the US and CA endpoints — the user hires in both countries
    and the APIs are per-country.
    """
    app_id = os.environ.get('ADZUNA_APP_ID', '').strip()
    app_key = os.environ.get('ADZUNA_APP_KEY', '').strip()
    if not (app_id and app_key):
        return []
    jobs = []
    for country in ('us', 'ca'):
        try:
            r = requests.get(
                f'https://api.adzuna.com/v1/api/jobs/{country}/search/1',
                params={'app_id': app_id, 'app_key': app_key,
                        'what': 'servicenow', 'results_per_page': 50,
                        'max_days_old': 14, 'sort_by': 'date'},
                headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            for j in r.json().get('results', []):
                loc = (j.get('location') or {}).get('display_name', '')
                jobs.append(_norm(
                    (j.get('company') or {}).get('display_name'),
                    j.get('title'), loc, j.get('redirect_url'),
                    j.get('created'), j.get('description'), 'adzuna'))
        except Exception as e:  # noqa: BLE001
            print(f'  ! adzuna-{country}: {str(e)[:120]}')
    return jobs


def fetch_usajobs():
    """Federal roles. Needs USAJOBS_API_KEY (free) + USAJOBS_EMAIL."""
    key = os.environ.get('USAJOBS_API_KEY', '').strip()
    email = os.environ.get('USAJOBS_EMAIL', '').strip()
    if not (key and email):
        return []
    jobs = []
    try:
        r = requests.get(
            'https://data.usajobs.gov/api/search',
            params={'Keyword': 'ServiceNow', 'ResultsPerPage': 100},
            headers={**UA, 'Authorization-Key': key,
                     'User-Agent': email, 'Host': 'data.usajobs.gov'},
            timeout=TIMEOUT)
        r.raise_for_status()
        items = r.json().get('SearchResult', {}).get('SearchResultItems', [])
        for it in items:
            d = it.get('MatchedObjectDescriptor', {})
            pos = d.get('PositionLocationDisplay', '')
            jobs.append(_norm(
                d.get('OrganizationName'), d.get('PositionTitle'), pos,
                d.get('PositionURI'), d.get('PublicationStartDate'),
                d.get('UserArea', {}).get('Details', {}).get('JobSummary'),
                'usajobs'))
    except Exception as e:  # noqa: BLE001
        print(f'  ! usajobs: {str(e)[:120]}')
    return jobs


def fetch_all():
    jobs = []
    for fn in (fetch_jobicy, fetch_adzuna, fetch_usajobs):
        jobs.extend(fn())
    print(f'  free APIs returned {len(jobs)} jobs')
    return jobs
