"""Job matcher — genuine ServiceNow relevance, fresh postings only.

Rules (user-defined, 2026-09-27; strict relevance since 2026-10-11 at user
request — the passing-mention tier kept surfacing noise like a front-end
role matched only on "ServiceNow" in the client's client list;
RETARGETED 2026-10-13 to a senior, AI-heavy ServiceNow profile;
v9 2026-10-14: TD Bank burst — 9 roles matched on incidental mentions):
  1. RELEVANCE — two tracks, either one qualifies:
       a) SERVICENOW: a ServiceNow-family term ("servicenow",
          "service now", "now platform") in the TITLE, OR the description
          shows the job genuinely involves ServiceNow — STRONG evidence:
          a ServiceNow role noun ("ServiceNow administrator"), the
          ServiceNow platform itself, a module name ("ServiceNow ITSM"),
          a ServiceNow-product mention ("Now Assist", "AI Control
          Tower"), or a sentence where the role DOES ServiceNow work: a
          strong platform verb (administer, configure, develop, implement,
          build, integrate, ...) ADJACENT to the ServiceNow mention
          (within 5 words). WEAK evidence alone does NOT match: bare
          experience / familiarity / skill wordings ("experience with
          ServiceNow"), "ServiceNow preferred", and certifications —
          those only count alongside a strong signal. EXCLUDED:
          client-list name-drops, competitor framing ("migrate from
          ServiceNow"), list boilerplate ("platforms such as Salesforce
          or ServiceNow", "ServiceNow or equivalent"), nice-to-have
          clauses ("nice to have experience with ServiceNow"),
          end-user usage ("raise ServiceNow requests", "our team uses
          ServiceNow for ticketing"), and ServiceNow-as-data-source
          ("develop insights from ServiceNow") — none of those is a
          ServiceNow job.
          ServiceNow-PRODUCT titles also qualify without the brand in the
          title: "Now Assist" and "AI Control Tower" are ServiceNow
          products, so those titles match (and bare mentions in a
          description count as genuine). Generic AI titles ("GenAI
          Engineer", "AI Architect") do NOT match on title alone — the
          description must still show ServiceNow involvement.
       b) FORWARD DEPLOYED: title contains "forward deployed" -> always
          relevant. Otherwise the description must name a forward-deployed
          role ("forward deployed engineer", "forward deployed architect",
          ...). A passing mention of a company's deployment model does NOT
          match.
     No company-type filter (startups and enterprises alike). Junior and
     generic ServiceNow roles still MATCH — seniority only affects
     RANKING (see fit_score), never eligibility.
  2. LOCATION — United States or Canada. Toronto/GTA is flagged (not filtered)
     so local hits stand out in alerts.
  3. REMOTE — on-site / hybrid only. A posting that is remote-only
     (location, title, or workplace type says remote with no hybrid /
     on-site marker) is rejected. "Virtual Agent" titles are NOT remote.
  4. GOVERNMENT — US federal / government / clearance roles are rejected.
     Canadian government and Canadian clearance (Reliability, etc.) pass.
     (v8: description-level clearance requirements, gov-domain phrases, and
     program-site markers; negated "no clearance required" does not reject;
     "government clients" / "federal regulations" passing mentions pass.)
  5. FRESHNESS — every match stays eligible for 30 days, so the standing
     stock of open roles surfaces — not just the newest flow. Unparseable
     dates pass (optimistic) — dropping a job over a date format would be
     worse than including it.
  6. TIER — 'core' = ServiceNow/FD/Now-Assist/AI-Control-Tower term in the
     TITLE (alerts get a star); 'desc' = genuine description-level
     relevance. Every alert is a real ServiceNow / Forward Deployed role
     now — there is no mention tier.
  7. FIT — fit_score ranks matches for the senior AI-heavy target profile:
     senior titles (Senior/Lead/Architect/Principal/Staff) and specialty
     clusters (AI, GRC/IRM, ITOM/CMDB, SAM/HAM, integrations, SPM,
     upgrades) boost the score; junior titles lower it. Ranking never
     filters — it only orders what surfaces first.

How to maintain: every rule lives in one of the CAPITALIZED lists below.
Regression tests in tests/test_match.py pin the behavior.

Pipeline (job_matches):
  relevance -> sales-title -> location -> remote -> government -> freshness
"""

# Bump this whenever the matching rules change. The Workday sweep caches
# "checked but not matched" URLs to avoid re-fetching descriptions every
# run; a version bump tells it to re-evaluate everything once.
# v6 (2026-10-11): the v5 sentence fallback was too loose — the first v5
# ATS run fired 50 alerts, most matching "nice-to-have familiarity with
# platforms such as Salesforce or ServiceNow" boilerplate. A description
# sentence now counts only when the role genuinely works with ServiceNow
# (work verbs: use, administer, develop, configure, ...), and competitor
# framing ("position against ServiceNow", "migrate from ServiceNow") plus
# list-membership ("platforms such as X or ServiceNow") are excluded.
# v8 (2026-10-13): gov/clearance filter hardened — description-level
# clearance-requirement phrasing (TS/SCI, active clearance, "clearance
# required", polygraph, classified work), gov-domain phrases ("national
# security", "department of defense", "intelligence community", ...), and
# gov program-site markers (Suitland, Fort Meade, ...) in location/title.
# Negated "no clearance required" does not reject; "government clients"
# / "federal regulations" passing mentions still pass.
# v10 (2026-10-14): user decision — the Forward Deployed lane is dropped
# from alerts entirely. Alerts are ServiceNow-family roles only
# (ServiceNow title terms, Now Assist / AI Control Tower product titles,
# or a description that genuinely shows ServiceNow work). Freshness
# window tightened 30 -> 7 days: roles older than a week aren't worth
# alerting on anymore.
# v11 (2026-10-15): sales-title filter. A Genpact "Business Development
# Executive 3" (New York) matched v10 because its description said
# "develop opportunities for SaaS solutions (ServiceNow, Salesforce
# etc.)" — "develop" adjacent to the ServiceNow mention passed the v9
# sentence test, but the role is a SALES seat that sells ServiceNow, not
# a ServiceNow role. Titles that are sales jobs (business development,
# sales, account executive/manager, SDR/BDR) are rejected outright.
# v12 (2026-10-16): parenthetical example-list blanking. Two TD Bank
# "Application Delivery Engineer II" (Mount Laurel NJ) postings matched
# v11 on "Enterprise ticketing tools (e.g., ServiceNow)" — an
# experience-with-tools example list — because "Integration" in
# "Middleware Integration platforms" sat two words after the mention
# and counted as a strong verb. ServiceNow as one enumerated example
# inside (e.g./such as/like) parens is now blanked from the description
# BEFORE sentence-splitting (the period in "e.g." would otherwise split
# the sentence and hide the marker from a per-sentence exclusion).
MATCHER_VERSION = 12

