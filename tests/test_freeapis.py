"""Tests for crawler/freeapis.py Adzuna dual-country fetch (mocked HTTP).
Run: python3 tests/test_freeapis.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from crawler import freeapis

passed = failed = 0


def check(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print(f'FAIL [{name}]: got {got!r}, want {want!r}')


os.environ['ADZUNA_APP_ID'] = 'test-id'
os.environ['ADZUNA_APP_KEY'] = 'test-key'

calls = []


class FakeResp:
    def __init__(self, country):
        self.country = country

    def raise_for_status(self):
        pass

    def json(self):
        return {'results': [{
            'company': {'display_name': f'Co-{self.country}'},
            'title': 'ServiceNow Dev',
            'location': {'display_name': 'Toronto' if self.country == 'ca' else 'Austin'},
            'redirect_url': f'https://x/{self.country}/1',
            'created': '2026-10-01',
            'description': 'ServiceNow work',
        }]}


def fake_get(url, params=None, headers=None, timeout=None):
    country = 'ca' if '/jobs/ca/' in url else 'us'
    calls.append(country)
    return FakeResp(country)


freeapis.requests.get = fake_get
jobs = freeapis.fetch_adzuna()
check('queries both countries', sorted(calls), ['ca', 'us'])
check('returns jobs from both', sorted(j['company'] for j in jobs), ['Co-ca', 'Co-us'])
check('job shape has url', all(j['url'].startswith('https://x/') for j in jobs), True)

# no keys -> skipped silently
del os.environ['ADZUNA_APP_ID']
del os.environ['ADZUNA_APP_KEY']
check('no keys returns []', freeapis.fetch_adzuna(), [])

print(f'\n{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
