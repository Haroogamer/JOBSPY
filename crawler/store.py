"""SQLite job store: dedupe by hash, track what's already been notified.

Two dedupe layers:
  1. URL hash (exact): the same posting URL never alerts twice.
  2. Canonical key (cross-source): the same role mirrored on two platforms
     (e.g. Workday + Lever, or a company migrating ATS boards) alerts once.
     Key = normalized company + normalized title + normalized city.
     Title normalization strips trailing req-ID parentheticals ("(10566)")
     and "Req ..." suffixes, but KEEPS location parentheticals ("(Ohio)").
     Within one platform the URL hash still governs, so distinct reqs on the
     same board (same title, same city, different URLs) still alert.

Schema migrates in place: enrichment columns (salary_*, workplace_type,
canonical_key) are added to an existing jobs.db on first open.
"""
import hashlib
import re
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_hash TEXT PRIMARY KEY,
    company TEXT, platform TEXT, source TEXT,
    title TEXT, location TEXT, url TEXT,
    date_posted TEXT, date_discovered TEXT,
    notified INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT, companies_crawled INTEGER, jobs_seen INTEGER,
    jobs_matched INTEGER, jobs_new INTEGER, errors INTEGER
);
"""

# Columns added after the original schema — backfilled on open.
EXTRA_COLUMNS = {
    'salary_min': 'REAL',
    'salary_max': 'REAL',
    'salary_currency': 'TEXT',
    'salary_text': 'TEXT',
    'workplace_type': 'TEXT',
    'canonical_key': 'TEXT',
}

_LEGAL_SUFFIXES = {'inc', 'llc', 'ltd', 'corp', 'corporation', 'co', 'company'}
_WORK_MODE_WORDS = {'remote', 'hybrid', 'on-site', 'onsite', 'virtual', 'on site'}
_REQ_PAREN_RE = re.compile(r'\s*\(([^)]*(req|jb|job|id|#|\d{4,})[^)]*)\)\s*$', re.IGNORECASE)
_REQ_SUFFIX_RE = re.compile(r'\s*[-–—]\s*req.*$', re.IGNORECASE)
_REQ_TAIL_RE = re.compile(r'\s+req(uisition)?\s*#?\s*[\w-]+\s*$', re.IGNORECASE)


def _squash(text):
    text = re.sub(r'[^a-z0-9]+', ' ', (text or '').lower())
    return re.sub(r'\s+', ' ', text).strip()


def _norm_company(name):
    words = _squash(name).split()
    while words and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    return ' '.join(words)


def _norm_title(title):
    t = (title or '').strip()
    t = _REQ_PAREN_RE.sub('', t)
    t = _REQ_SUFFIX_RE.sub('', t)
    t = _REQ_TAIL_RE.sub('', t)
    return _squash(t)


def _norm_city(location):
    """First real city from a location string. Work-mode-only segments
    ('Hybrid', 'Remote') are skipped; 'Toronto, Ontario' -> 'toronto'."""
    loc = location or ''
    for seg in re.split(r'[;|]', loc):
        words = [w for w in seg.lower().split() if w.strip(',') not in _WORK_MODE_WORDS]
        city = _squash(' '.join(words).split(',')[0])
        if city:
            return city
    return 'remote' if 'remote' in loc.lower() else 'unknown'


def canonical_key(job):
    """Cross-source identity: company + title + city, normalized."""
    return '|'.join([
        _norm_company(job.get('company')),
        _norm_title(job.get('title')),
        _norm_city(job.get('location')),
    ])


def job_hash(job):
    key = ':'.join([
        job.get('platform', ''), job.get('company', ''),
        job.get('title', ''), job.get('location', ''), job.get('url', ''),
    ])
    return hashlib.sha256(key.encode()).hexdigest()


class Store:
    def __init__(self, path):
        # 30s lock timeout: the ATS and Workday sweeps run on the same
        # cadence and both write here now — a brief lock wait beats an error.
        self.db = sqlite3.connect(path, timeout=30)
        self.db.executescript(SCHEMA)
        cols = {r[1] for r in self.db.execute('PRAGMA table_info(jobs)')}
        for col, typ in EXTRA_COLUMNS.items():
            if col not in cols:
                self.db.execute(f'ALTER TABLE jobs ADD COLUMN {col} {typ}')
        self.db.commit()
        # Backfill canonical keys for rows stored before the column existed,
        # so cross-source dedup works against history, not just new rows.
        for row in self.db.execute(
                'SELECT job_hash, company, title, location FROM jobs'
                ' WHERE canonical_key IS NULL'):
            ck = canonical_key({'company': row[1], 'title': row[2], 'location': row[3]})
            self.db.execute('UPDATE jobs SET canonical_key=? WHERE job_hash=?',
                            (ck, row[0]))
        self.db.commit()

    def seen(self, h):
        return self.db.execute(
            'SELECT 1 FROM jobs WHERE job_hash=?', (h,)).fetchone() is not None

    def canonical_exists(self, ck, exclude_platform=None):
        """True when a DIFFERENT platform already holds this canonical role."""
        if exclude_platform is None:
            row = self.db.execute(
                'SELECT 1 FROM jobs WHERE canonical_key=? LIMIT 1', (ck,)).fetchone()
        else:
            row = self.db.execute(
                'SELECT 1 FROM jobs WHERE canonical_key=? AND platform != ? LIMIT 1',
                (ck, exclude_platform)).fetchone()
        return row is not None

    def add(self, job, source):
        """Returns True if this is a genuinely new job (not seen by URL hash,
        and not a cross-platform mirror of an already-stored role)."""
        h = job_hash(job)
        if self.seen(h):
            return False
        ck = canonical_key(job)
        if self.canonical_exists(ck, exclude_platform=job.get('platform')):
            return False
        self.db.execute(
            'INSERT INTO jobs (job_hash, company, platform, source, title, location,'
            ' url, date_posted, date_discovered, notified, salary_min, salary_max,'
            ' salary_currency, salary_text, workplace_type, canonical_key)'
            ' VALUES (?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?)',
            (h, job.get('company'), job.get('platform'), source,
             job.get('title'), job.get('location'), job.get('url'),
             job.get('date_posted'), job.get('date_discovered'),
             job.get('salary_min'), job.get('salary_max'),
             job.get('salary_currency'), job.get('salary_text'),
             job.get('workplace_type'), ck),
        )
        return True

    def mark_notified(self, h):
        self.db.execute('UPDATE jobs SET notified=1 WHERE job_hash=?', (h,))

    def pending(self):
        """Jobs matched but never successfully notified (e.g. dry-run test data
        or transient Discord failures)."""
        cols = ('job_hash', 'company', 'platform', 'source', 'title', 'location',
                'url', 'date_posted', 'date_discovered')
        rows = self.db.execute(
            'SELECT job_hash, company, platform, source, title, location, url,'
            ' date_posted, date_discovered FROM jobs WHERE notified=0'
        ).fetchall()
        return [dict(zip(cols, r)) for r in rows]

    def log_run(self, stats):
        self.db.execute(
            'INSERT INTO runs (started_at, companies_crawled, jobs_seen, jobs_matched,'
            ' jobs_new, errors) VALUES (datetime("now"),?,?,?,?,?)',
            (stats['companies'], stats['seen'], stats['matched'],
             stats['new'], stats['errors']),
        )

    def commit(self):
        self.db.commit()

    def close(self):
        self.db.close()
