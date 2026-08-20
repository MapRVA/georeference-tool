"""Synchronous WDQS check that an item qualifies as a Region.

Runs in the admin request thread when a Region is created or repointed —
regions are admin-only and rare, so one sub-second query for immediate
pass/fail feedback beats deferring validation to the async closure load.

The query answers two questions at once: is the item a territory or
settlement, and where is it? Only the first is an admission test. The
coordinate rides along because a new region needs a map centerpoint at
insert time, and the closure refresh that would otherwise supply it runs
later, on the urgent queue. Its absence isn't disqualifying — the admin
form asks for a centerpoint by hand instead.
"""

from typing import NamedTuple

from subjects.sparql_safety import validate_qid
from subjects.wikidata_closure import (
    USER_AGENT,
    WDQS_ENDPOINT,
    parse_wikidata_point,
)

# Wikidata classes a Region's item must reach via wdt:P31/wdt:P279*.
# Q4835091 territory alone covers cities, counties, states, CDPs,
# neighborhoods, and historic districts, but towns/villages/suburbs and
# GNIS-imported "unincorporated community" items have no P279 path to it;
# Q486972 human settlement admits those while still rejecting buildings,
# houses, people, and events.
ALLOWED_ROOT_CLASSES = ("Q4835091", "Q486972")

# SELECT rather than ASK: the class test is still the pattern that
# decides whether any row comes back, but an OPTIONAL P625 rides along so
# eligibility and coordinate cost one round trip instead of two. No rows
# => wrong class. A row with ?coord unbound => right class, no
# coordinate. LIMIT 1 because multiple allowed roots (or multiple P625
# values) would otherwise return one row per combination.
_SELECT_TEMPLATE = """\
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?coord WHERE {{
  VALUES ?root {{ {roots} }}
  wd:{qid} wdt:P31/wdt:P279* ?root .
  OPTIONAL {{ wd:{qid} wdt:P625 ?coord }}
}}
LIMIT 1
"""


class RegionCheck(NamedTuple):
    """Verdict for one candidate Q-ID.

    ``eligible`` is the class test, and the only bar to admission.
    ``coordinate`` is the item's P625 as a ``Point``, or ``None`` when
    the item has no P625 (or only an unusable one, e.g. on another
    globe). The two are independent: an eligible item with no coordinate
    is a perfectly good region whose centerpoint the admin supplies.
    """

    eligible: bool
    coordinate: object


def region_class_query(qid):
    """Build the SELECT: class test plus optional coordinate for ``qid``."""
    validate_qid(qid)
    roots = " ".join(f"wd:{root}" for root in ALLOWED_ROOT_CLASSES)
    return _SELECT_TEMPLATE.format(qid=qid, roots=roots)


def check_region(qid, *, session=None, timeout=30):
    """Resolve ``qid``'s region eligibility and coordinate in one query.

    An ``eligible`` result also implicitly confirms the Q-ID resolves.
    Raises ``requests.RequestException`` on network failure — callers
    surface that as "try again" rather than treating it as a verdict.
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
            data={"query": region_class_query(qid)},
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/sparql-results+json",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        bindings = response.json().get("results", {}).get("bindings", [])
    finally:
        if owns_session:
            session.close()

    if not bindings:
        return RegionCheck(eligible=False, coordinate=None)
    coord = bindings[0].get("coord", {}).get("value")
    return RegionCheck(
        eligible=True,
        coordinate=parse_wikidata_point(coord) if coord else None,
    )
