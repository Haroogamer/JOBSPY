"""Tests for the v7 retarget (2026-10-13): senior AI-heavy ServiceNow profile.

- ServiceNow-product titles ("Now Assist", "AI Control Tower") match without
  the brand in the title; generic AI titles do NOT match on title alone.
- fit_score / fit_tier rank matches (seniority + specialty clusters);
  ranking never filters (junior/generic roles still match).
- Remote-only postings are rejected (on-site/hybrid only).
- v6 strictness (client-list / competitor / list boilerplate) is preserved.

Run: python3 tests/test_retarget.py
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from crawler.match import (  # noqa: E402
    MATCHER_VERSION, annotate_job, fit_score, fit_tier, is_remote_only,
    job_matches, match_tier, title_might_match,
)

TODAY = date(2026, 10, 12)
D = lambda n: (TODAY - timedelta(days=n)).isoformat()  # noqa: E731
SN_DESC = ("We are hiring a ServiceNow Developer to implement and configure "
           "workflows on the Now Platform.")

PASS = 0
FAIL = 0


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
    else:
        FAIL += 1
        print(f'FAIL [{name}]: got {got!r}, want {want!r}')


def J(title, desc=SN_DESC, loc='Toronto, ON', company='Acme', posted=D(1), **kw):
    j = {'company': company, 'title': title, 'description': desc,
         'location': loc, 'date_posted': posted}
    j.update(kw)
    return j


check('matcher version is 12', MATCHER_VERSION, 12)

# --- ServiceNow-product titles match without the brand ----------------------
check('Now Assist title matches',
      job_matches(J('Now Assist Developer', desc=''), TODAY), (True, 'match'))
check('Now Assist title is core tier',
      match_tier({'title': 'Now Assist Developer'}), 'core')
check('Now Assist Consultant matches',
      job_matches(J('Now Assist Consultant', desc=''), TODAY), (True, 'match'))
check('AI Control Tower title matches',
      job_matches(J('AI Control Tower Engineer', desc=''), TODAY), (True, 'match'))
check('AI Control Tower title is core tier',
      match_tier({'title': 'AI Control Tower Engineer'}), 'core')
check('Now Assist in description matches',
      job_matches(J('Software Engineer',
                    desc='Configure Now Assist for ITSM.'), TODAY), (True, 'match'))
check('AI Control Tower in description matches',
      job_matches(J('Platform Engineer',
                    desc='Manage AI Control Tower model governance.'), TODAY),
      (True, 'match'))

# --- generic AI titles do NOT match on title alone ---------------------------
check('GenAI title alone does not match',
      job_matches(J('GenAI Architect', desc='Build AI models.'), TODAY),
      (False, 'relevance'))
check('AI Engineer title alone does not match',
      job_matches(J('AI Engineer', desc='Work with AI systems.'), TODAY),
      (False, 'relevance'))
check('GenAI title + ServiceNow description matches',
      job_matches(J('GenAI Architect',
                    desc='Lead generative AI on the ServiceNow platform.'), TODAY),
      (True, 'match'))

# --- title pre-filter picks up product titles ---------------------------------
check('prefilter Now Assist', title_might_match('Now Assist Developer'), True)
check('prefilter AI Control Tower', title_might_match('AI Control Tower Lead'), True)
check('prefilter still rejects generic AI', title_might_match('GenAI Engineer'), False)

# --- fit scoring ---------------------------------------------------------------
check('senior SN dev scores 75 high',
      (fit_score(J('Senior ServiceNow Developer', desc='')),
       fit_tier(fit_score(J('Senior ServiceNow Developer', desc='')))), (75, 'high'))
check('junior SN admin scores 45 standard (still matches)',
      (fit_score(J('Junior ServiceNow Admin', desc='')),
       job_matches(J('Junior ServiceNow Admin', desc=''), TODAY)[0]), (45, True))
check('Now Assist dev scores 80 high',
      fit_score(J('Now Assist Developer', desc='')), 80)
check('SN AI Architect scores 95 high',
      fit_score(J('ServiceNow AI Architect - Now Assist', desc='')), 95)
check('generic desc match scores 50 standard',
      fit_score(J('Business Systems Analyst',
                  desc='Requires 3+ years of ServiceNow experience.')), 50)
check('SN dev + ITOM description scores 65 standard',
      fit_score(J('ServiceNow Developer',
                  desc='Configure CMDB and Discovery on the ServiceNow platform.')), 65)
check('senior SN ITOM Architect scores 85 high',
      fit_score(J('Senior ServiceNow ITOM Architect', desc='')), 85)
check('SN dev + GRC description scores 65 standard',
      fit_score(J('ServiceNow Developer',
                  desc='Configure GRC workflows on the ServiceNow platform.')), 65)
check('SN dev + SAM/HAM description scores 65 standard',
      fit_score(J('ServiceNow Developer',
                  desc='Administer SAM and HAM asset processes on the ServiceNow platform.')), 65)
check('senior SN dev + Now Assist description scores 85 high',
      fit_score(J('Senior ServiceNow Developer',
                  desc='Lead Now Assist implementations on the ServiceNow platform.')), 85)
check('AI cluster counted once (title wins over description)',
      fit_score(J('ServiceNow AI Engineer',
                  desc='Work on generative ai features on the ServiceNow platform.')), 80)
check('junior desc-tier match scores 35 low (still matches)',
      (fit_score(J('Junior Analyst',
                   desc='Administer ServiceNow tickets and support the platform team.')),
       job_matches(J('Junior Analyst',
                     desc='Administer ServiceNow tickets and support the platform team.'), TODAY)[0]),
      (35, True))
check('annotate_job attaches fit fields',
      (lambda j: (j['fit_score'], j['fit_tier']))(
          annotate_job(J('Senior ServiceNow Developer', desc=''), today=TODAY)),
      (75, 'high'))

# --- remote exclusion ------------------------------------------------------------
check('remote location rejected',
      job_matches(J('ServiceNow Developer', loc='Remote - United States'), TODAY),
      (False, 'remote'))
check('title (Remote) rejected',
      job_matches(J('ServiceNow Developer (Remote)', loc='Toronto, ON'), TODAY),
      (False, 'remote'))
check('leading Remote title rejected',
      job_matches(J('Remote ServiceNow Developer', loc='Austin, TX'), TODAY),
      (False, 'remote'))
check('Virtual, MN location rejected',
      job_matches(J('ServiceNow Developer', loc='Virtual, MN'), TODAY),
      (False, 'remote'))
check('Virtual Agent title is NOT remote',
      job_matches(J('Virtual Agent Developer', loc='Austin, TX',
                    desc='Build Virtual Agent on the ServiceNow platform.'), TODAY),
      (True, 'match'))
check('hybrid wins over remote location',
      job_matches(J('Hybrid ServiceNow Developer', loc='Remote; Toronto, ON'), TODAY),
      (True, 'match'))
check('workplace_type remote rejected',
      job_matches(J('ServiceNow Developer', loc='Austin, TX',
                    workplace_type='Remote'), TODAY), (False, 'remote'))
check('workplace_type hybrid passes',
      job_matches(J('ServiceNow Developer', loc='Remote',
                    workplace_type='Hybrid'), TODAY), (True, 'match'))
check('is_remote_only unit: bare remote', is_remote_only({'location': 'Remote'}), True)
check('is_remote_only unit: on-site passes',
      is_remote_only({'location': 'On-site, Austin, TX'}), False)
check('is_remote_only unit: unspecified passes',
      is_remote_only({'location': 'Not specified', 'title': 'ServiceNow Developer'}), False)

# --- v6 strictness preserved under v7 --------------------------------------------
check('v7 still rejects client-list name-drop',
      job_matches(J('Senior Developer',
                    desc='We have partnered with companies like Google, ServiceNow, Uber.'), TODAY),
      (False, 'relevance'))
check('v7 still rejects list boilerplate',
      job_matches(J('Graphic Designer',
                    desc='Nice-to-have familiarity with platforms such as Salesforce or ServiceNow.'), TODAY),
      (False, 'relevance'))
check('v7 still rejects competitor framing',
      job_matches(J('Renewal Account Manager',
                    desc='Position our BPM suite against ServiceNow and Pega.'), TODAY),
      (False, 'relevance'))

print(f'\n{PASS} passed, {FAIL} failed')
sys.exit(1 if FAIL else 0)
