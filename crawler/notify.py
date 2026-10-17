"""Discord notifications via webhook. Set DISCORD_WEBHOOK_URL env var."""
import os

import requests

from .hiring import email_format_hint


def format_age(age_days):
    if age_days is None:
        return 'date unknown'
    if age_days <= 0:
        return 'today'
    if age_days == 1:
        return 'yesterday'
    return f'{age_days}d ago'


def notify(job):
    url = os.environ.get('DISCORD_WEBHOOK_URL', '').strip()
    if not url:
        return False, 'no webhook configured'
    title = (job.get('title') or 'Untitled').strip() or 'Untitled'
    if job.get('gta'):
        title = f'🌆 [GTA] {title}'
    # Core tier = ServiceNow / Forward Deployed term in the title: star it so
    # titled roles jump out. Every alert is a genuine role now — there is no
    # mention tier since 2026-10-11.
    if job.get('tier') == 'core':
        title = f'⭐ {title}'
    age = format_age(job.get('age_days'))
    fields = [
        {'name': 'Company', 'value': job.get('company') or 'Unknown', 'inline': True},
        {'name': 'Location', 'value': job.get('location') or 'Unknown', 'inline': True},
        {'name': 'Posted', 'value': age, 'inline': True},
        {'name': 'Source', 'value': job.get('platform') or job.get('source') or 'api', 'inline': True},
    ]
    # Fit ranking (v7): surface the senior AI-heavy target profile first.
    # Present only when computed (annotate_job sets it; DB-retry jobs lack it).
    if job.get('fit_score') is not None:
        fields.append({'name': '🎯 Fit',
                       'value': f"{str(job.get('fit_tier', 'standard')).title()} ({job['fit_score']})",
                       'inline': True})
    # Salary enrichment: shown only when the source ATS published it.
    salary = job.get('salary_text')
    if not salary and (job.get('salary_min') is not None or job.get('salary_max') is not None):
        mn = job.get('salary_min')
        mx = job.get('salary_max')
        fmt = lambda v: f'{v:,.0f}' if isinstance(v, (int, float)) else str(v)  # noqa: E731
        salary = f'{fmt(mn)}-{fmt(mx)}' if mn is not None and mx is not None and mn != mx else fmt(mn if mn is not None else mx)
        if job.get('salary_currency'):
            salary = f'{salary} {job["salary_currency"]}'
    if salary:
        fields.append({'name': '💰 Salary', 'value': salary, 'inline': True})
    # Attach the company's email format when known, so a hiring-manager
    # name (researched on demand) turns into an address in one step.
    hint = email_format_hint(job.get('company'))
    if hint:
        fields.append({'name': '📧 Email format', 'value': hint, 'inline': False})
    try:
        r = requests.post(url, json={'embeds': [{
            'title': title,
            'url': job.get('url'),
            'description': f"New job match at {job.get('company', 'Unknown')} — posted {age}",
            'color': 0x2F80ED,
            'fields': fields,
        }]}, timeout=15)
        r.raise_for_status()
        return True, 'sent'
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]