import re
from datetime import date, datetime, timezone

# ---------------------------------------------------------------------------
# 1. Relevance: broad by user request (2026-09-30) — any ServiceNow mention
#    counts, no experience-depth requirement, no company-type filter.
#    Forward Deployed keeps its two-path shape (title auto-matches;
#    description must name a forward-deployed role). Word-boundary matched
#    so "now platform" can't match "know platform" / "snow platform".
# ---------------------------------------------------------------------------
RELEVANCE_TERMS = [
    r'\bservicenow\b',
    r'\bservice\s+now\b',      # "Service Now" with a space
    r'\bnow\s+platform\b',     # "Now Platform"
    r'\bnowplatform\b',
]

# ServiceNow-PRODUCT title terms (v7 retarget): "Now Assist" and "AI Control
# Tower" are ServiceNow products, so roles titled for them match even
# without the brand in the title ("Now Assist Developer", "AI Control
# Tower Engineer"). Generic AI titles ("GenAI Engineer", "AI Architect") do
# NOT match on title alone — the description must show ServiceNow
# involvement, same as any other generic title.
PRODUCT_TITLE_TERMS = [
    r'\bnow\s+assist\b',
    r'\bai\s+control\s+tower\b',
]

# STRONG evidence phrases (v9): ServiceNow role nouns. If one of these
# appears in the description, the job IS a ServiceNow role — no second
# signal needed. NOTE: "ServiceNow platform" / "Now Platform" are
# deliberately NOT here: the bare phrase matches team names ("partner
# with ServiceNow platform teams" — TD Bank CCM posting) and runtime
# statements ("runs on the ServiceNow platform"), not ServiceNow work.
# Genuine platform work ("build apps on the ServiceNow platform") still
# passes via the sentence test — "build" sits adjacent to the mention.
STRONG_PHRASES = [
    # role nouns: "ServiceNow X" as the job itself
    'servicenow developer', 'servicenow administrator', 'servicenow admin',
    'servicenow consultant', 'servicenow architect', 'servicenow engineer',
    'servicenow analyst', 'servicenow specialist', 'servicenow expert',
    'servicenow lead', 'servicenow manager', 'servicenow owner',
    'servicenow sme', 'servicenow professional',
]

# WEAK evidence phrases (v9): bare experience / familiarity / skill /
# requirement / certification wordings. These are INTENTIONALLY NOT
# consulted by the matcher: a posting that says only "experience with
# ServiceNow" — with no ServiceNow duties, no module, no role noun — is
# not a ServiceNow role. (TD Bank burst, 2026-10-14: a Mulesoft dev with
# "nice to have experience with ServiceNow", a security analyst with
# "experience using ServiceNow" among five other tools, a DBA with
# "ServiceNow or equivalent".) Genuine matches always carry a stronger
# signal, so dropping these as standalone evidence loses nothing real.
# Kept here to document the decision — do not re-add them to the matcher
# without a second-signal requirement.
WEAK_PHRASES = [
    # bare platform mentions (see STRONG_PHRASES note — team names and
    # runtime statements, not ServiceNow work)
    'servicenow platform', 'nowplatform',
    # experience / knowledge wordings
    'servicenow experience', 'experience with servicenow',
    'experience in servicenow', 'experience on servicenow',
    'experience using servicenow', 'servicenow background',
    'servicenow skills', 'servicenow skill', 'knowledge of servicenow',
    'servicenow knowledge', 'familiarity with servicenow',
    'familiar with servicenow', 'know servicenow', 'knows servicenow',
    'hands on servicenow', 'working knowledge of servicenow',
    'working with servicenow', 'work with servicenow',
    'works with servicenow', 'proficiency in servicenow',
    'proficient in servicenow', 'strong servicenow', 'solid servicenow',
    'deep servicenow', 'extensive servicenow',
    # requirement wordings
    'servicenow required', 'servicenow preferred', 'servicenow desired',
    # ServiceNow certification names (CSA/CAD/CIS) — a cert preference
    # alone is not a ServiceNow role; genuine roles carry duties too.
    'servicenow certified', 'certified servicenow',
    'servicenow certification', 'servicenow certifications',
    'certified system administrator',
    'certified application developer', 'certified implementation specialist',
]

# ServiceNow module names following the brand: "ServiceNow ITSM", ...
MODULE_RES = [
    r'\bservicenow\s+(itsm|itom|itbm|hrsd|csm|fsm|grc|irm|secops|ppm|spm|cmdb|'
    r'discovery|devops|app\s+engine)\b',
]

