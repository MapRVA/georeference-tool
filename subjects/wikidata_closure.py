"""Fetch a subject's local Wikidata graph from the Wikidata Query Service.

Strategy: one CONSTRUCT query per subject to WDQS that returns the seed's
triples plus its neighbourhood — statement bodies, labels and class edges
for referenced entities and class ancestors, and descriptors of the
properties the seed uses. The response is parsed client-side with
pyoxigraph, grouped by Wikidata entity IRI, and loaded into Oxigraph via
a single SPARQL Update that atomically replaces each entity's named graph.

This means one external request per subject refresh instead of one per
entity, and a consistent snapshot (no risk of upstream edits landing
mid-walk).
"""

import logging
from datetime import datetime

import pyoxigraph
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .sparql_safety import (
    UnsafeSparqlInput,
    looks_like_pid,
    looks_like_qid,
    validate_language_tag,
    validate_qid,
)

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

# ---------------------------------------------------------------------------
# Closure CONSTRUCT assembly.
#
# The query is composed from the named fragments below so each concern is
# documented next to its SPARQL, as ``#`` comments that travel with the
# assembled query into the WDQS GUI and logs. Fragments are ``str.format``
# templates sharing two placeholders — ``{qid}`` (validated seed Q-ID) and
# ``{lang_filter}`` (literal-language guard built from
# ``settings.WIKIDATA_MIRROR_LANGUAGES`` at call time) — with literal SPARQL
# braces doubled.
#
# Every branch either is a self-contained pattern (seed, sitelink) or reads
# "select neighbour ?entity rows, then emit a profile of triples about
# them". Two shared emission profiles:
#   - full (``_TAIL_FULL``): every triple, literals language-filtered
#   - nav  (``_TAIL_NAV``):  labels, descriptions, and class edges only —
#     enough to name an entity and place it in the P31/P279 ontology
#     without pulling its statement bodies, which would balloon the closure
# ---------------------------------------------------------------------------

_TAIL_FULL = """\
    ?entity ?p ?o .
    {lang_filter}"""

_TAIL_NAV = """\
    ?entity ?p ?o .
    FILTER(?p IN (rdfs:label, skos:altLabel, schema:description,
                  wdt:P31, wdt:P279))
    {lang_filter}"""

_BRANCH_SEED = (
    """\
    # Seed: every triple about the subject itself - the truthy wdt:*
    # values plus the reified p:* links to the statement nodes that the
    # full-profile branch follows.
    BIND(wd:{qid} AS ?entity)
"""
    + _TAIL_FULL
)

_BRANCH_FULL = (
    """\
    # Full-profile neighbours - every (language-filtered) triple about:
    # (a) the seed's statement nodes: carries qualifiers (pq:*), typed
    #     main values (ps:*), rank, and the prov:wasDerivedFrom link.
    #     parse_closure routes these into the seed's named graph, so reads
    #     can walk ?s p:Pxx ?stmt . ?stmt pq:Pxx ?q without crossing
    #     graphs.
    # (b) entities the seed points to via truthy wdt:* claims: brands,
    #     architects, locations, ... - full data for display and category
    #     autocomplete without a second round trip. Their own reified
    #     statements are NOT pulled; that would balloon the closure.
    {{
      wd:{qid} ?stmt_link ?entity .
      FILTER(STRSTARTS(STR(?stmt_link), "http://www.wikidata.org/prop/P"))
    }} UNION {{
      wd:{qid} ?direct_pred ?entity .
      FILTER(STRSTARTS(STR(?direct_pred), "http://www.wikidata.org/prop/direct/"))
      FILTER(isIRI(?entity))
      FILTER(STRSTARTS(STR(?entity), "http://www.wikidata.org/entity/Q"))
      FILTER(?entity != wd:{qid})
    }}
"""
    + _TAIL_FULL
)

_BRANCH_NAV = (
    """\
    # Nav-profile neighbours - names and ontology placement only, for:
    # (a) entities referenced by the seed's statement nodes (ps:* main
    #     values and pq:* qualifiers), e.g. the historic district named in
    #     a pq:P361 on a heritage-designation claim; without labels here
    #     the category autocomplete's qualifier arm drops them.
    # (b) class ancestors via wdt:P31?/wdt:P279*.
    # (c) the "Wikidata item of this property" (P1629) target of each
    #     cultural-heritage authority-control property (P31 Q18618628) the
    #     seed uses - the register (e.g. National Register of Historic
    #     Places) whose label fetch_authority_ids displays. Scoped to
    #     authority properties to limit entity fan-out; drop the P31
    #     constraint here if other property items become useful.
    {{
      wd:{qid} ?stmt_link ?stmt .
      FILTER(STRSTARTS(STR(?stmt_link), "http://www.wikidata.org/prop/P"))
      ?stmt ?stmt_pred ?entity .
      FILTER(STRSTARTS(STR(?stmt_pred), "http://www.wikidata.org/prop/statement/") ||
             STRSTARTS(STR(?stmt_pred), "http://www.wikidata.org/prop/qualifier/"))
      FILTER(isIRI(?entity))
      FILTER(STRSTARTS(STR(?entity), "http://www.wikidata.org/entity/Q"))
    }} UNION {{
      wd:{qid} wdt:P31?/wdt:P279* ?entity .
    }} UNION {{
      wd:{qid} ?claim ?claim_value .
      ?authprop wikibase:directClaim ?claim .
      ?authprop wdt:P31 wd:Q18618628 .
      ?authprop wdt:P1629 ?entity .
    }}
    FILTER(?entity != wd:{qid})
"""
    + _TAIL_NAV
)

