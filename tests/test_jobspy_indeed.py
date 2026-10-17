"""Tests for crawler/sources/jobspy_indeed.py (no network).
Run: python3 tests/test_jobspy_indeed.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from crawler.sources import jobspy_indeed as ji

passed = failed = 0


def check(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print(f'FAIL [{name}]: got {got!r}, want {want!r}')


# Absolute user rule: Indeed ONLY. If anyone adds another board here
# (linkedin is banned outright), this fails loudly.
check('site_name is indeed-only', ji.SITE_NAME, ['indeed'])
check('no linkedin in site_name', 'linkedin' not in ji.SITE_NAME, True)

# Row normalization -> matcher job-dict shape.
row = {
    'title': 'ServiceNow Developer',
    'company': 'Acme Health',
    'location': 'Herndon, VA, USA',
    'job_url': 'https://www.indeed.com/viewjob?jk=abc123',
    'date_posted': '2026-10-17',
    'description': 'We need a ServiceNow developer to administer the platform.',
}
job = ji._row_to_job(row)
check('company', job['company'], 'Acme Health')
check('platform', job['platform'], 'indeed-jobspy')
check('title', job['title'], 'ServiceNow Developer')
check('location', job['location'], 'Herndon, VA, USA')
check('url', job['url'], 'https://www.indeed.com/viewjob?jk=abc123')
check('date_posted', job['date_posted'], '2026-10-17')
check('description kept', job['description'].startswith('We need'), True)

# Missing fields degrade to matcher-safe defaults, never crash.
job2 = ji._row_to_job({})
check('missing company', job2['company'], 'Unknown')
check('missing title', job2['title'], '')
check('missing location', job2['location'], 'Not specified')
check('missing url', job2['url'], None)
check('missing description', job2['description'], '')

# Query pack covers the ServiceNow-family roles; national search (state
# targeting is a ranking preference, not a query filter).
check('queries non-empty', len(ji.QUERIES) >= 4, True)
check('all queries servicenow-family',
      all('servicenow' in q.lower() for q in ji.QUERIES), True)
check('hours_old default', ji.HOURS_OLD, 12)

print(f'{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
