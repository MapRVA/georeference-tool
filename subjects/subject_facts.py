"""Read per-Subject Wikidata facts from the Oxigraph mirror.

Counterpart to ``wikidata_closure.py``, which writes them. Queries here
are anchored on the entity IRI (bound subject, scoped to the entity's
named graph) so the planner can't pick the bad plan we hit when an
``rdfs:label`` lookup over the whole graph appears before a small
intermediate result has been built. See the timing notes in this
module's PR for what that looks like in practice.
"""

import logging
from datetime import datetime

import requests

from .oxigraph import OxigraphClient, entity_graph_iri
from .sparql_safety import UnsafeSparqlInput, validate_qid

logger = logging.getLogger(__name__)


# ``SAMPLE`` collapses to exactly one row even if a future closure load
# emits duplicate English literals -- ``wikidata_closure.parse_closure``
# doesn't dedupe per (predicate, lang), and seed entities arrive with
# unfiltered languages from CONSTRUCT branch 1.
_SUBJECT_FACTS_QUERY = """\
PREFIX wd:     <http://www.wikidata.org/entity/>
PREFIX wdt:    <http://www.wikidata.org/prop/direct/>
PREFIX schema: <http://schema.org/>

SELECT (SAMPLE(?d) AS ?description) (SAMPLE(?i) AS ?inception)
WHERE {{
  GRAPH <{graph}> {{
    OPTIONAL {{ wd:{qid} schema:description ?d . FILTER(LANG(?d) = "en") }}
    OPTIONAL {{ wd:{qid} wdt:P571 ?i }}
  }}
}}
"""


def fetch_subject_facts(qid):
    """Return ``{description, inception}`` for one Subject from Oxigraph.

    ``description`` is the English ``schema:description`` literal (str,
    omitted if absent). ``inception`` is a ``datetime.date`` parsed from
    the first ``wdt:P571`` literal (omitted if absent or unparseable).
    Returns ``{}`` on Q-ID validation failure or Oxigraph transport
    error so callers can render the page without the Wikidata fields.
    """
    try:
        validate_qid(qid)
    except UnsafeSparqlInput:
        return {}

    query = _SUBJECT_FACTS_QUERY.format(qid=qid, graph=entity_graph_iri(qid))

    try:
        with OxigraphClient() as client:
            rows = client.select(query)
    except requests.RequestException as e:
        logger.warning("fetch_subject_facts(%s) failed: %s", qid, e)
        return {}

    if not rows:
        return {}

    facts = {}
    row = rows[0]
    if row.get("description"):
        facts["description"] = row["description"]
    if row.get("inception"):
        # P571 RDF literals like "1895-01-01T00:00:00Z". BCE years (leading
        # "-") and partial dates are skipped, matching the leniency of
        # ``extract_seed_metadata`` in wikidata_closure.py.
        try:
            facts["inception"] = datetime.strptime(
                row["inception"][:10], "%Y-%m-%d"
            ).date()
        except (ValueError, TypeError):
            pass
    return facts
