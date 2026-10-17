"""Periodic Workday sweep for ServiceNow + Forward Deployed roles —
RUNS ON A LOCAL MACHINE ONLY.

Workday blocks datacenter IPs, so this never runs in GitHub Actions.
Schedule it with cron on a home machine (see README), or run manually:

    python workday_sweep.py                  # priority boards + next rotation slice
    python workday_sweep.py --priority-only  # just the 23 priority boards
    python workday_sweep.py --rotation-only  # just the next rotation slice
    python workday_sweep.py --all            # all 204 boards (slow, manual)

How coverage works:
  - Boards live in workday_boards.json; priority ones carry "priority": true.
  - Every run sweeps all priority boards plus the next ROTATION_SLICE
    non-priority boards. The rotation cursor persists in
    workday_rotation.json, so the full 204-board list is covered over ~6
    runs (~36h at the 6-hourly cadence) without any single run taking hours.
  - Each board is searched for 'servicenow' and 'forward deployed'
    (user request 2026-09-30); results page through up to MAX_RESULTS
    per query so big boards don't hide fresh postings past page one.

Speed: posting URLs already evaluated (notified OR checked-and-rejected)
are skipped before their detail pages are fetched — repeat sweeps only pay
for genuinely new postings. The checked cache is keyed by MATCHER_VERSION,
so a matcher change re-evaluates everything once.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

# load local .env (KEY=VALUE) if present — secrets never leave this machine
_env = HERE / '.env'
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from crawler.match import MATCHER_VERSION, annotate_job  # noqa: E402
from crawler.notify import notify  # noqa: E402
from crawler.store import Store, job_hash  # noqa: E402
from crawler.workday import search_workday  # noqa: E402

SEEN_FILE = HERE / 'workday_seen.json'          # urls already notified
CHECKED_FILE = HERE / 'workday_checked.json'    # urls evaluated but not matched
ROTATION_FILE = HERE / 'workday_rotation.json'  # cursor into non-priority pool
BOARDS_FILE = HERE / 'workday_boards.json'
LOG_FILE = HERE / 'workday_sweep.log'

# Search queries run per board: ServiceNow roles + Forward Deployed roles
# (user request 2026-09-30). Both go through the same matcher.
SEARCH_QUERIES = ['servicenow', 'forward deployed']
# Non-priority boards swept per run. 181 in the pool / 30 per run ~= full
# coverage every 6 runs (~36h at the 6-hourly cadence).
ROTATION_SLICE = 30
# Max search results evaluated per query per board (paging, 20 per page).
MAX_RESULTS = 40


def log(msg):
    line = f'{datetime.now(timezone.utc).isoformat()} {msg}'
    print(line, flush=True)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')


def _load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def _save_json(path, data):
    Path(path).write_text(json.dumps(data, indent=1))


def load_boards():
    """(priority, pool) — priority boards always run; pool rotates."""
    boards = _load_json(BOARDS_FILE, [])
    priority = [(b['company'], b['board']) for b in boards if b.get('priority')]
    pool = [(b['company'], b['board']) for b in boards if not b.get('priority')]
    return priority, pool


def load_checked():
    """Evaluated-but-rejected URLs. Reset when the matcher changes, so a
    rule change re-evaluates everything once instead of trusting old verdicts."""
    data = _load_json(CHECKED_FILE, {})
    if not isinstance(data, dict) or data.get('version') != MATCHER_VERSION:
        return {'version': MATCHER_VERSION, 'urls': {}}
    urls = data.get('urls')
    return {'version': MATCHER_VERSION, 'urls': urls if isinstance(urls, dict) else {}}


def next_rotation(pool):
    """Next ROTATION_SLICE boards from the pool plus the cursor to save.

    The cursor is returned, not saved — the caller persists it after the
    sweep completes, so a killed run re-sweeps the same slice next time
    instead of silently skipping boards for a full cycle.
    """
    if not pool:
        return [], 0
    state = _load_json(ROTATION_FILE, {})
    cursor = state.get('cursor', 0) % len(pool)
    boards = [pool[(cursor + i) % len(pool)] for i in range(min(ROTATION_SLICE, len(pool)))]
    return boards, (cursor + len(boards)) % len(pool)


def save_rotation(cursor):
    _save_json(ROTATION_FILE, {'cursor': cursor})


def sweep_board(company, spec, known_urls):
    """Search one board for all queries. Returns (matches, evaluated, err)."""
    matched, err = [], None
    evaluated = set()
    for q in SEARCH_QUERIES:
        m, fetched, e = search_workday(company, spec, query=q, max_results=MAX_RESULTS,
                                       skip_urls=known_urls | evaluated)
        evaluated |= fetched
        matched.extend(m)
        if e and not err:
            err = e
        time.sleep(4)  # pacing between queries — Workday throttles aggressively
    # dedupe across queries (same job can hit both searches)
    uniq = list({j['url']: j for j in matched}.values())
    return uniq, evaluated, err


def _finalize_match(store, job, ok):
    """Mark a successfully-notified job in the shared DB so run.py's
    pending-retry loop won't re-alert it on the next ATS sweep.

    Without this, every Workday discovery gets a duplicate Discord post
    (2026-10-16: TD Bank Product Owner and 2x Application Delivery
    Engineer II both double-alerted). Failed deliveries (ok=False) stay
    notified=0 so the pending loop can retry them — that path is
    intentional.
    """
    if store is not None and ok:
        try:
            store.mark_notified(job_hash(job))
            store.commit()
        except Exception as e:  # noqa: BLE001 - seen.json is the source of truth
            log(f'! mark_notified failed: {e}'[:160])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--priority-only', action='store_true')
    ap.add_argument('--rotation-only', action='store_true')
    ap.add_argument('--all', action='store_true')
    args = ap.parse_args()

    priority, pool = load_boards()
    if args.all:
        boards = priority + pool
        mode = f'all {len(boards)} boards'
    elif args.priority_only:
        boards = priority
        mode = f'priority-only ({len(boards)})'
    elif args.rotation_only:
        rot, new_cursor = next_rotation(pool)
        boards = rot
        mode = f'rotation-only ({len(boards)})'
    else:
        rot, new_cursor = next_rotation(pool)
        boards = priority + rot
        mode = f'priority ({len(priority)}) + rotation ({len(rot)})'
    log(f'start: {mode}')

    seen = _load_json(SEEN_FILE, {})
    checked = load_checked()
    known_urls = set(seen) | set(checked['urls'])
    new_matches, errors = 0, 0
    now = datetime.now(timezone.utc).isoformat()

    # Shared dedupe with the ATS sweep: a role already alerted from another
    # platform (same company + title + city) must not alert again here.
    # DB errors fail OPEN (notify anyway) — a locked DB must not lose alerts.
    try:
        store = Store(HERE / 'jobs.db')
    except Exception as e:  # noqa: BLE001
        log(f'! jobs.db unavailable, cross-source dedup off: {e}'[:160])
        store = None

    for company, spec in boards:
        uniq, evaluated, err = sweep_board(company, spec, known_urls)
        if err:
            errors += 1
            log(f'! {company}: {err}')
        fresh = [j for j in uniq if j['url'] not in seen]
        for job in fresh:
            annotate_job(job)
            job['date_discovered'] = now
            dup = False
            if store is not None:
                try:
                    # Record in jobs.db first: add() returns False for a URL
                    # already stored OR a cross-platform mirror of it.
                    if not store.add(job, source='workday'):
                        dup = True
                        log(f'  = DUP: {job["title"]} @ {company} ({job["location"]}) — already alerted from another platform')
                    store.commit()
                except Exception as e:  # noqa: BLE001 - fail open
                    log(f'! jobs.db write failed, notifying anyway: {e}'[:160])
            if dup:
                seen[job['url']] = now
                known_urls.add(job['url'])
                continue
            ok, msg = notify(job)
            log(f'  + NEW: {job["title"]} @ {company} ({job["location"]}) -> discord={ok} {msg}')
            seen[job['url']] = now
            known_urls.add(job['url'])
            new_matches += 1
            _finalize_match(store, job, ok)
        # Remember rejections so repeat sweeps don't re-fetch their details.
        for url in evaluated:
            if url not in seen and url not in checked['urls']:
                checked['urls'][url] = now
                known_urls.add(url)
        if uniq and not fresh:
            log(f'  = {company}: {len(uniq)} matched, all seen before')
        elif not uniq and not err:
            log(f'  - {company}: no matches')
        time.sleep(4)  # pacing between boards — Workday throttles aggressively

    _save_json(SEEN_FILE, seen)
    _save_json(CHECKED_FILE, checked)
    if store is not None:
        store.close()
    if not args.all and not args.priority_only:
        save_rotation(new_cursor)
    log(f'done: {len(boards)} boards, {new_matches} new, {errors} errors')


if __name__ == '__main__':
    main()
