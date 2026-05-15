"""Fetch a subject's class-ancestor closure from the Wikidata Query Service.

Strategy: one CONSTRUCT query per subject to WDQS that returns the seed's
triples plus its class-ancestor labels and class edges. The response is
parsed client-side with pyoxigraph, grouped by Wikidata entity IRI, and
loaded into Oxigraph via a single SPARQL Update that atomically replaces
each entity's named graph.

This means one external request per subject refresh instead of one per
entity, and a consistent snapshot (no risk of upstream edits landing
mid-walk).
"""

import logging
from datetime import datetime

import pyoxigraph

from .sparql_safety import UnsafeSparqlInput, validate_qid

logger = logging.getLogger(__name__)

WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
WIKIDATA_ENTITY_IRI_BASE = "http://www.wikidata.org/entity/"
# Wikidata statement nodes are IRIs like
# ``http://www.wikidata.org/entity/statement/Q42-D8404CDA-25E4-...``;
# the leading ``Q``-segment names the entity that asserts the claim.
WIKIDATA_STATEMENT_IRI_BASE = "http://www.wikidata.org/entity/statement/"
USER_AGENT = (
    "GeoreferenceTool/1.0 (https://github.com/mapRVA/georeference-tool; sparql-mirror)"
)

# WikidataItem fields populated by ``extract_seed_metadata`` plus the
# sparql-mirror bookkeeping fields. Callers pass this as ``update_fields``
# so the seed row save touches only what the closure actually rewrites
# (and avoids re-entering ``WikidataItem.save()``'s is_new branch, which
# would trigger another WDQS fetch).
SEED_METADATA_FIELDS = (
    "title",
    "description",
    "wikipedia_url",
    "architect",
    "image_url",
    "inception",
    "sparql_last_loaded_at",
    "sparql_fetch_failures",
)

RDFS_LABEL_IRI = "http://www.w3.org/2000/01/rdf-schema#label"
SCHEMA_DESCRIPTION_IRI = "http://schema.org/description"
SCHEMA_ABOUT_IRI = "http://schema.org/about"
WDT_P18_IRI = "http://www.wikidata.org/prop/direct/P18"
WDT_P84_IRI = "http://www.wikidata.org/prop/direct/P84"
WDT_P571_IRI = "http://www.wikidata.org/prop/direct/P571"
COMMONS_FILEPATH_PREFIX = "http://commons.wikimedia.org/wiki/Special:FilePath/"
EN_WIKIPEDIA_PREFIX = "https://en.wikipedia.org/"


