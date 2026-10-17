"""Hiring-manager email support: company email patterns + address construction.

What this does:
  - Maps a company name to its email domain (COMPANY_DOMAINS, seeded by hand
    as companies are researched — guessing a domain from a name is how you
    end up emailing the wrong company).
  - Keeps a persistent cache (email_patterns.json) of domain -> address
    pattern, e.g. "snhu.edu" -> "first.last".
  - Looks up an unknown pattern via Hunter.io's free Domain Search when
    HUNTER_API_KEY is set (25 free lookups/month; one lookup per company,
    cached forever after).
  - Builds a likely company address from a person's name + the pattern.

What this does NOT do:
  - Identify the hiring manager. Picking the right person needs judgment
    (LinkedIn research) and stays with the agent on demand — auto-guessing
    a name per alert would staple wrong people to wrong jobs.
  - Touch personal emails. Only company-domain addresses are constructed.

Notifier wiring: crawler/notify.py calls email_format_hint() and appends
the company's email format to the Discord alert when it's known.
"""

import json
import os
import re
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

HERE = Path(__file__).parent
CACHE_FILE = HERE / 'email_patterns.json'

# Company name (as it appears in job records) -> email domain.
# Add entries as they are verified; never guess.
COMPANY_DOMAINS = {
    'SNHU': 'snhu.edu',
    'Medtronic': 'medtronic.com',
    'Caterpillar': 'cat.com',
    'Accenture': 'accenture.com',
    'Avanade': 'avanade.com',
    'Adobe': 'adobe.com',
    'Target': 'target.com',
    'Amgen': 'amgen.com',
    'Anthropic': 'anthropic.com',
    'Databricks': 'databricks.com',
    'Cloudflare': 'cloudflare.com',
    'Okta': 'okta.com',
    'IonQ': 'ionq.com',
}

# Hunter.io pattern tokens -> template. '{first}' / '{last}' are the
# person's lowercased, de-accented name parts.
PATTERNS = {
    '{first}.{last}': '{first}.{last}',
    '{first}{last}': '{first}{last}',
    '{f}.{last}': '{first0}.{last}',
    '{first}.{l}': '{first}.{last0}',
    '{f}{last}': '{first0}{last}',
    '{first}_{last}': '{first}_{last}',
    '{last}.{first}': '{last}.{first}',
    '{last}{first}': '{last}{first}',
}


def _load_cache():
    try:
        return json.loads(CACHE_FILE.read_text())
    except Exception:
        return {}


def _save_cache(cache):
    CACHE_FILE.write_text(json.dumps(cache, indent=1, sort_keys=True))


def _hunter_pattern(domain):
    """Ask Hunter.io Domain Search for the company's email pattern."""
    api_key = os.environ.get('HUNTER_API_KEY', '').strip()
    if not api_key or requests is None:
        return None
    try:
        r = requests.get(
            'https://api.hunter.io/v2/domain-search',
            params={'domain': domain, 'api_key': api_key},
            timeout=15,
        )
        r.raise_for_status()
        return (r.json().get('data') or {}).get('pattern')
    except Exception:
        return None


def get_pattern(domain):
    """Return the email pattern for a domain, using the cache then Hunter."""
    domain = (domain or '').strip().lower()
    if not domain:
        return None
    cache = _load_cache()
    if domain in cache:
        return cache[domain]
    pattern = _hunter_pattern(domain)
    if pattern:
        cache[domain] = pattern
        _save_cache(cache)
    return pattern


def seed_pattern(domain, pattern):
    """Manually record a verified pattern (used when researched by hand)."""
    domain = (domain or '').strip().lower()
    if not domain or not pattern:
        raise ValueError('domain and pattern are required')
    cache = _load_cache()
    cache[domain] = pattern
    _save_cache(cache)
    return pattern


def _clean(name):
    name = (name or '').strip().lower()
    name = re.sub(r"['`]", '', name)
    name = re.sub(r'[^a-z-]', ' ', name)
    parts = [p for p in name.split('-')[0].split() if p]
    return parts[0] if parts else ''


def build_email(first_name, last_name, domain):
    """Build the likely company address for a person.

    Returns None when the domain or its pattern is unknown — a missing
    email is better than a fabricated one.
    """
    pattern = get_pattern(domain)
    template = PATTERNS.get(pattern or '')
    if not template:
        return None
    first, last = _clean(first_name), _clean(last_name)
    if not first or not last:
        return None
    local = template.format(first=first, last=last,
                            first0=first[0], last0=last[0])
    return f'{local}@{domain.strip().lower()}'


def email_format_hint(company):
    """Human-readable email format for a company, e.g. 'first.last@snhu.edu'.

    Returns None when the domain or pattern isn't known yet.
    """
    domain = COMPANY_DOMAINS.get((company or '').strip())
    if not domain:
        return None
    pattern = get_pattern(domain)
    if not pattern:
        return None
    return f'{pattern}@{domain}'
