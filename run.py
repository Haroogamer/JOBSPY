"""ServiceNow job crawler — main entry point.

Crawls ATS boards (Greenhouse / Lever / Ashby) + free job APIs, matches
ServiceNow-family roles, dedupes in SQLite, notifies via Discord. Zero paid APIs.

Workday boards are SKIPPED here by design: Workday blocks datacenter IPs, so
every Workday board fails from GitHub Actions. Workday coverage comes from
workday_sweep.py, which runs on a local machine. See crawler/workday.py.

Usage: python run.py [--dry-run] [--limit N]
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
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

from crawler.boards import crawl_company   # noqa: E402
from crawler.config import SOURCES  # noqa: E402
from crawler.match import annotate_job, job_matches  # noqa: E402
from crawler.notify import notify          # noqa: E402
from crawler.sources.jobspy_indeed import fetch_indeed_jobs  # noqa: E402
from crawler.store import Store, job_hash    # noqa: E402

try:
    from crawler.freeapis import fetch_all as fetch_free_apis
except ImportError:
    fetch_free_apis = None


def load_companies():
    data = json.loads((HERE / 'companies.json').read_text())
    if isinstance(data, dict):  # {platform: [{company, board}]}
        out = []
        for platform, items in data.items():
            for it in items:
                out.append({'company': it['company'], 'platform': platform,
                            'board': it['board']})
        return out
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()

    # --dry-run never touches the real database: it runs against an in-memory
    # store so test crawls can't pollute dedupe state or notification history.
    store = Store(':memory:') if args.dry_run else Store(HERE / 'jobs.db')
    stats = {'companies': 0, 'seen': 0, 'matched': 0, 'new': 0,
             'errors': 0, 'skipped_workday': 0}
    t0 = time.time()

    companies = load_companies() if SOURCES['ats_boards'] else []
    if not SOURCES['ats_boards']:
        print('ats boards disabled (SOURCE_ATS_BOARDS=0) — set to 1 to re-enable')
    # Workday can't run from cloud IPs — skip here, cover via workday_sweep.py.
    runnable, skipped = [], 0
    for c in companies:
        if c.get('platform') == 'workday':
            skipped += 1
        else:
            runnable.append(c)
    stats['skipped_workday'] = skipped
    if skipped:
        print(f'skipping {skipped} workday boards (local sweep covers these)')
    companies = runnable
    if args.limit:
        companies = companies[:args.limit]

    def _crawl(entry):
        jobs, err = crawl_company(entry)
        return entry, jobs, err

    # Crawl boards in parallel: sequential requests take too long for the
    # Actions timeout. DB writes and notifications stay serial afterwards so
    # SQLite access stays single-threaded.
    with ThreadPoolExecutor(max_workers=12) as ex:
        crawled = list(ex.map(_crawl, companies))

    for entry, jobs, err in crawled:
        stats['companies'] += 1
        if err:
            stats['errors'] += 1
            print(f'  ! {err}')
            continue
        for job in jobs:
            stats['seen'] += 1
            ok, _ = job_matches(job)
            if not ok:
                continue
            stats['matched'] += 1
            job['date_discovered'] = datetime.now(timezone.utc).isoformat()
            annotate_job(job)
            if store.add(job, source='ats-board'):
                stats['new'] += 1
                if args.dry_run:
                    print(f"  + [{job['company']}] {job['title']} ({job['location']})")
                else:
                    sent, _ = notify(job)
                    if sent:
                        store.mark_notified(job_hash(job))
        store.commit()

    if SOURCES['indeed_jobspy']:
        ijobs, ierrors = fetch_indeed_jobs()
        for e in ierrors:
            stats['errors'] += 1
            print(f'  ! indeed-jobspy: {e}')
        for job in ijobs:
            stats['seen'] += 1
            ok, _ = job_matches(job)
            if not ok:
                continue
            stats['matched'] += 1
            job['date_discovered'] = datetime.now(timezone.utc).isoformat()
            annotate_job(job)
            if store.add(job, source='indeed-jobspy'):
                stats['new'] += 1
                if args.dry_run:
                    print(f"  + [{job['company']}] {job['title']} ({job['location']})")
                else:
                    sent, _ = notify(job)
                    if sent:
                        store.mark_notified(job_hash(job))
        store.commit()

    if SOURCES['free_apis'] and fetch_free_apis:
        for job in fetch_free_apis():
            stats['seen'] += 1
            ok, _ = job_matches(job)
            if not ok:
                continue
            stats['matched'] += 1
            job['date_discovered'] = datetime.now(timezone.utc).isoformat()
            annotate_job(job)
            if store.add(job, source='free-api'):
                stats['new'] += 1
                if args.dry_run:
                    print(f"  + [{job['company']}] {job['title']} ({job['location']})")
                else:
                    sent, _ = notify(job)
                    if sent:
                        store.mark_notified(job_hash(job))
        store.commit()

    store.log_run(stats)
    store.commit()

    # Production: retry anything matched but never notified (dry-run leftovers,
    # webhook failures, etc.). Pending jobs are only marked after a successful
    # Discord delivery, so a failed delivery is retried on the next run.
    if not args.dry_run:
        for job in store.pending():
            sent, _ = notify(job)
            if sent:
                stats['new'] += 1
                store.mark_notified(job_hash(job))
        store.commit()

    store.close()
    dt = time.time() - t0
    print(f'done in {dt:.0f}s: {stats["companies"]} boards, {stats["seen"]} jobs seen,'
          f' {stats["matched"]} matched, {stats["new"]} new, {stats["errors"]} errors,'
          f' {stats["skipped_workday"]} workday skipped')


if __name__ == '__main__':
    main()