_BRANCH_PROP_DESCRIPTORS = """\
    # Property descriptors: for every property the seed uses as a truthy
    # claim, mirror the property entity's own descriptor triples - label,
    # the wikibase:directClaim bridge to its wdt: predicate, class markers
    # (wdt:P31, e.g. Q18618628 marks cultural-heritage authority-control
    # properties), the P1630 formatter URL, and the P1629 link to the
    # property's Wikidata item. parse_closure routes these wd:Pxx subjects
    # into per-property named graphs; reads join them back to the seed's
    # raw values (see subject_facts.fetch_authority_ids), and future
    # subject-page widgets get property labels without closure changes.
    wd:{qid} ?claim ?claim_value .
    ?entity wikibase:directClaim ?claim .
    ?entity ?p ?o .
    FILTER(?p IN (rdfs:label, wikibase:directClaim, wdt:P31, wdt:P1630,
                  wdt:P1629))
    {lang_filter}"""

_BRANCH_SITELINK = """\
    # English Wikipedia sitelink. The article URL is the *subject* of
    # these triples, so parse_closure's entity grouping skips them;
    # extract_seed_metadata reads them into WikidataItem.wikipedia_url.
    ?article schema:about wd:{qid} .
    ?article schema:isPartOf <https://en.wikipedia.org/> ."""

_CLOSURE_BRANCHES = (
    _BRANCH_SEED,
    _BRANCH_FULL,
    _BRANCH_NAV,
    _BRANCH_PROP_DESCRIPTORS,
    _BRANCH_SITELINK,
)

_CLOSURE_QUERY_TEMPLATE = (
    """\
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX schema: <http://schema.org/>

CONSTRUCT {{
  ?entity ?p ?o .
  ?article schema:about wd:{qid} .
  ?article schema:isPartOf <https://en.wikipedia.org/> .
}} WHERE {{
  {{
"""
    + "\n  }} UNION {{\n".join(_CLOSURE_BRANCHES)
    + """
  }}
}}
"""
)


def _language_filter():
    """Build the literal-language FILTER from ``WIKIDATA_MIRROR_LANGUAGES``.

    Language-tagged literals outside the configured set are dropped; plain
    literals (dates, external identifiers, formatter URLs) always pass.
    Built per call so the setting stays test-overridable and importing
    this module never touches Django settings.
    """
    langs = settings.WIKIDATA_MIRROR_LANGUAGES
    if not langs:
        raise ImproperlyConfigured("WIKIDATA_MIRROR_LANGUAGES must not be empty")
    tags = ", ".join(f'"{validate_language_tag(lang)}"' for lang in langs)
    return f'FILTER(!isLiteral(?o) || lang(?o) IN ({tags}) || lang(?o) = "")'


def closure_query(qid):
    """Build the CONSTRUCT for the seed + its closure neighbourhood.

    Per-branch documentation lives on the ``_BRANCH_*`` fragment constants
    above and is carried into the assembled query as SPARQL comments.
    Cross-cutting notes:

    - Literals in every branch are restricted to
      ``settings.WIKIDATA_MIRROR_LANGUAGES`` (plus plain literals). Reads
      and ``extract_seed_metadata`` are English-only today, so keep ``en``
      in the list; adding languages there is the first step of any future
      localization, followed by read-side changes.
    - Reference bodies (``pr:*`` triples on reference nodes) are not
      pulled - the ``prov:wasDerivedFrom`` link comes along, but following
      it to the citation details would require another branch and a
      value-node-aware parser. Add later if a query needs it.
    - ``parse_closure`` routes the response into named graphs (statement
      nodes into their owning entity's graph, ``wd:Pxx`` property
      descriptors into per-property graphs); ``extract_seed_metadata``
      picks the sitelink triples out separately.
    """
    validate_qid(qid)
    return _CLOSURE_QUERY_TEMPLATE.format(qid=qid, lang_filter=_language_filter())


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
        graphs. Property descriptors (``wd:Pxxx`` subjects, from the
        property-descriptor branch) go under per-property graph IRIs -
        stored once, shared by every subject that uses the property. Blank
        nodes, value nodes, and reference nodes are dropped.
      - ``labels``: ``{qid: english_label}`` - one per Q-entity, for
        populating a freshly-created ``WikidataItem.title`` without an
        extra fetch.
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
            # Statements minted by older Wikibase versions carry a
            # lowercase entity segment (``statement/q123-...``); uppercase
            # it so their bodies land in the (canonical-IRI) entity graph
            # instead of being dropped as invalid.
            owning_qid = suffix.split("-", 1)[0].upper()
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
        suffix = iri.removeprefix(WIKIDATA_ENTITY_IRI_BASE)

        # Property descriptors (``wd:Pxxx`` subjects) mirror into
        # per-property named graphs, refreshed whenever any subject using
        # the property refreshes. ``looks_like_pid`` validates the suffix,
        # so the IRI is safe to reach ``build_atomic_update``'s
        # ``GRAPH <iri>`` f-string. Skipped by the label collection below:
        # ``WikidataItem`` rows are Q-entities only.
        if looks_like_pid(suffix):
            groups.setdefault(iri, []).append(
                pyoxigraph.Triple(quad.subject, quad.predicate, quad.object)
            )
            continue

        # Reject anything whose suffix isn't a Q-ID before it lands in
        # ``groups`` and gets f-stringed into the ``GRAPH <iri>`` clause
        # in ``build_atomic_update``. Drops properties (P31) that share
        # the entity-IRI prefix but aren't graph subjects we want.
        qid = suffix
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
    # Property-descriptor graphs (wd:Pxxx) live only in Oxigraph;
    # WikidataItem rows track Q-entities alone.
    qids = [q for q in (iri_to_qid(iri) for iri in groups) if looks_like_qid(q)]
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