def closure_query(qid):
    """Build the CONSTRUCT for the seed + its closure neighbourhood.

    Six UNION branches:
      - Seed: all triples about the seed itself. Includes both the truthy
        ``wdt:*`` predicates and the reified ``p:*`` links to statement
        nodes, which the next branch follows.
      - Seed statement bodies: for every ``wd:{{qid}} p:Pxxx ?stmt`` triple,
        emit all triples about ``?stmt``. This is what carries qualifiers
        (``pq:*``), the typed main value (``ps:*``), rank (``wikibase:rank``)
        and the link to a reference node (``prov:wasDerivedFrom``).
        Statement-node triples are routed into the seed's named graph by
        ``parse_closure`` so SPARQL queries can traverse
        ``?subject p:Pxxx ?stmt . ?stmt pq:Pxxx ?qval`` without crossing
        graphs.
      - Statement-referenced entities: labels and class edges for entities
        pointed to by the seed's statement nodes (``ps:*`` main values and
        ``pq:*`` qualifiers). Without this, an entity reached only via a
        qualifier — e.g., the historic district named in a ``pq:P361`` on a
        ``p:P1435`` heritage-designation claim — has no English label in
        Oxigraph, and the category autocomplete's qualifier-path UNION arm
        silently drops it. Restricted to the same label / class-edge set as
        the ancestor branch — we don't pull each qualifier-target's full
        statement body.
      - Ancestors via P31?/P279*: only labels and class edges (wdt:P31,
        wdt:P279). The predicate filter avoids pulling each ancestor's
        full statement body, which we don't need for class navigation.
      - Direct references: any Wikidata entity the seed points to via a
        ``wdt:*`` predicate, with all its triples (English literals only).
        This gives us labels and class edges for brands (wdt:P1716),
        architects (wdt:P84), locations (wdt:P131), etc., so they're
        available as autocomplete categories and for display without a
        second round trip. Their reified statements are *not* pulled —
        widening to those would balloon the closure.
      - Seed's English Wikipedia sitelink: emits the article URL via
        ``schema:about``/``schema:isPartOf`` triples. The article URL has
        the article as subject (not the entity), so it's skipped by
        ``parse_closure``'s grouping; ``extract_seed_metadata`` picks it
        out separately to populate ``WikidataItem.wikipedia_url``.

    English-only by design: ``parse_closure`` and ``extract_seed_metadata``
    both read English labels exclusively, so multilingual support would
    require changes well beyond the literal filter here.

    Reference bodies (``pr:*`` triples on reference nodes) are not pulled —
    the ``prov:wasDerivedFrom`` link comes along, but following it to the
    citation details would require another branch and a value-node-aware
    parser. Add later if a query needs it.
    """
    validate_qid(qid)
    return f"""\
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX schema: <http://schema.org/>

CONSTRUCT {{
  ?entity ?p ?o .
  ?article schema:about wd:{qid} .
  ?article schema:isPartOf <https://en.wikipedia.org/> .
}} WHERE {{
  {{
    BIND(wd:{qid} AS ?entity)
    ?entity ?p ?o .
  }} UNION {{
    wd:{qid} ?seed_p ?entity .
    FILTER(STRSTARTS(STR(?seed_p), "http://www.wikidata.org/prop/P"))
    ?entity ?p ?o .
    FILTER(!isLiteral(?o) || lang(?o) = "en" || lang(?o) = "")
  }} UNION {{
    wd:{qid} ?stmt_link ?stmt .
    FILTER(STRSTARTS(STR(?stmt_link), "http://www.wikidata.org/prop/P"))
    ?stmt ?ref_pred ?entity .
    FILTER(STRSTARTS(STR(?ref_pred), "http://www.wikidata.org/prop/statement/") ||
           STRSTARTS(STR(?ref_pred), "http://www.wikidata.org/prop/qualifier/"))
    FILTER(isIRI(?entity))
    FILTER(STRSTARTS(STR(?entity), "http://www.wikidata.org/entity/Q"))
    FILTER(?entity != wd:{qid})
    ?entity ?p ?o .
    FILTER(?p IN (rdfs:label, skos:altLabel, schema:description,
                  wdt:P31, wdt:P279))
    FILTER(!isLiteral(?o) || lang(?o) = "en" || lang(?o) = "")
  }} UNION {{
    wd:{qid} wdt:P31?/wdt:P279* ?entity .
    FILTER(?entity != wd:{qid})
    ?entity ?p ?o .
    FILTER(?p IN (rdfs:label, skos:altLabel, schema:description,
                  wdt:P31, wdt:P279))
    FILTER(!isLiteral(?o) || lang(?o) = "en" || lang(?o) = "")
  }} UNION {{
    wd:{qid} ?ref_pred ?entity .
    FILTER(STRSTARTS(STR(?ref_pred), "http://www.wikidata.org/prop/direct/"))
    FILTER(isIRI(?entity))
    FILTER(STRSTARTS(STR(?entity), "http://www.wikidata.org/entity/Q"))
    FILTER(?entity != wd:{qid})
    ?entity ?p ?o .
    FILTER(!isLiteral(?o) || lang(?o) = "en" || lang(?o) = "")
  }} UNION {{
    ?article schema:about wd:{qid} .
    ?article schema:isPartOf <https://en.wikipedia.org/> .
  }}
}}
"""


