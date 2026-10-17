"""Tests for the elite-crawler upgrade: new ATS platforms (SmartRecruiters,
Workable, Jibe), the Ashby location fix, salary enrichment, retry/backoff,
canonical cross-source dedup, and matcher false-positive regression.
All HTTP is mocked — no network. Run: python3 tests/test_boards_new.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from crawler import boards
from crawler.match import job_matches
from crawler.store import Store, canonical_key

passed = failed = 0


def check(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print(f'FAIL [{name}]: got {got!r}, want {want!r}')


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f'HTTP {self.status_code}')

    def json(self):
        return self._payload


# --- SmartRecruiters: paged list + parallel detail fetch -------------------
def fake_sr_get(url, params=None, headers=None, timeout=None):
    if 'postings/' in url and not url.endswith('/postings'):
        pid = url.rsplit('/', 1)[-1]
        return FakeResp({
            'id': pid, 'name': 'ServiceNow Developer',
            'postingUrl': f'https://jobs.smartrecruiters.com/ServiceNow/{pid}',
            'releasedDate': '2026-10-10T00:00:00Z',
            'location': {'city': 'Toronto', 'country': 'ca',
                         'fullLocation': 'Toronto, , Canada',
                         'remote': False, 'hybrid': True},
            'jobAd': {'sections': {
                'jobDescription': {'title': 'Job Description',
                                   'text': '<p>We use ServiceNow for ITSM.</p>'},
                'qualifications': {'title': 'Qualifications',
                                   'text': 'ServiceNow experience required.'},
            }},
        })
    offset = (params or {}).get('offset', 0)
    if offset == 0:
        return FakeResp({'totalFound': 2, 'content': [
            {'id': '1', 'name': 'ServiceNow Developer',
             'location': {'fullLocation': 'Toronto, , Canada'}},
            {'id': '2', 'name': 'Sales Rep',
             'location': {'fullLocation': 'Toronto, , Canada'}},
        ]})
    return FakeResp({'totalFound': 2, 'content': []})


boards.requests.get = fake_sr_get
jobs = boards.crawl_smartrecruiters('ServiceNow', 'ServiceNow')
check('SR returns both postings', len(jobs), 2)
check('SR description joins sections',
      jobs[0]['description'],
      'We use ServiceNow for ITSM. ServiceNow experience required.')
check('SR location from fullLocation', jobs[0]['location'], 'Toronto, , Canada')
check('SR workplace hybrid', jobs[0]['workplace_type'], 'Hybrid')
check('SR date from releasedDate', jobs[0]['date_posted'], '2026-10-10T00:00:00Z')
check('SR url from postingUrl', jobs[0]['url'],
      'https://jobs.smartrecruiters.com/ServiceNow/1')
check('SR no salary', jobs[0]['salary_text'], None)

# --- Workable: widget list, title-only (no description) ----------------------
def fake_wk_get(url, params=None, headers=None, timeout=None):
    return FakeResp({'jobs': [{
        'title': 'ServiceNow Developer',
        'url': 'https://apply.workable.com/credence/j/ABC',
        'published_on': '2026-10-09',
        'telecommuting': False,
        'locations': [{'city': 'Austin', 'country': 'United States'}],
    }]})


boards.requests.get = fake_wk_get
jobs = boards.crawl_workable('Credence', 'credence')
check('Workable returns job', len(jobs), 1)
check('Workable location joined', jobs[0]['location'], 'Austin, United States')
check('Workable description empty (title-only)', jobs[0]['description'], '')
check('Workable date', jobs[0]['date_posted'], '2026-10-09')

# --- Jibe: keyword paging, dedup across keywords, salary 0 -> None ----------
def fake_jibe_get(url, params=None, headers=None, timeout=None):
    kw = (params or {}).get('keywords')
    if kw == 'servicenow':
        return FakeResp({'jobs': [{'data': {
            'title': 'ServiceNow Developer',
            'description': '<p>Develop on ServiceNow.</p>',
            'full_location': 'Memphis, Tennessee',
            'apply_url': 'https://fedex.jibeapply.com/jobs/1',
            'posted_date': '2026-10-08T00:00:00+0000',
            'salary_min_value': 0, 'salary_max_value': 0,
            'location_type': 'On-site',
        }}]})
    # 'forward deployed' returns the SAME url (dedup) + one new one
    return FakeResp({'jobs': [
        {'data': {'title': 'ServiceNow Developer',
                  'description': '<p>Develop on ServiceNow.</p>',
                  'full_location': 'Memphis, Tennessee',
                  'apply_url': 'https://fedex.jibeapply.com/jobs/1',
                  'posted_date': '2026-10-08T00:00:00+0000',
                  'salary_min_value': 90000, 'salary_max_value': 120000,
                  'location_type': 'On-site'}},
        {'data': {'title': 'Forward Deployed Engineer',
                  'description': 'Forward deployed role.',
                  'full_location': 'Seattle, Washington',
                  'apply_url': 'https://fedex.jibeapply.com/jobs/2',
                  'posted_date': '2026-10-09T00:00:00+0000',
                  'salary_min_value': 150000, 'salary_max_value': 180000,
                  'location_type': 'Hybrid'}},
    ]})


boards.requests.get = fake_jibe_get
jobs = boards.crawl_jibe('FedEx', 'fedex')
check('Jibe dedupes across keywords', len(jobs), 2)
check('Jibe strips HTML', jobs[0]['description'], 'Develop on ServiceNow.')
check('Jibe salary 0 -> None', jobs[0]['salary_min'], None)
check('Jibe salary parsed', jobs[1]['salary_min'], 150000)
check('Jibe salary text', jobs[1]['salary_text'], '150,000-180,000')
check('Jibe workplace', jobs[1]['workplace_type'], 'Hybrid')

# --- Ashby: location from `location` + address + secondary; compensation ---
def fake_ashby_get(url, params=None, headers=None, timeout=None):
    check('Ashby requests compensation', (params or {}).get('includeCompensation'), 'true')
    return FakeResp({'jobs': [{
        'title': 'ServiceNow Developer',
        'location': 'Remote',
        'address': {'postalAddress': {'addressLocality': 'Toronto',
                                      'addressRegion': 'Ontario',
                                      'addressCountry': 'Canada'}},
        'secondaryLocations': [{'location': 'Ottawa', 'address': None}],
        'jobUrl': 'https://jobs.ashbyhq.com/co/123',
        'publishedAt': '2026-10-10T00:00:00Z',
        'descriptionPlain': 'ServiceNow work.',
        'workplaceType': 'Hybrid',
        'compensation': {'compensationTierSummary': None,
                         'compensationTiers': [
                             {'min': 100000, 'max': 130000,
                              'currency': 'CAD', 'interval': 'per-year'}],
                         'summaryComponents': []},
    }]})


boards.requests.get = fake_ashby_get
jobs = boards.crawl_ashby('Co', 'co')
check('Ashby location combines fields', jobs[0]['location'],
      'Remote; Toronto; Ontario; Canada')
check('Ashby salary from tiers', jobs[0]['salary_min'], 100000)
check('Ashby salary text', jobs[0]['salary_text'], '100,000-130,000 CAD')
check('Ashby workplace', jobs[0]['workplace_type'], 'Hybrid')
check('Ashby drops secondary locations (blocked-marker safety)',
      'Ottawa' not in jobs[0]['location'], True)

# --- Lever: salaryRange + workplaceType -------------------------------------
def fake_lever_get(url, params=None, headers=None, timeout=None):
    return FakeResp([{
        'text': 'ServiceNow Developer',
        'categories': {'location': 'Toronto'},
        'workplaceType': 'hybrid',
        'hostedUrl': 'https://jobs.lever.co/co/1',
        'createdAt': 1760000000000,
        'description': 'ServiceNow work.',
        'lists': [],
        'salaryRange': {'min': 120000, 'max': 140000, 'currency': 'CAD'},
    }])


boards.requests.get = fake_lever_get
jobs = boards.crawl_lever('Co', 'co')
check('Lever salary parsed', (jobs[0]['salary_min'], jobs[0]['salary_max']),
      (120000, 140000))
check('Lever salary text', jobs[0]['salary_text'], '120,000-140,000 CAD')
check('Lever workplace', jobs[0]['workplace_type'], 'hybrid')

# --- title_only: vendor board skips SR detail fetches ---------------------
detail_calls = []


def fake_sr_titleonly_get(url, params=None, headers=None, timeout=None):
    if '/postings/' in url and not url.endswith('/postings'):
        detail_calls.append(url)
        return FakeResp({})
    return FakeResp({'totalFound': 1, 'content': [
        {'id': '9', 'name': 'ServiceNow Developer',
         'location': {'fullLocation': 'Toronto, , Canada'},
         'releasedDate': '2026-10-11T00:00:00Z'},
    ]})


boards.requests.get = fake_sr_titleonly_get
jobs = boards.crawl_smartrecruiters('ServiceNow', 'ServiceNow', title_only=True)
check('title_only skips detail fetches', detail_calls, [])
check('title_only returns list-level job', len(jobs), 1)
check('title_only blanks description', jobs[0]['description'], '')
check('title_only keeps title', jobs[0]['title'], 'ServiceNow Developer')

# crawl_company passes title_only through and blanks descriptions
boards.requests.get = fake_sr_get  # full SR mock from above (list + detail)
jobs, err = boards.crawl_company({'company': 'ServiceNow',
                                  'platform': 'smartrecruiters',
                                  'board': 'ServiceNow', 'title_only': True},
                                 delay=0)
check('crawl_company title_only no error', err, None)
check('crawl_company title_only blanks all descriptions',
      all(j['description'] == '' for j in jobs), True)
tries = []


def fake_retry_get(url, params=None, headers=None, timeout=None):
    tries.append(url)
    if len(tries) < 3:
        return FakeResp({}, status=429)
    return FakeResp({'jobs': []})


boards.requests.get = fake_retry_get
boards.time.sleep = lambda s: None  # don't wait in tests
data = boards._get('https://example.com/x')
check('retry succeeds after 429s', data, {'jobs': []})
check('retry made 3 attempts', len(tries), 3)

# --- Canonical key normalization ---------------------------------------------
check('canonical strips req-id parens',
      canonical_key({'company': 'Acme Inc', 'title': 'ServiceNow Developer (10566)',
                     'location': 'Toronto, Ontario'}),
      canonical_key({'company': 'Acme', 'title': 'ServiceNow Developer',
                     'location': 'Toronto, ON'}))
check('canonical keeps location parens',
      canonical_key({'company': 'Acme', 'title': 'Forward Deployed Engineer (Ohio)',
                     'location': 'Columbus, OH'}),
      'acme|forward deployed engineer ohio|columbus')
check('canonical city skips Hybrid segment',
      canonical_key({'company': 'Acme', 'title': 'ServiceNow Developer',
                     'location': 'Hybrid; New York, NY'}),
      'acme|servicenow developer|new york')

# --- Store: cross-platform dedup + enrichment persistence --------------------
store = Store(':memory:')
base = {'company': 'Acme Corp', 'title': 'ServiceNow Developer',
        'location': 'Toronto, ON', 'url': 'https://jobs.lever.co/acme/1',
        'date_posted': '2026-10-10', 'date_discovered': '2026-10-12',
        'platform': 'lever', 'salary_min': 100000, 'salary_max': 130000,
        'salary_currency': 'CAD', 'salary_text': '100,000-130,000 CAD',
        'workplace_type': 'Hybrid'}
check('store adds new job', store.add(base, source='ats-board'), True)
mirror = dict(base, platform='workday',
              url='https://acme.wd1.myworkdayjobs.com/en-US/x/job/1')
check('store suppresses cross-platform mirror', store.add(mirror, source='workday'), False)
distinct = dict(base, url='https://jobs.lever.co/acme/2')
check('store keeps distinct req on same board', store.add(distinct, source='ats-board'), True)
row = store.db.execute(
    'SELECT salary_min, salary_text, workplace_type, canonical_key FROM jobs'
    ' WHERE url=?', (base['url'],)).fetchone()
check('store persists enrichment',
      (row[0], row[1], row[2]), (100000, '100,000-130,000 CAD', 'Hybrid'))
check('store backfills canonical key', bool(row[3]), True)
check('canonical_exists excludes same platform',
      store.canonical_exists(canonical_key(base), exclude_platform='lever'), False)
check('canonical_exists finds other platform',
      store.canonical_exists(canonical_key(base), exclude_platform='workday'), True)

# --- Workday sweep: cross-source dedup via jobs.db ---------------------------
import json as _json  # noqa: E402
import tempfile as _tempfile  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
import workday_sweep as _sweep  # noqa: E402

_tmpdir = _Path(_tempfile.mkdtemp())
_sweep.HERE = _tmpdir
_sweep.SEEN_FILE = _tmpdir / 'seen.json'
_sweep.CHECKED_FILE = _tmpdir / 'checked.json'
_sweep.ROTATION_FILE = _tmpdir / 'rotation.json'
_sweep.BOARDS_FILE = _tmpdir / 'boards.json'
_sweep.LOG_FILE = _tmpdir / 'sweep.log'
_sweep.BOARDS_FILE.write_text(_json.dumps([
    {'company': 'Acme', 'board': 'acme.wd1.myworkdayjobs.com|acme', 'priority': True},
]))
_sweep.SEEN_FILE.write_text('{}')
_sweep.CHECKED_FILE.write_text('{}')
_sweep.ROTATION_FILE.write_text('{}')

# jobs.db already holds this role from the ATS sweep (Lever).
_pre = Store(str(_tmpdir / 'jobs.db'))
_pre.add({'company': 'Acme', 'title': 'ServiceNow Developer',
          'location': 'Toronto, ON', 'url': 'https://jobs.lever.co/acme/1',
          'date_posted': '2026-10-12', 'date_discovered': '2026-10-12',
          'platform': 'lever'}, source='ats-board')
_pre.commit()
_pre.close()

_notified = []
_sweep.notify = lambda job: (_notified.append(job['title']), (True, 'sent'))[1]


def _fake_search(company, spec, query, max_results, skip_urls):
    mirror = {'company': 'Acme', 'title': 'ServiceNow Developer',
              'location': 'Toronto, Ontario',
              'url': 'https://acme.wd1.myworkdayjobs.com/en-US/acme/job/1',
              'date_posted': '2026-10-12', 'description': 'ServiceNow work.',
              'platform': 'workday'}
    fresh = {'company': 'Acme', 'title': 'Forward Deployed Engineer',
             'location': 'Toronto, Ontario',
             'url': 'https://acme.wd1.myworkdayjobs.com/en-US/acme/job/2',
             'date_posted': '2026-10-12', 'description': 'FD role.',
             'platform': 'workday'}
    return [mirror, fresh], set(), None


_sweep.search_workday = _fake_search
_sweep.time.sleep = lambda s: None
import sys as _sys
_sys.argv = ['workday_sweep.py', '--priority-only']
_sweep.main()
check('workday sweep notifies only the fresh job', _notified,
      ['Forward Deployed Engineer'])
_post = Store(str(_tmpdir / 'jobs.db'))
check('workday sweep recorded fresh job in jobs.db',
      _post.canonical_exists(
          canonical_key({'company': 'Acme', 'title': 'Forward Deployed Engineer',
                         'location': 'Toronto'})),
      True)
_post.close()
from datetime import date, timedelta  # noqa: E402
TODAY = date(2026, 10, 12)
RECENT = (TODAY - timedelta(days=2)).isoformat()


def _job(desc, title='Software Engineer'):
    return {'company': 'Co', 'title': title, 'description': desc,
            'location': 'Austin, TX', 'date_posted': RECENT}


check('matcher rejects client-list name-drop',
      job_matches(_job('We have partnered with companies like Google, ServiceNow, Uber.'), TODAY)[0],
      False)
check('matcher rejects list boilerplate',
      job_matches(_job('Nice-to-have familiarity with platforms such as Salesforce or ServiceNow.'), TODAY)[0],
      False)
check('matcher rejects competitor framing',
      job_matches(_job('Position our suite against ServiceNow to win deals.'), TODAY)[0],
      False)
check('matcher rejects migrate-from framing',
      job_matches(_job('Help customers migrate from ServiceNow to our platform.'), TODAY)[0],
      False)
check('matcher keeps genuine sentence',
      job_matches(_job('You will use ServiceNow to configure ITSM workflows.'), TODAY)[0],
      True)
check('matcher keeps title match',
      job_matches(_job('Unrelated description.', title='ServiceNow Developer'), TODAY)[0],
      True)

print(f'\n{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