# ---------------------------------------------------------------------------
# Forward Deployed (REMOVED 2026-10-14, v10): the user dropped the FDE lane
# from alerts — ServiceNow-family roles only now. Kept as a changelog note
# so nobody re-adds it without asking.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 2. Locations: United States + Canada. Everything else is out.
# ---------------------------------------------------------------------------
US_STATE_NAMES = [
    'alabama', 'alaska', 'arizona', 'arkansas', 'california', 'colorado',
    'connecticut', 'delaware', 'florida', 'georgia', 'hawaii', 'idaho',
    'illinois', 'indiana', 'iowa', 'kansas', 'kentucky', 'louisiana', 'maine',
    'maryland', 'massachusetts', 'michigan', 'minnesota', 'mississippi',
    'missouri', 'montana', 'nebraska', 'nevada', 'new hampshire', 'new jersey',
    'new mexico', 'new york', 'north carolina', 'north dakota', 'ohio',
    'oklahoma', 'oregon', 'pennsylvania', 'rhode island', 'south carolina',
    'south dakota', 'tennessee', 'texas', 'utah', 'vermont', 'virginia',
    'washington', 'west virginia', 'wisconsin', 'wyoming',
    'district of columbia', 'washington dc',
]

US_MARKERS = [
    'united states', 'usa', r'u\.s\.', 'new york', 'michigan', 'chicago',
    'dallas', 'atlanta', 'washington', 'virginia',
]

CANADA_MARKERS = [
    'canada', 'toronto', 'vancouver', 'montreal', 'ottawa', 'calgary',
    'edmonton', 'winnipeg', 'quebec', 'mississauga',
]

# Toronto + GTA municipalities — flagged in alerts, not filtered.
GTA_MARKERS = [
    'toronto', 'gta', 'greater toronto', 'mississauga', 'brampton',
    'scarborough', 'north york', 'etobicoke', 'vaughan', 'markham',
    'richmond hill', 'oakville', 'burlington', 'milton', 'ajax', 'pickering',
    'whitby', 'oshawa', 'newmarket', 'aurora', 'georgetown', 'halton',
    'peel region', 'york region', 'durham region',
]

# Client-list / partnership name-drop constructions. A sentence matching one
# of these is a brand mention, not a ServiceNow job ("we've partnered with
# companies like Google, ServiceNow, Uber"). Note "such as"/"including" are
# deliberately NOT excluded — "tools such as ServiceNow, Jira" is a genuine
# in-job mention. Bare partnership ("As a ServiceNow partner...") passes:
# it signals the work itself is ServiceNow.
_CLIENTLIST_MARKERS = [
    r'clients?\s+like', r'customers?\s+like', r'companies\s+like',
    r'trusted\s+by', r'client\s+(roster|list)', r'our\s+clients?\b',
]

# Sentence-level strong platform verbs (v9): the role must DO ServiceNow
# work — administer, build, configure, develop, implement, integrate,
# ... "Use" / "work with" / "utilize" are NOT strong verbs: "our team uses
# ServiceNow for ticketing" and "raise ServiceNow requests" are end-user
# usage, not ServiceNow work (TD Bank burst, 2026-10-13). Noun forms that
# caused false positives are excluded: "configuration" matched the
# "Configuration Compliance" module name, "delivery" matched the
# "ServiceNow delivery" team name — but the genuine noun forms
# (administration, development, implementation, maintenance, deployment,
# integration, configuration when it is the work itself) stay. The verb
# must sit within ±5 words of the ServiceNow mention (see
# _has_platform_verb_near_sn) — a verb glued to some other object in a
# run-on TD chunk ("manage findings", "maintain a backlog", "develop
# insights") does not count.
_STRONG_VERB_TOKENS = {
    'administer', 'administers', 'administering', 'administration',
    'develop', 'develops', 'developing', 'development',
    'build', 'builds', 'building',
    'configure', 'configures', 'configuring', 'configuration',
    'implement', 'implements', 'implementing', 'implementation',
    'support', 'supports', 'supporting',
    'maintain', 'maintains', 'maintaining', 'maintenance',
    'manage', 'manages', 'managing',
    'operate', 'operates', 'operating',
    'deploy', 'deploys', 'deploying', 'deployment',
    'integrate', 'integrates', 'integrating', 'integration',
    'customize', 'customizes', 'customizing',
    'extend', 'extends', 'extending',
    'deliver', 'delivers', 'delivering',
    # "Lead ServiceNow implementations / lead generative AI on the
    # ServiceNow platform" is genuine ServiceNow work — leading the
    # platform work counts. (Competitor framing still excludes
    # "lead the migration from ServiceNow": that check runs first.)
    'lead', 'leads', 'leading',
}

# Competitor framing: ServiceNow as the thing being beaten, replaced, or
# left ("position our suite against ServiceNow", "migrate from ServiceNow").
# A sales/competitor mention is not a ServiceNow job.
_COMPETITOR_RES = [
    r'\b(against|versus|vs\.?|unlike|alternative\s+to)\s+servicenow\b',
    r'\breplac\w*\s+servicenow\b',
    r'\bmigrate\w*\s+(from|off)\s+servicenow\b',
    r'\bdisplace\w*\s+servicenow\b',
    r'\bcompete\w*\s+(with|against)\s+servicenow\b',
]

# List-membership: ServiceNow as one example among others
# ("platforms such as Salesforce or ServiceNow") — not role relevance.
# "ServiceNow or equivalent" is the same shape: ServiceNow as one
# interchangeable option ("ServiceNow or equivalent ITSM platforms" —
# TD Bank DBA posting, 2026-10-13).
_LIST_RES = [
    r'\b(such\s+as|including|e\.g\.|for\s+example)\b.*\bservicenow\b',
    r'\blike\b.*\bservicenow\b',
    r'\bservicenow\s+or\s+(equivalent|similar|comparable|other)\b',
]

