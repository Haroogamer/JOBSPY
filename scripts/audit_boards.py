"""Board health audit: check every ATS board in companies.json is alive.

Workday boards are skipped (they block datacenter IPs by design — see
crawler/workday.py). Everything else gets one cheap request:

    python scripts/audit_boards.py            # summary only
    python scripts/audit_boards.py --verbose  # per-board status lines
    python scripts/audit_boards.py --fix      # drop dead boards from companies.json
                                              # (keeps a .bak of the original)

A board counts as dead after 3 failed attempts. --fix rewrites
companies.json in place; review the diff before committing.
"""
import argparse
import json
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))

import requests  # noqa: E402
from crawler.boards import UA, TIMEOUT  # noqa: E402

CHECK_URLS = {
    'greenhouse': lambda s: f'https://boards-api.greenhouse.io/v1/boards/{s}/jobs',
    'lever': lambda s: f'https://api.lever.co/v0/postings/{s}?mode=json',
    'ashby': lambda s: f'https://api.ashbyhq.com/posting-api/job-board/{s}',
}


def check(entry):
    platform, slug = entry['platform'], entry['board']
    url_fn = CHECK_URLS.get(platform)
    if not url_fn:
        return entry, 'UNKNOWN-PLATFORM'
    for _ in range(3):
        try:
            r = requests.get(url_fn(slug), headers=UA, timeout=TIMEOUT)
            if r.status_code == 200:
                return entry, 'OK'
            if r.status_code in (400, 429):
                time.sleep(5)
                continue
            return entry, f'DEAD-{r.status_code}'
        except Exception:
            time.sleep(5)
    return entry, 'DEAD-ERR'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--fix', action='store_true',
                    help='drop dead boards from companies.json (keeps .bak)')
    args = ap.parse_args()

    path = HERE / 'companies.json'
    boards = json.loads(path.read_text())
    live, dead = [], []
    with ThreadPoolExecutor(max_workers=10) as ex:
        for entry, status in ex.map(check, boards):
            if entry.get('platform') == 'workday':
                continue  # blocked from cloud IPs by design; not a failure
            if status == 'OK':
                live.append(entry)
            else:
                dead.append((entry, status))
            if args.verbose:
                print(f'{status:10} {entry["platform"]:10} {entry["company"]} | {entry["board"]}')

    print(f'\n{len(live)} live, {len(dead)} dead, {len(boards)} total')
    for entry, status in dead:
        print(f'  {status:10} {entry["platform"]:10} {entry["company"]} | {entry["board"]}')

    if args.fix and dead:
        dead_ids = {(e['platform'], e['board']) for e, _ in dead}
        kept = [b for b in boards if (b['platform'], b['board']) not in dead_ids]
        shutil.copy(path, str(path) + '.bak')
        path.write_text(json.dumps(kept, indent=1))
        print(f'removed {len(boards) - len(kept)} dead boards (backup at companies.json.bak)')


if __name__ == '__main__':
    main()
