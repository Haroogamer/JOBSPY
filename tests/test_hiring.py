"""Tests for crawler/hiring.py: email patterns, address construction, hints.

Uses a throwaway cache file so the real email_patterns.json is untouched.
Run: python3 tests/test_hiring.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import crawler.hiring as hiring

passed = failed = 0


def check(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print(f'FAIL [{name}]: got {got!r}, want {want!r}')


# point the cache at a temp file for the whole test run
_tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
_tmp.close()
hiring.CACHE_FILE = hiring.Path(_tmp.name)
hiring._save_cache({})

# seeding + hint
hiring.seed_pattern('snhu.edu', '{f}.{last}')
check('hint known company', hiring.email_format_hint('SNHU'), '{f}.{last}@snhu.edu')
check('hint unknown company', hiring.email_format_hint('Acme Corp'), None)
check('hint company w/o domain mapping', hiring.email_format_hint('Some Startup XYZ'), None)

# construction
check('build f.last', hiring.build_email('Jane', 'Doe', 'snhu.edu'), 'j.doe@snhu.edu')
check('build strips case/space', hiring.build_email('  MARY ', "O'Brien", 'snhu.edu'), 'm.obrien@snhu.edu')
check('build unknown domain -> None', hiring.build_email('Jane', 'Doe', 'unknown.io'), None)
check('build empty name -> None', hiring.build_email('', 'Doe', 'snhu.edu'), None)

# cache persists across "restarts" (reload from disk)
hiring.seed_pattern('example.com', '{first}.{last}')
fresh = hiring._load_cache()
check('cache persisted snhu', fresh.get('snhu.edu'), '{f}.{last}')
check('cache persisted example', fresh.get('example.com'), '{first}.{last}')

# no Hunter key -> no network, returns None for uncached domain
os.environ.pop('HUNTER_API_KEY', None)
check('no key, uncached -> None', hiring.get_pattern('never-seen.example'), None)

os.unlink(_tmp.name)
print(f'\n{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