# Disqualifies the location even when "remote" is present
# ("Remote AUS", "Remote EMEA", ...).
BLOCKED_LOCATIONS = [
    'india', 'uk', 'united kingdom', 'england', 'germany', 'france', 'spain',
    'netherlands', 'singapore', 'australia', 'philippines', 'mexico', 'brazil',
    'ireland', 'poland', 'romania', 'czech republic', 'hungary', 'israel',
    'pakistan', 'uae', 'united arab emirates', 'south africa', 'colombia',
    'argentina', 'portugal', 'italy', 'sweden', 'denmark', 'norway',
    'japan', 'tokyo', 'korea', 'seoul',
    'europe', 'emea', 'apac', 'latam', 'anz', 'aus',
]

_US_ABBR = re.compile(
    r'\b[A-Za-z]+(?:[ .\'-][A-Za-z]+)*,\s*'
    r'(al|ak|az|ar|ca|co|ct|de|fl|ga|hi|ia|id|il|in|ks|ky|la|ma|md|me|mi|mn|mo|ms|mt|'
    r'nc|nd|ne|nh|nj|nm|nv|ny|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|va|vt|wa|wi|wv|wy|dc)\b',
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# 3. US government exclusion. Checked against company + title always, and
#    against the description for clearance-specific phrases. Only applied to
#    US-located jobs — Canadian government / clearance roles still pass.
#    (v8, 2026-10-13: the 20:41 run leaked two roles because the old filter
#    only checked company/title for gov terms and the description for a
#    narrow clearance list. A "TS/SCI" role in Suitland, MD and a "US
#    National Security" role both passed. The filter now also checks the
#    description for clearance-requirement phrasing and gov-domain phrases,
#    and the location/title for gov program-site markers.)
# ---------------------------------------------------------------------------
GOVERNMENT_TERMS = [
    'federal', 'government', 'dod', 'department of defense',
]

CLEARANCE_TERMS = [
    'security clearance', 'secret clearance', 'top secret', 'public trust',
]

# Clearance REQUIREMENT phrasing: the role demands a clearance ("TS/SCI",
# "active clearance", "clearance required", "ability to obtain a
# clearance", polygraph, classified work). Checked against title and
# description AFTER stripping negations ("no clearance required").
_CLEARANCE_REQUIREMENT_RES = [
    r'\bts\s*/\s*sci\b',
    r'\btop\s+secret\s*/\s*sci\b',
    r'\bsci\s+clearance\b',
    r'\bsci\s+eligib\w*\b',
    r'\bactive\s+clearance\b',
    # "clearance required/needed" — but NOT "medical/manager/change
    # clearance required" (a different kind of clearance).
    r'(?<!medical\s)(?<!manager\s)(?<!change\s)(?<!stakeholder\s)'
    r'\bclearance\s+(required|requirement|needed|necessary)\b',
    r'\b(security\s+)?clearance\s+eligib\w*\b',
    r'\b(hold|have|possess|obtain|maintain)\s+(a\s+|an\s+|the\s+)?'
    r'(active\s+)?security\s+clearance\b',
    r'\bability\s+to\s+obtain\s+(a\s+|an\s+)?(security\s+)?clearance\b',
    r'\b(eligible|eligibility)\s+for\s+(a\s+|an\s+)?(security\s+)?clearance\b',
    r'\bpolygraph\b',
    r'\bclassified\s+(work|information|systems?|data|programs?|projects?|materials?|networks?)\b',
]

# Gov-domain phrases in a title or description: the work itself is US
# national-security / defense / federal-agency work. Deliberately NOT bare
# "federal" or "government" — a GRC role mentioning "federal regulations"
# or "government clients" in passing is not a government job.
_GOV_DOMAIN_RES = [
    r'\bnational\s+security\b',
    r'\bdepartment\s+of\s+defense\b',
    r'\bdod\b',
    r'\bintelligence\s+community\b',
    r'\bfederal\s+(agency|agencies|contract\w*)\b',
    r'\b(u\.s\.|us|united\s+states)\s+government\s+(customers?|clients?|agenc(y|ies))\b',
    r'\bgovernment\s+contract\w*\b',
]

# Gov program sites: intel / military enclaves where a posting is
# effectively a government-site role (Suitland Federal Center, Fort Meade /
# NSA, Quantico, Fort Belvoir, ...). Checked against location + title
# only — a passing "near Fort Meade" in a description is not the job site.
_GOV_SITE_TERMS = [
    'suitland', 'fort meade', 'fort belvoir', 'quantico',
    'annapolis junction', 'langley', 'joint base andrews',
    'washington navy yard',
]

# Negated clearance mentions: the role explicitly does NOT need a
# clearance ("no clearance required"). Stripped before the clearance
# checks so these roles still pass.
_CLEARANCE_NEGATION_RES = [
    r'\bno\s+(security\s+)?clearance\s+(required|needed|necessary)\b',
    r'\bclearance\s+not\s+(required|needed|necessary)\b',
    r'\bnot\s+require\w*\s+(a\s+|an\s+|any\s+)?(security\s+)?clearance\b',
    r"\bn['’]t\s+require\w*\s+(a\s+|an\s+|any\s+)?(security\s+)?clearance\b",
    r'\bwithout\s+(a\s+|an\s+|any\s+)?(security\s+)?clearance\b',
    r'\bno\s+clearance\b',
]

# ---------------------------------------------------------------------------
# 4. Freshness: max age in days — every match is a genuine ServiceNow /
#    Forward Deployed role now, so all stay eligible for 30 days and the
#    standing stock of open roles surfaces, not just the newest flow.
# ---------------------------------------------------------------------------
MAX_AGE_DAYS = 7


def _wordlist(terms):
    return re.compile('|'.join(rf'(?:{t})' for t in terms), re.IGNORECASE)


def _norm(text):
    """Lowercase + collapse variants so phrases match uniformly."""
    t = (text or '').lower().replace('-', ' ')
    t = re.sub(r'\bservice\s+now\b', 'servicenow', t)
    t = re.sub(r'\bnow\s+platform\b', 'nowplatform', t)
    return t


def _phrase_re(phrase):
    return r'\b' + r'\s+'.join(re.escape(w) for w in phrase.split()) + r'\b'


_RELEVANCE_RE = _wordlist(RELEVANCE_TERMS)
_PRODUCT_TITLE_RE = _wordlist(PRODUCT_TITLE_TERMS)
_STRONG_PHRASE_RE = re.compile('|'.join(_phrase_re(p) for p in STRONG_PHRASES))
_MODULE_RE = _wordlist(MODULE_RES)
_CITIZEN_RE = re.compile(r'\bcitizen\s+developer\b')
_LOWCODE_RE = re.compile(r'\b(low\s+code|no\s+code|nocode)\b')
_BLOCKED_RE = _wordlist([rf'\b{t}\b' for t in BLOCKED_LOCATIONS])
_US_MARKER_RE = _wordlist(US_MARKERS)
_CA_MARKER_RE = _wordlist([rf'\b{t}\b' for t in CANADA_MARKERS])
_GTA_RE = _wordlist([rf'\b{t}\b' for t in GTA_MARKERS])
_STATE_RE = _wordlist([rf'\b{s}\b' for s in US_STATE_NAMES])
_GOV_RE = _wordlist([rf'\b{t}\b' for t in GOVERNMENT_TERMS])
_CLEARANCE_RE = _wordlist(CLEARANCE_TERMS)
_CLEARANCE_REQ_RES_COMPILED = [re.compile(p, re.IGNORECASE) for p in _CLEARANCE_REQUIREMENT_RES]
_GOV_DOMAIN_RE = re.compile('|'.join(_GOV_DOMAIN_RES), re.IGNORECASE)
_GOV_SITE_RE = _wordlist([rf'\b{t}\b' for t in _GOV_SITE_TERMS])
_CLEARANCE_NEGATION_RES_COMPILED = [re.compile(p, re.IGNORECASE) for p in _CLEARANCE_NEGATION_RES]
_CLIENTLIST_RE = _wordlist(_CLIENTLIST_MARKERS)
_COMPETITOR_RE = _wordlist(_COMPETITOR_RES)
_LIST_RE = _wordlist(_LIST_RES)


# ---------------------------------------------------------------------------
# Relevance
# ---------------------------------------------------------------------------
def _strip_nice_to_have(text):
    """Remove "nice to have" clauses before matching.

    A ServiceNow mention that appears only inside a nice-to-have clause
    ("nice to have experience with ServiceNow & financial industry" — TD
    Bank Mulesoft posting, 2026-10-13) is a preference, not a duty, and
    must not match. The clause runs to the next sentence boundary or 150
    chars, whichever comes first. A genuine role keeps its duties, so
    stripping only removes the preference clause.
    """
    return re.sub(r'\bnice[\s-]*to[\s-]*have\b[^.!?\n;]{0,150}', ' ', text)


def _has_platform_verb_near_sn(sent):
    """True when a strong platform verb sits within ±5 words of a
    ServiceNow mention in this sentence.

    TD descriptions are run-on chunks with no sentence boundaries, so a
    verb anywhere in the "sentence" proves nothing ("manage findings",
    "maintain a backlog", "develop insights" all sit far from the
    ServiceNow mention and apply to other objects). Only a verb ADJACENT
    to ServiceNow counts. Two guards:
    - Module/discipline/team names that contain verb-like words are
      blanked first: "configuration compliance" / "configuration
      management" (module/discipline) and "servicenow delivery"
      (team name) must not fire the "configuration" / "delivery" verbs.
    - "from ServiceNow" is ServiceNow-as-data-source ("develop insights
      from ServiceNow", "migrate data from ServiceNow") — the mention
      does not count even with a nearby verb.
    """
    s = re.sub(r'\bconfiguration\s+(compliance|management)\b', ' ', sent)
    s = re.sub(r'\bservicenow\s+delivery\b', ' ', s)
    tokens = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", s)
    for i, tok in enumerate(tokens):
        if tok not in ('servicenow', 'nowplatform'):
            continue
        if any(tokens[j] == 'from' for j in range(max(0, i - 2), i)):
            continue
        if any(w in _STRONG_VERB_TOKENS
               for w in tokens[max(0, i - 5):i + 6]):
            return True
    return False


def _genuine_sentence(sent):
    """A description sentence genuinely involves ServiceNow in the role.

    The role must DO ServiceNow work: a strong platform verb adjacent to
    the ServiceNow mention. Excluded: client-list name-drops, competitor
    framing ("against ServiceNow", "migrate from ServiceNow"),
    list-membership ("platforms such as Salesforce or ServiceNow",
    "ServiceNow or equivalent"), end-user usage, and ServiceNow as a
    mere data source.
    """
    if 'servicenow' not in sent and 'nowplatform' not in sent:
        return False
    if _CLIENTLIST_RE.search(sent):
        return False
    if _COMPETITOR_RE.search(sent):
        return False
    if _LIST_RE.search(sent):
        return False
    return _has_platform_verb_near_sn(sent)


def _has_genuine_sn_desc(description):
    """True when the description shows the job genuinely involves ServiceNow.

    STRONG evidence: a ServiceNow role noun ("ServiceNow administrator"),
    the ServiceNow platform, a module name ("ServiceNow ITSM"), a bare
    mention of a ServiceNow product ("Now Assist", "AI Control Tower" —
    specific products, not generic brand name-drops), or a sentence where
    the role does ServiceNow work (strong platform verb adjacent to the
    mention). Client-list name-drops, competitor mentions, "such as X or
    ServiceNow" / "ServiceNow or equivalent" list boilerplate, nice-to-have
    clauses, end-user usage, and bare experience/familiarity wordings are
    excluded — none of those is a ServiceNow job.
    """
    text = _norm(description or '')
    if not text:
        return False
    text = _strip_nice_to_have(text)
    # Blank parenthetical example enumerations: "ticketing tools (e.g.,
    # ServiceNow)" — ServiceNow as one enumerated example among
    # tools/products is list boilerplate, not a ServiceNow role (TD Bank
    # burst, 2026-10-16: "Enterprise ticketing tools (e.g., ServiceNow)").
    # Done on the WHOLE text before sentence-splitting: the period in
    # "e.g." splits sentences, which would otherwise hide the marker from
    # a per-sentence exclusion. Only fires when ServiceNow sits INSIDE
    # the example parens, so genuine cases are untouched ("Administer
    # ServiceNow (ITSM, HRSD)" keeps its evidence outside the parens).
    text = re.sub(
        r'\(\s*(e\.?g?\.?|such\s+as|including|like)\s*,?\s*'
        r'[^)]*\bservicenow\b[^)]*\)', ' ', text)
    if _STRONG_PHRASE_RE.search(text) or _MODULE_RE.search(text):
        return True
    if _PRODUCT_TITLE_RE.search(text):
        return True
    return any(_genuine_sentence(s) for s in re.split(r'[.!?\n]+', text))


def is_relevant(title, description):
    """True when the job is a ServiceNow-family role.

    - a ServiceNow-family term OR a ServiceNow-product term
      ("Now Assist", "AI Control Tower") in the TITLE, or
    - the description shows the job genuinely involves ServiceNow (see
      _has_genuine_sn_desc).
    Client-list name-drops do NOT match.
    (v10: the Forward Deployed lane was removed per user request —
    ServiceNow-family roles only.)
    """
    title = title or ''
    if _RELEVANCE_RE.search(title) or _PRODUCT_TITLE_RE.search(title):
        return True
    return _has_genuine_sn_desc(description)


def title_might_match(title):
    """Cheap title pre-filter for the Workday crawler: is it worth spending
    a detail request on this title? Broad on purpose — any ServiceNow-family
    term or ServiceNow-product term qualifies. (Kept the old name so
    crawler/workday.py is unchanged.)"""
    title = title or ''
    return bool(_RELEVANCE_RE.search(title) or _PRODUCT_TITLE_RE.search(title))


def match_tier(job):
    """'core' for ServiceNow / ServiceNow-product terms in the TITLE
    (alerts get a star), 'desc' for genuine description-level relevance
    (experience/module phrases, real in-job ServiceNow sentences, or a
    ServiceNow-product mention). There is no mention tier: every match is
    a real ServiceNow role since 2026-10-11.
    (v10: Forward Deployed no longer matches.)
    """
    title = job.get('title') or ''
    if _RELEVANCE_RE.search(title) or _PRODUCT_TITLE_RE.search(title):
        return 'core'
    return 'desc'


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------
def location_region(location, title=''):
    """'us', 'ca', or None. Bare 'remote' with no country attached -> 'us'."""
    text = f'{location or ""} {title or ""}'.lower()
    if _BLOCKED_RE.search(text):
        return None
    if _CA_MARKER_RE.search(text):
        return 'ca'
    if _US_MARKER_RE.search(text):
        return 'us'
    if _STATE_RE.search(text):
        return 'us'
    if _US_ABBR.search(text):
        return 'us'
    if re.search(r'\bremote\b', text):
        return 'us'
    return None


def is_gta(location, title=''):
    """True if the job looks Toronto/GTA-based (flagged, not filtered)."""
    text = f'{location or ""} {title or ""}'.lower()
    return bool(_GTA_RE.search(text))


# ---------------------------------------------------------------------------
# Remote (v7): on-site / hybrid only. A posting is remote-only when the
# location, title, or workplace type says remote with no hybrid / on-site
# marker anywhere. "Virtual Agent" titles are NOT remote — only the word
# "virtual" in a LOCATION ("Virtual, MN") counts, and title matching
# requires an explicit "(Remote)" / leading / trailing "remote".
# ---------------------------------------------------------------------------
_ONSITE_RES = [
    r'\bhybrid\b',
    r'\bon[\s-]?site\b',
    r'\bin[\s-]?office\b',
    r'\bin[\s-]?person\b',
    r'\boffice[\s-]?based\b',
]
_REMOTE_LOC_RES = [
    r'\bremote\b',
    r'\bwork\s*from\s*home\b',
    r'\bwfh\b',
    r'\bvirtual\b',
]
_REMOTE_TITLE_RES = [
    r'\(\s*remote\s*\)',
    r'^\s*remote[\s\-–—,:]',
    r'[\s\-–—,:]remote\s*$',
]
_ONSITE_RES_COMPILED = [re.compile(p) for p in _ONSITE_RES]
_REMOTE_LOC_RES_COMPILED = [re.compile(p) for p in _REMOTE_LOC_RES]
_REMOTE_TITLE_RES_COMPILED = [re.compile(p) for p in _REMOTE_TITLE_RES]


def is_remote_only(job):
    """True when the posting is remote-only (no hybrid / on-site marker)."""
    loc = (job.get('location') or '').lower()
    title = (job.get('title') or '').lower()
    wt = (job.get('workplace_type') or '').lower()
    if any(r.search(f'{loc} {title}') for r in _ONSITE_RES_COMPILED):
        return False
    if wt in ('hybrid', 'on-site', 'onsite', 'on site'):
        return False
    if wt == 'remote':
        return True
    if any(r.search(loc) for r in _REMOTE_LOC_RES_COMPILED):
        return True
    return any(r.search(title) for r in _REMOTE_TITLE_RES_COMPILED)


# ---------------------------------------------------------------------------
# Sales titles (v11): a sales seat that sells ServiceNow is not a
# ServiceNow role. Rejected outright — the user wants sales-engineering
# roles labeled as noise, and "ServiceNow-family roles only" means these
# never alert.
# ---------------------------------------------------------------------------
_SALES_TITLE_RES = [
    r'\bbusiness\s+development\b',
    r'\baccount\s+(executive|manager)\b',
    r'\bsales\b',
    r'\b(sdr|bdr)\b',
    r'\binside\s+sales\b',
]
_SALES_TITLE_RES_COMPILED = [re.compile(p, re.IGNORECASE) for p in _SALES_TITLE_RES]


def is_sales_role(job):
    """True when the title is a sales job (not a ServiceNow-family role)."""
    return any(r.search(job.get('title') or '') for r in _SALES_TITLE_RES_COMPILED)


# ---------------------------------------------------------------------------
# Government / clearance (US only)
# ---------------------------------------------------------------------------
def _strip_clearance_negations(text):
    """Remove negated clearance mentions ("no clearance required") so roles
    that explicitly DON'T need a clearance aren't rejected."""
    out = text or ''
    for pat in _CLEARANCE_NEGATION_RES_COMPILED:
        out = pat.sub(' ', out)
    return out


def _has_clearance_requirement(text):
    """True when the text says the role demands a clearance."""
    return bool(_CLEARANCE_RE.search(text) or
                any(r.search(text) for r in _CLEARANCE_REQ_RES_COMPILED))


def is_government_job(job):
    """True for US federal/government/clearance roles."""
    company = job.get('company', '') or ''
    title = _strip_clearance_negations(job.get('title', '') or '')
    location = job.get('location', '') or ''
    who = f'{company} {title}'
    if _GOV_RE.search(who):
        return True
    # Gov program sites in the location or title (Suitland, Fort Meade, ...).
    if _GOV_SITE_RE.search(f'{location} {title}'):
        return True
    # Clearance requirements or gov-domain work in the title.
    if _has_clearance_requirement(title) or _GOV_DOMAIN_RE.search(title):
        return True
    desc = _strip_clearance_negations(job.get('description', '') or '')
    if _has_clearance_requirement(desc):
        return True
    return bool(_GOV_DOMAIN_RE.search(desc))


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------
def parse_posted_date(value, today=None):
    """Normalize a posted-date value to a datetime.date, or None.

    Handles: None, epoch seconds/millis (int/float/str), ISO 8601,
    date-only strings, common human formats ("Sep 27, 2026"), and
    Workday-style relative dates ("Posted 4 Days Ago").
    """
    today = today or date.today()
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:      # epoch millis (Lever createdAt)
            ts /= 1000
        elif ts > 1e10:    # epoch micros — just in case
            ts /= 1e6
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    s = str(value).strip()
    if not s:
        return None
    # Workday-style relative dates: "Posted 4 Days Ago", "Posted Yesterday",
    # "Posted 30+ Days Ago", "Posted Today".
    low = s.lower()
    if 'posted' in low or 'yesterday' in low or re.search(r'\btoday\b', low):
        from datetime import timedelta as _td
        if re.search(r'\btoday\b', low):
            return today
        if 'yesterday' in low:
            return today - _td(days=1)
        m = re.search(r'(\d+)\+?\s*(day|week|month|hour|minute)', low)
        if m:
            n, unit = int(m.group(1)), m.group(2)
            days = n * {'day': 1, 'week': 7, 'month': 30,
                        'hour': 0, 'minute': 0}[unit]
            return today - _td(days=days)
    # Pure digits as string -> epoch
    if re.fullmatch(r'\d{10,16}', s):
        return parse_posted_date(int(s), today)
    # ISO 8601 / date-only
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00')).date()
    except ValueError:
        pass
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%b %d, %Y', '%B %d, %Y',
                '%Y/%m/%d', '%d-%b-%Y', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # Last resort: find a YYYY-MM-DD inside a longer string
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


def posted_age_days(job, today=None):
    """Days since posting, or None if the date can't be determined."""
    today = today or date.today()
    posted = parse_posted_date(job.get('date_posted'), today)
    if posted is None:
        return None
    return (today - posted).days


def is_fresh(job, today=None):
    """7-day freshness (v10) — only roles posted in the last week are
    worth alerting on. Unknown dates pass (optimistic)."""
    age = posted_age_days(job, today)
    if age is None:
        return True
    return age <= MAX_AGE_DAYS


# ---------------------------------------------------------------------------
# Fit ranking (v7 retarget): scores a MATCHED job for the senior, AI-heavy
# ServiceNow target profile. Ranking NEVER filters — junior/generic
# ServiceNow roles still match, they just score lower and surface later.
#   base 50 for any match
#   +10 title (core) match
#   +15 senior title (Senior/Lead/Architect/Principal/Staff/Expert/SME)
#   -15 junior title (Junior/Jr/Entry-level/Intern)
#   specialty clusters: +20 title / +10 description for AI (highest
#   priority), +10 title / +5 description for every other cluster
#   (a cluster counts once — title wins over description, no double-count)
# fit_tier: >=75 high, 40-74 standard, <40 low.
# ---------------------------------------------------------------------------
SENIOR_TITLE_RES = [
    r'\bsenior\b', r'\bsr\.?\b', r'\blead\b', r'\bprincipal\b',
    r'\bstaff\b', r'\barchitect\b', r'\bexpert\b', r'\bsme\b',
]
JUNIOR_TITLE_RES = [
    r'\bjunior\b', r'\bjr\.?\b', r'\bentry[\s-]?level\b', r'\bintern(ship)?\b',
]
# Specialty clusters from the target profile. Patterns run against the
# lowercased title / description with word boundaries; "sam"/"ham" use
# bare abbreviations (job posts don't name people "Sam").
CLUSTERS = {
    'ai': [r'\bnow\s+assist\b', r'\bai\s+control\s+tower\b', r'\bgenai\b',
           r'\bgenerative\s+ai\b', r'\bllm\b', r'\bai\s+agent\b',
           r'\bai\s+governance\b', r'\bresponsible\s+ai\b',
           r'\bprompt\s+injection\b', r'\bmachine\s+learning\b'],
    'grc': [r'\bgrc\b', r'\birm\b', r'\btprm\b',
            r'\bthird[\s-]?party\s+risk\b', r'\bcompliance\b',
            r'\brisk\s+management\b', r'\baudit\b', r'\bgovernance\b',
            r'\bregulatory\b', r'\bdisclosure\b'],
    'itom': [r'\bitom\b', r'\bcmdb\b', r'\bdiscovery\b', r'\bmid\s+server\b',
             r'\bevent\s+management\b', r'\bservice\s+mapping\b',
             r'\btenable\b', r'\bvulnerability\b'],
    'samham': [r'\bsoftware\s+asset\b', r'\bhardware\s+asset\b',
               r'\basset\s+management\b', r'\bcontract\s+lifecycle\b',
               r'\blicen[cs]e\s+compliance\b', r'\bentitlement\b',
               r'\bsam\b', r'\bham\b'],
    'integrations': [r'\bintegration\b', r'\bsailpoint\b',
                     r'\bvirtual\s+agent\b', r'\bazure\s+ad\b',
                     r'\brest\s+api\b', r'\bsso\b', r'\bsingle\s+sign[\s-]?on\b',
                     r'\bidentity\s+provisioning\b'],
    'spm': [r'\bspm\b', r'\bstrategic\s+portfolio\b',
            r'\bportfolio\s+management\b', r'\bproject\s+portfolio\b'],
    'upgrades': [r'\bupgrade\b', r'\brelease\s+management\b',
                 r'\bpatch\s+management\b'],
}
_SENIOR_RES_COMPILED = [re.compile(p) for p in SENIOR_TITLE_RES]
_JUNIOR_RES_COMPILED = [re.compile(p) for p in JUNIOR_TITLE_RES]
_CLUSTERS_COMPILED = {k: [re.compile(p) for p in v] for k, v in CLUSTERS.items()}
# Bare "AI" counts for the AI cluster in TITLES only ("ServiceNow AI
# Engineer" is AI-flavored). In descriptions bare "AI" is noise
# ("AI-powered" appears everywhere), so description matching uses the
# specific patterns above.
_BARE_AI_RE = re.compile(r'\bai\b')


def fit_score(job):
    """0-100 fit score for the senior AI-heavy ServiceNow target profile."""
    title = (job.get('title') or '').lower()
    desc = (job.get('description') or '').lower()
    score = 50
    if match_tier(job) == 'core':
        score += 10
    if any(r.search(title) for r in _SENIOR_RES_COMPILED):
        score += 15
    if any(r.search(title) for r in _JUNIOR_RES_COMPILED):
        score -= 15
    for name, patterns in _CLUSTERS_COMPILED.items():
        title_pats = patterns + ([_BARE_AI_RE] if name == 'ai' else [])
        if any(r.search(title) for r in title_pats):
            score += 20 if name == 'ai' else 10
        elif any(r.search(desc) for r in patterns):
            score += 10 if name == 'ai' else 5
    return max(0, min(100, score))


def fit_tier(score):
    """'high' >= 75, 'standard' 40-74, 'low' < 40."""
    if score >= 75:
        return 'high'
    if score >= 40:
        return 'standard'
    return 'low'


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------
def annotate_job(job, today=None):
    """Attach computed fields used by alerts: region, gta, age_days, tier,
    fit_score, fit_tier."""
    job['region'] = location_region(job.get('location'), job.get('title'))
    job['gta'] = is_gta(job.get('location'), job.get('title'))
    job['age_days'] = posted_age_days(job, today)
    job['tier'] = match_tier(job)
    job['fit_score'] = fit_score(job)
    job['fit_tier'] = fit_tier(job['fit_score'])
    return job


def job_matches(job, today=None):
    """job = dict with company/title/description/location/date_posted.
    Returns (bool, reason). Reasons: 'relevance', 'sales', 'location',
    'remote', 'government', 'stale', 'match'."""
    if not is_relevant(job.get('title'), job.get('description')):
        return False, 'relevance'
    if is_sales_role(job):
        return False, 'sales'
    region = location_region(job.get('location'), job.get('title'))
    if not region:
        return False, 'location'
    if is_remote_only(job):
        return False, 'remote'
    if region != 'ca' and is_government_job(job):
        return False, 'government'
    if not is_fresh(job, today):
        return False, 'stale'
    return True, 'match'
