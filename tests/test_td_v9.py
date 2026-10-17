"""Regression tests for matcher v9 (2026-10-14) — TD Bank false-positive burst.

On 2026-10-13 the Workday sweep matched 9 TD Bank roles, ALL with
non-ServiceNow titles, ALL from one board. The descriptions were fetched
live and the exact triggering sentences diagnosed. 8 of the 9 matched on
incidental ServiceNow mentions (ticket-raising, nice-to-have, "or
equivalent", familiarity lists, "experience using" among other tools,
use-as-system-of-record). The 9th (Senior Manager, Enterprise Data Quality
Management) is a genuine ServiceNow CMDB/SAM/HAM platform role — it
correctly still matches and is pinned as the exception.

Sentences below are the real TD sentences (company boilerplate trimmed).
Near-miss cases that must still MATCH are pinned alongside: a role whose
actual duties involve ServiceNow (administer/configure/develop/integrate
the platform) still passes, as do Now Assist / AI Control Tower titles,
GRC roles, and integration roles where ServiceNow is genuinely the job.

Run: python3 tests/test_td_v9.py
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from crawler.match import job_matches  # noqa: E402

TODAY = date(2026, 10, 14)
D = lambda n: (TODAY - timedelta(days=n)).isoformat()  # noqa: E731

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


def J(title, desc, loc='Toronto, ON', company='TD Bank', posted=D(1)):
    return {'company': company, 'title': title, 'description': desc,
            'location': loc, 'date_posted': posted}


# --- TD burst: the 8 incidental-mention cases must now be REJECTED --------
check('TD Data Engineer: raise ServiceNow requests (ticket-raising)',
      J('Data Engineer II - CPB Data Curation',
        desc=('Work closely with Release Management teams to support code '
              'packaging and deployment into higher environments. '
              'Raise ServiceNow requests and work with the Change '
              'Management team to support release management activities. '
              'Lead data engineering initiatives and capabilities.')),
      False, 'relevance')

check('TD Mulesoft: nice-to-have experience with ServiceNow',
      J('Mulesoft Software Engineer II',
        desc=('Strong verbal and written communication skills are essential. '
              'Self-motivated team player with high energy. '
              'Nice to have: experience with ServiceNow & financial industry. '
              'Build integrations between enterprise systems.')),
      False, 'relevance')

check('TD DBA: ServiceNow or equivalent ITSM platforms',
      J('Oracle / PostgreSQL Database Administrator',
        desc=('Operating systems & tools: Linux/Unix administration, '
              'enterprise monitoring platforms, capacity planning tools, '
              'observability and APM tools, ServiceNow or equivalent ITSM '
              'platforms. Preferred qualifications: experience supporting '
              'Oracle Exadata in large enterprise environments.')),
      False, 'relevance')

check('TD Vuln Governance: experience using SN module among other tools',
      J('Senior Information Security Analyst (Vulnerability Governance)',
        desc=('Experience using ServiceNow Security Operations module. '
              'Familiarity with application, infrastructure, or cloud '
              'security scanning tools such as Veracode, Snyk, Qualys VM, '
              'Wiz, or comparable platforms. Experience analyzing, '
              'validating, and reporting vulnerability data.')),
      False, 'relevance')

check('TD Secure Code Review: bare experience using ServiceNow',
      J('Senior Information Security Analyst (Secure Code Review)',
        desc=('Hands on experience conducting security focused static '
              'analysis using commercial SAST tools such as Checkmarx, '
              'Veracode, Fortify and SonarQube. Experience using ServiceNow. '
              'Strong analytical and problem solving skills.')),
      False, 'relevance')

check('TD Business Insights: familiarity with Jira, Confluence, ServiceNow',
      J('Business Insights Analyst II',
        desc=('Advanced proficiency in: Excel, data visualization, data '
              'analysis and reporting. Familiarity with Jira, Confluence, '
              'ServiceNow, and agile delivery tools. Experience working in '
              'agile delivery environments.')),
      False, 'relevance')

check('TD CCM: business-user of a ServiceNow module (use as system of record)',
      J('Information Security Specialist (Security Posture Insights)',
        desc=('As a key business and product partner for the ServiceNow '
              'Configuration Compliance Management module, the specialist '
              'defines reporting and workflow requirements, uses the '
              'platform to manage findings through closure, and develops '
              'dashboards, metrics and executive insights. Use ServiceNow '
              'Configuration Compliance Management as the system of record '
              'for findings, ownership, remediation tasks, exceptions, '
              'evidence, validation, escalation and closure. Define and '
              'prioritize ServiceNow Configuration Compliance requirements '
              'for data ingestion, findings normalization, assignment '
              'logic, remediation workflows, notifications, escalations. '
              'Partner with ServiceNow platform, data and engineering '
              'teams to improve Configuration Compliance integrations.')),
      False, 'relevance')

check('TD ETAM: hands-on depth + preferred certs, no SN duties',
      J('Senior Manager - ETAM - Technology Standards and Product Catalogue',
        desc=('10+ years in IT asset management, enterprise architecture '
              'or technology governance, with 5+ years leading teams. '
              'Hands on depth in ServiceNow TPM, TRM and APM, and working '
              'knowledge of SAM Pro, HAM Pro, CMDB and CSDM. Preferred: '
              'ServiceNow certifications (CIS APM, CIS SAM, CIS HAM, CSA). '
              'Experience with technology lifecycle management, standards '
              'and exceptions in a regulated environment.')),
      False, 'relevance')

# --- TD burst: the genuine exception still MATCHES ------------------------
check('TD EDQ: genuine SN platform role (owns Data Content Manager across SN modules)',
      J('Senior Manager, Enterprise Data Quality Management',
        desc=('The Senior Manager, Enterprise Data Quality Management owns '
              'and leads Data Content Manager as an enterprise capability '
              'across the ServiceNow modules that depend on trusted data. '
              'ServiceNow certifications relevant to platform '
              'administration, the Configuration Management Database, '
              'Application Portfolio Management, Hardware Asset Management, '
              'or Software Asset Management. Familiarity with the Common '
              'Service Data Model and ServiceNow relationship structures.')),
      True)

# --- Near-misses that must still MATCH ------------------------------------
check('genuine: administer ServiceNow CMDB',
      J('ITOM Engineer',
        desc='Administer ServiceNow CMDB and configure discovery patterns, credentials, and schedules.'),
      True)
check('genuine: configure ServiceNow workflows',
      J('Platform Engineer',
        desc='Configure ServiceNow workflows and implement approval automation for IT requests.'),
      True)
check('genuine: develop ServiceNow apps',
      J('Software Engineer',
        desc='Develop ServiceNow applications on the Now Platform, building catalog items and Flow Designer flows.'),
      True)
check('genuine: integrate ServiceNow (Mulesoft-style integration role)',
      J('Mulesoft Software Engineer II',
        desc='Build MuleSoft integrations that integrate ServiceNow with SailPoint for identity provisioning.'),
      True)
check('genuine: ServiceNow role noun in description',
      J('IT Analyst',
        desc='Act as ServiceNow administrator for incident and change management.'),
      True)
check('genuine: Now Assist title',
      J('Now Assist Developer', desc='Build conversational AI skills.'), True)
check('genuine: AI Control Tower title',
      J('AI Control Tower Engineer', desc='Govern model usage.'), True)
check('genuine: GRC role on ServiceNow + federal regulations passing mention',
      J('GRC Analyst',
        desc=('Implement ServiceNow GRC controls and manage risk '
              'assessments. Ensure compliance with federal regulations.')),
      True)
check('genuine: weak phrase + genuine sentence = match',
      J('Business Systems Analyst',
        desc=('Experience with ServiceNow required. You will administer '
              'the ServiceNow platform and configure ITSM workflows.')),
      True)
check('genuine: manage incidents in ServiceNow',
      J('ITSM Analyst',
        desc='Manage incidents in ServiceNow and support the platform team.'),
      True)
check('genuine: ServiceNow module name',
      J('Support Specialist',
        desc='Provide L2 support for the ServiceNow ITSM module.'), True)
check('genuine: must-have administration sentence',
      J('Administrator',
        desc='Must have ServiceNow administration skills.'), True)

# --- Targeted v9 exclusions -------------------------------------------------
check('excluded: nice-to-have ServiceNow development',
      J('Full Stack Developer',
        desc=('Build React and Node applications. Nice to have: ServiceNow '
              'development experience. Work in an agile team.')),
      False, 'relevance')
check('excluded: ServiceNow or similar ITSM tool',
      J('Help Desk Analyst',
        desc='Experience with ServiceNow or similar ITSM tool preferred.'),
      False, 'relevance')
check('excluded: ServiceNow as data source (develop insights from)',
      J('Reporting Analyst',
        desc='Develop actionable insights from ServiceNow data and build dashboards.'),
      False, 'relevance')
check('excluded: bare familiarity with ServiceNow',
      J('Data Analyst',
        desc='Familiarity with ServiceNow and agile delivery tools.'),
      False, 'relevance')
check('excluded: cert preference alone',
      J('Platform Analyst',
        desc='ServiceNow Certified System Administrator preferred.'),
      False, 'relevance')
check('excluded: uses ServiceNow for ticketing (end-user)',
      J('IT Analyst',
        desc='Our team uses ServiceNow for ticketing and change management.'),
      False, 'relevance')

print(f'\n{PASS} passed, {FAIL} failed')
sys.exit(1 if FAIL else 0)
