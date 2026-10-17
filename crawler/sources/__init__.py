"""Broad job-board sources (Indeed via jobspy, ...).

Each module exposes a fetch_*() function returning (jobs, errors) and never
raising — per-source isolation so one dead source never kills the sweep.
Job dicts match the shape crawler/match.py expects:
company / platform / title / location / url / date_posted / description.
"""
