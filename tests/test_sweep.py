"""Tests for the Workday sweep machinery: rotation, checked-cache versioning,
board loading. Pure logic — no network. Run: python3 tests/test_sweep.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import workday_sweep as sweep
from crawler.match import MATCHER_VERSION

passed = failed = 0


def check(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print(f'FAIL [{name}]: got {got!r}, want {want!r}')


# --- next_rotation: walks the pool, wraps around, cursor saved by caller ---
_tmp = tempfile.NamedTemporaryFile(delete=False)
_tmp.close()
sweep.ROTATION_FILE = Path(_tmp.name)
Path(_tmp.name).write_text('{}')
pool = [(f'Co{i}', f'spec{i}') for i in range(65)]
sweep.ROTATION_SLICE = 30

first, cur1 = sweep.next_rotation(pool)
check('rotation first slice size', len(first), 30)
check('rotation first slice start', first[0][0], 'Co0')
check('rotation does not save cursor itself',
      json.loads(Path(_tmp.name).read_text()), {})
sweep.save_rotation(cur1)
second, cur2 = sweep.next_rotation(pool)
check('rotation second slice start', second[0][0], 'Co30')
sweep.save_rotation(cur2)
third, cur3 = sweep.next_rotation(pool)
check('rotation third slice wraps', third[0][0], 'Co60')
check('rotation third slice wraps size', len(third), 30)
sweep.save_rotation(cur3)
fourth, _ = sweep.next_rotation(pool)
check('rotation wraps to start', fourth[0][0], 'Co25')  # (90 % 65)
os.unlink(_tmp.name)

# --- load_checked: version mismatch resets ---
_tmp2 = tempfile.NamedTemporaryFile(delete=False)
_tmp2.close()
sweep.CHECKED_FILE = Path(_tmp2.name)
Path(_tmp2.name).write_text(json.dumps({'version': MATCHER_VERSION - 1,
                                        'urls': {'http://x': 't'}}))
c = sweep.load_checked()
check('checked version mismatch resets urls', c['urls'], {})
check('checked version mismatch sets version', c['version'], MATCHER_VERSION)
Path(_tmp2.name).write_text(json.dumps({'version': MATCHER_VERSION,
                                        'urls': {'http://y': 't'}}))
c = sweep.load_checked()
check('checked version match keeps urls', c['urls'], {'http://y': 't'})
Path(_tmp2.name).write_text('not json at all')
c = sweep.load_checked()
check('checked corrupt file resets', (c['version'], c['urls']),
      (MATCHER_VERSION, {}))
os.unlink(_tmp2.name)

# --- load_boards: priority flag splits correctly ---
_tmp3 = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
_tmp3.close()
sweep.BOARDS_FILE = Path(_tmp3.name)
Path(_tmp3.name).write_text(json.dumps([
    {'company': 'A', 'board': 'a|x', 'priority': True},
    {'company': 'B', 'board': 'b|y'},
    {'company': 'C', 'board': 'c|z', 'priority': True},
]))
priority, pool = sweep.load_boards()
check('priority boards', [p[0] for p in priority], ['A', 'C'])
check('rotation pool', [p[0] for p in pool], ['B'])
os.unlink(_tmp3.name)

# --- sweep_board: 3-tuple from search_workday is honored ---
calls = []


def fake_search(company, spec, query, max_results, skip_urls):
    calls.append((query, set(skip_urls)))
    jobs = [{'url': f'https://x/{query}/1', 'title': 'T1'},
            {'url': 'https://x/skip/9', 'title': 'T9'}]
    return jobs, {'https://x/fetched/1', 'https://x/fetched/2'}, None


sweep.search_workday = fake_search
sweep.SEARCH_QUERIES = ['q1', 'q2']
uniq, evaluated, err = sweep.sweep_board('Co', 'spec', {'https://x/skip/9'})
check('sweep_board err', err, None)
check('sweep_board evaluated has fetched urls',
      {'https://x/fetched/1', 'https://x/fetched/2'} <= evaluated, True)
check('sweep_board dedupes across queries', len(uniq), 3)  # q1/1, q2/1, skip/9
check('sweep_board passes skip_urls through',
      all('https://x/skip/9' in s for _, s in calls), True)

# --- _finalize_match: no duplicate Discord posts across sweeps -------------
# Regression test for 2026-10-16: workday_sweep.py never marked jobs as
# notified in jobs.db, so run.py's pending-retry loop re-alerted every
# Workday discovery on the next ATS sweep (TD Bank Product Owner and 2x
# Application Delivery Engineer II double-alerted).
from crawler.store import Store, job_hash  # noqa: E402

_tmp3 = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
_tmp3.close()
_store = Store(_tmp3.name)
_job = {'company': 'TD Bank', 'platform': 'workday', 'source': 'workday',
        'title': 'Product Owner I (US) eGRC AI',
        'location': 'Charlotte, North Carolina',
        'url': 'https://example.com/job/1', 'description': 'x',
        'date_posted': '2026-10-16', 'date_discovered': '2026-10-16T20:00:00'}
assert _store.add(_job, source='workday') is True
check('new workday job is pending before finalize',
      len(_store.pending()), 1)
sweep._finalize_match(_store, _job, True)
check('successful notify marks notified (no pending re-alert)',
      _store.pending(), [])
_job2 = dict(_job, url='https://example.com/job/2',
             title='Application Delivery Engineer II')
assert _store.add(_job2, source='workday') is True
sweep._finalize_match(_store, _job2, False)  # failed delivery
check('failed notify stays pending for retry',
      [j['url'] for j in _store.pending()], ['https://example.com/job/2'])
sweep._finalize_match(None, _job2, True)  # store unavailable: no crash
check('finalize with no store does not crash', True, True)
_store.close()
os.unlink(_tmp3.name)

print(f'\n{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