def fetch_closure_turtle(session, qid, timeout=60):
    """Run the closure CONSTRUCT against WDQS, return Turtle bytes.

    Uses POST (recommended by WDQS for arbitrary query bodies) and asks
    for Turtle so we can hand it straight to pyoxigraph.
    """
    response = session.post(
        WDQS_ENDPOINT,
        data={"query": closure_query(qid)},
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/turtle",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.content


def parse_closure(turtle_bytes):
    """Parse closure Turtle, group by Wikidata entity IRI, collect labels.

    Returns ``(groups, labels)``:
      - ``groups``: ``{entity_iri: [pyoxigraph.Triple, ...]}`` - triples
        keyed by the named graph they belong in. Entity-subject triples
        go under the entity's own IRI; statement-node triples go under
        the owning entity's IRI (parsed out of the statement IRI's
        ``Q``-prefix), so a SPARQL query can traverse
        ``?entity p:Pxxx ?stmt . ?stmt pq:Pxxx ?qval`` without crossing
        graphs. Blank nodes, value nodes, and reference nodes are dropped.
      - ``labels``: ``{qid: english_label}`` - one per entity, for populating
        a freshly-created ``WikidataItem.title`` without an extra fetch.
    """
    groups = {}
    labels = {}
    for quad in pyoxigraph.parse(turtle_bytes, format=pyoxigraph.RdfFormat.TURTLE):
        subj = quad.subject
        if not isinstance(subj, pyoxigraph.NamedNode):
            continue
        iri = subj.value

        # Statement nodes (``entity/statement/Q{n}-{uuid}``) share the
        # entity IRI base but are routed into the owning entity's graph,
        # not their own. Check this before the entity-base branch since
        # the statement prefix is a superset of the entity prefix.
        if iri.startswith(WIKIDATA_STATEMENT_IRI_BASE):
            suffix = iri.removeprefix(WIKIDATA_STATEMENT_IRI_BASE)
            owning_qid = suffix.split("-", 1)[0]
            try:
                validate_qid(owning_qid)
            except UnsafeSparqlInput:
                continue
            graph_iri = f"{WIKIDATA_ENTITY_IRI_BASE}{owning_qid}"
            groups.setdefault(graph_iri, []).append(
                pyoxigraph.Triple(quad.subject, quad.predicate, quad.object)
            )
            continue

        if not iri.startswith(WIKIDATA_ENTITY_IRI_BASE):
            continue
        # Reject anything whose suffix isn't a Q-ID before it lands in
        # ``groups`` and gets f-stringed into the ``GRAPH <iri>`` clause
        # in ``build_atomic_update``. Drops properties (P31) that share
        # the entity-IRI prefix but aren't graph subjects we want.
        qid = iri.removeprefix(WIKIDATA_ENTITY_IRI_BASE)
        try:
            validate_qid(qid)
        except UnsafeSparqlInput:
            continue

        groups.setdefault(iri, []).append(
            pyoxigraph.Triple(quad.subject, quad.predicate, quad.object)
        )

        if (
            quad.predicate.value == RDFS_LABEL_IRI
            and isinstance(quad.object, pyoxigraph.Literal)
            and quad.object.language == "en"
            and qid not in labels
        ):
            labels[qid] = quad.object.value
    return groups, labels


def extract_seed_metadata(turtle_bytes, qid):
    """Pull ``WikidataItem`` metadata fields for ``qid`` out of the closure Turtle.

    Reads the same Turtle that ``parse_closure`` consumes - re-parses
    because pyoxigraph's parser is single-pass. The Turtle is small (a
    few thousand triples per subject), so the double-parse is cheap and
    keeps grouping and metadata extraction as independent concerns.

    Returns a dict matching the JSON-API code path it replaces:
      - ``title``: English ``rdfs:label`` (falls back to ``qid``)
      - ``description``: English ``schema:description``
      - ``wikipedia_url``: English Wikipedia article URL (or ``""``)
      - ``architect``: comma-joined ``Wikidata:Qxxx`` strings from
        ``wdt:P84`` (or ``""``); preserves the existing storage shape
      - ``image_url``: Commons ``Special:Redirect`` URL derived from
        ``wdt:P18``, or ``""``
      - ``inception``: ``datetime.date`` from ``wdt:P571`` (CE dates
        only - matches the JSON path's behavior), or ``None``
    """
    seed_iri = f"{WIKIDATA_ENTITY_IRI_BASE}{qid}"
    title = ""
    description = ""
    wikipedia_url = ""
    architects = []
    image_url = ""
    inception = None

    for quad in pyoxigraph.parse(turtle_bytes, format=pyoxigraph.RdfFormat.TURTLE):
        subj = quad.subject
        if not isinstance(subj, pyoxigraph.NamedNode):
            continue
        pred = quad.predicate.value
        obj = quad.object

        if subj.value == seed_iri:
            if pred == RDFS_LABEL_IRI and isinstance(obj, pyoxigraph.Literal):
                if obj.language == "en" and not title:
                    title = obj.value
            elif pred == SCHEMA_DESCRIPTION_IRI and isinstance(obj, pyoxigraph.Literal):
                if obj.language == "en" and not description:
                    description = obj.value
            elif pred == WDT_P84_IRI and isinstance(obj, pyoxigraph.NamedNode):
                if obj.value.startswith(WIKIDATA_ENTITY_IRI_BASE):
                    architect_qid = obj.value.removeprefix(WIKIDATA_ENTITY_IRI_BASE)
                    architects.append(f"Wikidata:{architect_qid}")
            elif pred == WDT_P18_IRI and isinstance(obj, pyoxigraph.NamedNode):
                if not image_url and obj.value.startswith(COMMONS_FILEPATH_PREFIX):
                    filename = obj.value.removeprefix(COMMONS_FILEPATH_PREFIX)
                    image_url = (
                        "https://commons.wikimedia.org/w/index.php"
                        f"?title=Special:Redirect/file/{filename}&width=300"
                    )
            elif pred == WDT_P571_IRI and isinstance(obj, pyoxigraph.Literal):
                if inception is None:
                    try:
                        inception = datetime.strptime(obj.value[:10], "%Y-%m-%d").date()
                    except (ValueError, TypeError):
                        pass
        elif (
            pred == SCHEMA_ABOUT_IRI
            and isinstance(obj, pyoxigraph.NamedNode)
            and obj.value == seed_iri
            and subj.value.startswith(EN_WIKIPEDIA_PREFIX)
            and not wikipedia_url
        ):
            wikipedia_url = subj.value

    return {
        "title": title or qid,
        "description": description,
        "wikipedia_url": wikipedia_url,
        "architect": ", ".join(architects),
        "image_url": image_url,
        "inception": inception,
    }


def build_atomic_update(groups):
    """Build the SPARQL Update body that replaces each entity's named graph.

    One ``DROP SILENT GRAPH`` + ``INSERT DATA { GRAPH <iri> { ... } }`` pair
    per entity, joined with ``;``. Submitted as a single Update request,
    this is one Oxigraph transaction - all graphs swap together or none do.
    """
    if not groups:
        return ""
    operations = []
    for iri, triples in groups.items():
        nt = pyoxigraph.serialize(
            triples,
            format=pyoxigraph.RdfFormat.N_TRIPLES,
        ).decode("utf-8")
        operations.append(f"DROP SILENT GRAPH <{iri}>")
        operations.append(f"INSERT DATA {{ GRAPH <{iri}> {{\n{nt}}} }}")
    return " ;\n".join(operations)


def iri_to_qid(iri):
    return iri.removeprefix(WIKIDATA_ENTITY_IRI_BASE)


class ClosureLoadError(Exception):
    """Raised when fetch/parse of a closure doesn't return a usable seed.

    Network failures from WDQS surface as ``requests`` exceptions and
    aren't wrapped - callers that care about that distinction can catch
    them directly.
    """


def fetch_seed_data(qid, *, session=None, timeout=60):
    """Run the WDQS closure CONSTRUCT for ``qid`` and parse the response.

    One HTTP request to WDQS, then three passes over the Turtle: grouping
    by entity for the Oxigraph load, label extraction for ancestor rows,
    metadata extraction for the seed's ``WikidataItem`` fields.

    Returns a dict with keys ``turtle``, ``groups``, ``labels``,
    ``metadata``. Raises ``ClosureLoadError`` if the response is empty or
    missing the seed itself; raises ``requests.RequestException`` if the
    HTTP call fails.
    """
    owns_session = session is None
    if owns_session:
        # Local import: avoids a hard dependency on Django app readiness
        # if this module gets imported during settings load.
        from .tasks import create_request_session

        session = create_request_session()
    try:
        turtle = fetch_closure_turtle(session, qid, timeout=timeout)
    finally:
        if owns_session:
            session.close()

    groups, labels = parse_closure(turtle)
    if not groups:
        raise ClosureLoadError(f"WDQS returned no entity triples for {qid}")
    seed_iri = f"{WIKIDATA_ENTITY_IRI_BASE}{qid}"
    if seed_iri not in groups:
        raise ClosureLoadError(f"WDQS response did not include the seed entity {qid}")

    metadata = extract_seed_metadata(turtle, qid)
    return {
        "turtle": turtle,
        "groups": groups,
        "labels": labels,
        "metadata": metadata,
    }


def commit_closure_to_oxigraph(
    seed_qid, groups, labels, *, discovered_via=None, client=None
):
    """Push parsed closure to Oxigraph and reconcile ``WikidataItem`` rows.

    - Atomically replaces each entity's named graph in Oxigraph.
    - Bumps ``sparql_last_loaded_at`` on already-existing ``WikidataItem``
      rows in the closure (the seed itself is skipped here; its caller -
      typically ``WikidataItem.save()`` - sets that field in-place before
      saving).
    - ``bulk_create``s ``WikidataItem`` rows for newly-encountered
      ancestors. ``bulk_create`` bypasses ``save()`` so we don't fan out
      one closure-fetch per ancestor.

    Returns the number of new ancestor rows created.
    """
    from django.utils import timezone

    from .models import WikidataItem
    from .oxigraph import OxigraphClient

    owns_client = client is None
    if owns_client:
        client = OxigraphClient()
    try:
        client.update(build_atomic_update(groups))
    finally:
        if owns_client:
            client.close()

    now = timezone.now()
    qids = [iri_to_qid(iri) for iri in groups.keys()]
    existing_qids = set(
        WikidataItem.objects.filter(wikidata_id__in=qids).values_list(
            "wikidata_id", flat=True
        )
    )

    # Skip the seed: its caller (WikidataItem.save) is mid-save and will
    # write sparql_last_loaded_at in the same INSERT/UPDATE.
    refresh_qids = [q for q in existing_qids if q != seed_qid]
    if refresh_qids:
        WikidataItem.objects.filter(wikidata_id__in=refresh_qids).update(
            sparql_last_loaded_at=now,
            sparql_fetch_failures=0,
        )

    new_qids = [q for q in qids if q not in existing_qids and q != seed_qid]
    new_items = [
        WikidataItem(
            wikidata_id=q,
            title=labels.get(q, q),
            sparql_last_loaded_at=now,
            sparql_fetch_failures=0,
            discovered_via=discovered_via,
        )
        for q in new_qids
    ]
    if new_items:
        WikidataItem.objects.bulk_create(new_items)

    return len(new_items)
