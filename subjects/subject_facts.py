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
from urllib.parse import urlsplit

import requests

from .oxigraph import OxigraphClient, entity_graph_iri
from .sparql_safety import UnsafeSparqlInput, validate_qid

logger = logging.getLogger(__name__)


# ``SAMPLE`` collapses to exactly one row even if a closure load emits
# duplicate literals -- ``wikidata_closure.parse_closure`` doesn't dedupe
# per (predicate, lang), and ``WIKIDATA_MIRROR_LANGUAGES`` may mirror
# more languages than the English these reads pick out.
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


_AUTHORITY_IDS_QUERY = """\
PREFIX wd:       <http://www.wikidata.org/entity/>
PREFIX wdt:      <http://www.wikidata.org/prop/direct/>
PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX rdfs:     <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?prop ?propLabel ?value ?formatter ?itemLabel WHERE {{
  GRAPH <{graph}> {{ wd:{qid} ?p ?value . }}
  GRAPH ?prop_g {{
    ?prop wikibase:directClaim ?p ;
          wdt:P31 wd:Q18618628 .
    OPTIONAL {{ ?prop rdfs:label ?propLabel . FILTER(LANG(?propLabel) = "en") }}
    OPTIONAL {{ ?prop wdt:P1630 ?formatter }}
  }}
  OPTIONAL {{
    GRAPH ?prop_g {{ ?prop wdt:P1629 ?item }}
    GRAPH ?item_g {{ ?item rdfs:label ?itemLabel . FILTER(LANG(?itemLabel) = "en") }}
  }}
}}
ORDER BY ?propLabel ?value
"""


_SAFE_URL_SCHEMES = frozenset({"http", "https"})


def _authority_url(formatter, value):
    """
    Build the external-identifier URL, or ``None`` if unsafe.

    ``formatter`` is a Wikidata ``P1630`` template with a ``$1`` placeholder
    for ``value``. A vandalized formatter could yield a non-``http(s)``
    scheme (e.g. ``javascript:``) that would be rendered straight into an
    ``href``; such URLs are dropped.
    """
    if not formatter:
        return None
    url = formatter.replace("$1", value)
    if urlsplit(url).scheme.lower() not in _SAFE_URL_SCHEMES:
        return None
    return url


def fetch_authority_ids(qid):
    """
    Return authority-control external identifiers for one Subject.

    Pairs each cultural-heritage authority-control property the subject
    uses (found via the per-property descriptor graphs ``wikidata_closure``
    mirrors) with the subject's own identifier value(s), yielding
    display-ready external links. Returns a list of
    ``{property, value, url, item_label}`` dicts, ordered by property
    label; ``url`` is ``None`` when the property has no ``P1630`` formatter
    URL (or the formatter would produce a non-``http(s)`` link), and
    ``item_label`` is ``None`` unless the property has a P1629
    ("Wikidata item of this property") target with a mirrored English
    label. Returns ``[]`` on Q-ID validation failure or Oxigraph transport
    error, so callers can render the page without the section.
    """
    try:
        validate_qid(qid)
    except UnsafeSparqlInput:
        return []

    query = _AUTHORITY_IDS_QUERY.format(qid=qid, graph=entity_graph_iri(qid))

    try:
        with OxigraphClient() as client:
            rows = client.select(query)
    except requests.RequestException as e:
        logger.warning("fetch_authority_ids(%s) failed: %s", qid, e)
        return []

    results = []
    for row in rows:
        value = row.get("value")
        if not value:
            continue
        formatter = row.get("formatter")
        # Fall back to the bare P-ID if a property somehow lacks an English
        # label, so the row still renders with an identifier prefix.
        label = row.get("propLabel") or row.get("prop", "").rsplit("/", 1)[-1]
        results.append(
            {
                "property": label,
                "value": value,
                "url": _authority_url(formatter, value),
                "item_label": row.get("itemLabel") or None,
            }
        )
    return results


def fetch_subject_facts(qid):
    """
    Return ``{description, inception}`` for one Subject from Oxigraph.

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
