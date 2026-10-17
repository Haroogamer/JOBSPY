"""Tests for the v8 gov/clearance hardening (2026-10-13).

The 2026-10-13 20:41 run leaked two roles the old filter missed:
- Spear AI, "Meridian: Forward Deployed Infrastructure Engineer (Senior /
  Suitland, MD / Hybrid" — Suitland program site + TS/SCI in description.
- TRM Labs, "Forward Deployed Engineer - US National Security".

The filter now checks description-level clearance requirements and
gov-domain phrases, plus program-site markers in location/title — without
rejecting legitimate roles that mention "government clients" or "federal
regulations" in passing, security work without a clearance, or an explicit
"no clearance required".

Run: python3 tests/test_gov_v8.py
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from crawler.match import job_matches  # noqa: E402

TODAY = date(2026, 10, 13)
D = lambda n: (TODAY - timedelta(days=n)).isoformat()  # noqa: E731
SN_DESC = ("We are hiring a ServiceNow Developer to implement and configure "
           "workflows on the Now Platform.")

PASS = 0
FAIL = 0


def check(name, job, expected, expected_reason=None):
    global PASS, FAIL
    ok, reason = job_matches(job, today=TODAY)
    good = (ok == expected) and (expected_reason is None or reason == expected_reason)
    print(f'{"PASS" if good else "FAIL"} [{reason}] {name} '
          f'(expected {expected}, got {ok})')
    if good:
        PASS += 1
    else:
        FAIL += 1


def J(title, desc=SN_DESC, loc='Austin, TX', company='Acme', posted=D(1)):
    return {'company': company, 'title': title, 'description': desc,
            'location': loc, 'date_posted': posted}


# --- the two leaked roles (exact cases) -------------------------------------
SPEAR_DESC = ("Deploy and maintain infrastructure for the Meridian program at "
              "our Suitland, MD site. You will configure ServiceNow ITSM "
              "for cleared teams. Active TS/SCI clearance required. "
              "Applicants must be able to obtain a security clearance.")
check('Spear AI leaked role rejected (Suitland + TS/SCI)',
      J('Meridian: Forward Deployed Infrastructure Engineer (Senior / Suitland, MD / Hybrid',
        desc=SPEAR_DESC, loc='Suitland, MD', company='Spear AI'),
      False, 'government')
check('Spear AI site marker alone rejects (no clearance mention)',
      J('Meridian: Forward Deployed Infrastructure Engineer (Senior / Suitland, MD / Hybrid',
        desc=SN_DESC, loc='Suitland, MD', company='Spear AI'),
      False, 'government')
check('TRM Labs leaked role rejected (US National Security)',
      J('Forward Deployed Engineer - US National Security',
        desc='Support US national security customers. Configure ServiceNow '
             'workflows for mission teams.',
        loc='Washington, DC', company='TRM Labs'),
      False, 'government')
check('TRM Labs title alone rejects (bland description)',
      J('Forward Deployed Engineer - US National Security',
        desc=SN_DESC, loc='Washington, DC', company='TRM Labs'),
      False, 'government')

# --- clearance-requirement phrasing ----------------------------------------
for label, desc in [
    ('TS/SCI', 'ServiceNow role. Active TS/SCI clearance required.'),
    ('TS / SCI spaced', 'ServiceNow role. TS / SCI clearance required.'),
    ('Top Secret/SCI', 'ServiceNow role. Top Secret/SCI clearance required.'),
    ('active clearance', 'ServiceNow role. Active clearance required.'),
    ('ability to obtain', 'ServiceNow role. Must have ability to obtain a security clearance.'),
    ('eligible for clearance', 'ServiceNow role. Must be eligible for a security clearance.'),
    ('polygraph', 'ServiceNow role. CI polygraph required.'),
    ('classified information', 'ServiceNow role. Access to classified information required.'),
    ('hold a clearance', 'ServiceNow role. Must hold a security clearance.'),
    ('clearance eligibility', 'ServiceNow role. Clearance eligibility required.'),
]:
    check(f'clearance phrase rejected: {label}',
          J('ServiceNow Developer', desc=desc, loc='Arlington, VA'),
          False, 'government')

# --- gov-domain phrasing ----------------------------------------------------
for label, desc in [
    ('DoD customer', 'ServiceNow role supporting Department of Defense customers.'),
    ('intelligence community', 'ServiceNow role for intelligence community customers.'),
    ('federal agency', 'ServiceNow role supporting federal agencies.'),
    ('federal contract', 'ServiceNow role on a federal contract.'),
    ('government contract', 'ServiceNow role working on a government contract.'),
    ('US Government customer', 'ServiceNow role supporting U.S. Government customers.'),
]:
    check(f'gov-domain phrase rejected: {label}',
          J('ServiceNow Developer', desc=desc, loc='Arlington, VA'),
          False, 'government')

# --- other program sites ----------------------------------------------------
for site in ['Fort Meade, MD', 'Quantico, VA', 'Fort Belvoir, VA',
             'Annapolis Junction, MD', 'Langley, VA',
             'Joint Base Andrews, MD']:
    check(f'program site rejected: {site}',
          J('ServiceNow Developer', desc=SN_DESC, loc=site),
          False, 'government')

# --- near-misses that must still match --------------------------------------
check('GRC role with federal regulations + government clients passes',
      J('ServiceNow GRC Analyst',
        desc='Implement compliance controls for federal regulations (SOX, '
             'HIPAA). Our consultancy serves government clients across '
             'healthcare and finance. Configure ServiceNow GRC/IRM.'),
      True)
check('security workflow role without clearance passes',
      J('ServiceNow SecOps Engineer',
        desc='Build security workflows, vulnerability response, and SIEM '
             'integrations on ServiceNow SecOps.'),
      True)
check('explicit no clearance required passes',
      J('ServiceNow Developer',
        desc='ServiceNow Developer. No clearance required. Configure ITSM workflows.'),
      True)
check('clearance not required passes',
      J('ServiceNow Admin',
        desc='ServiceNow Admin. Clearance not required.'),
      True)
check('does not require a clearance passes',
      J('ServiceNow Developer',
        desc='ServiceNow Developer. This role does not require a security clearance.'),
      True)
check('work without a clearance passes',
      J('ServiceNow Developer',
        desc='ServiceNow Developer. Work without a clearance; configure workflows.'),
      True)
check('public sector passing mention passes',
      J('ServiceNow Developer',
        desc='ServiceNow Developer serving public sector and commercial '
             'clients. Implement ITSM.'),
      True)
check('medical clearance required (different clearance) passes',
      J('ServiceNow Developer',
        desc='ServiceNow Developer. Medical clearance required for site access. '
             'Configure ITSM workflows.'),
      True)
check('Canadian national-security role still passes (CA carve-out)',
      J('Forward Deployed Engineer - National Security',
        desc=SN_DESC, loc='Ottawa, ON', company='Acme'),
      True)

print(f'\n{PASS} passed, {FAIL} failed')
sys.exit(1 if FAIL else 0)
