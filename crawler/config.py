"""Per-source enable/disable flags. Env-driven; documented in .env.example.

Defaults reflect the 2026-10-17 call:
  - indeed_jobspy ON  — primary source (free, no key, greenfield coverage)
  - ats_boards   OFF — modules kept in crawler/boards.py, disabled by flag
  - workday      OFF — modules kept in crawler/workday.py, disabled by flag
                       (also datacenter-blocked, so never viable on Actions)
  - free_apis    ON  — keeps existing key-gated behavior (Adzuna/USAJobs/
                       Jobicy skip silently when keys are absent)

Set e.g. SOURCE_ATS_BOARDS=1 to re-enable a source without touching code.
"""
import os


def _flag(name, default):
    return os.environ.get(name, default).strip().lower() in ('1', 'true', 'yes', 'on')


SOURCES = {
    'indeed_jobspy': _flag('SOURCE_INDEED_JOBSPY', '1'),
    'ats_boards': _flag('SOURCE_ATS_BOARDS', '0'),
    'workday': _flag('SOURCE_WORKDAY', '0'),
    'free_apis': _flag('SOURCE_FREE_APIS', '1'),
}
