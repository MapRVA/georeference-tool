"""Synchronous WDQS check that an item qualifies as a Region.

Runs in the admin request thread when a Region is created or repointed —
regions are admin-only and rare, so one sub-second ASK for immediate
pass/fail feedback beats deferring validation to the async closure load.
"""

from subjects.sparql_safety import validate_qid
from subjects.wikidata_closure import USER_AGENT, WDQS_ENDPOINT

# Wikidata classes a Region's item must reach via wdt:P31/wdt:P279*.
# Q4835091 territory alone covers cities, counties, states, CDPs,
# neighborhoods, and historic districts, but towns/villages/suburbs and
# GNIS-imported "unincorporated community" items have no P279 path to it;
# Q486972 human settlement admits those while still rejecting buildings,
# houses, people, and events.
ALLOWED_ROOT_CLASSES = ("Q4835091", "Q486972")

_ASK_TEMPLATE = """\
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

ASK {{
  VALUES ?root {{ {roots} }}
  wd:{qid} wdt:P31/wdt:P279* ?root .
}}
"""


def region_class_ask_query(qid):
    """Build the ASK: does ``qid`` reach an allowed root via P31/P279*?"""
    validate_qid(qid)
    roots = " ".join(f"wd:{root}" for root in ALLOWED_ROOT_CLASSES)
    return _ASK_TEMPLATE.format(qid=qid, roots=roots)


def check_region_class(qid, *, session=None, timeout=30):
    """True iff ``qid`` is (transitively) an instance of an allowed root.

    A ``True`` result also implicitly confirms the Q-ID resolves. Raises
    ``requests.RequestException`` on network failure — callers surface
    that as "try again" rather than treating it as a verdict.
    """
    owns_session = session is None
    if owns_session:
        # Local import: subjects.tasks imports regions modules, so a
        # module-level import here would be circular.
        from subjects.tasks import create_request_session

        session = create_request_session()
    try:
        response = session.post(
            WDQS_ENDPOINT,
            data={"query": region_class_ask_query(qid)},
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/sparql-results+json",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return bool(response.json().get("boolean"))
    finally:
        if owns_session:
            session.close()
