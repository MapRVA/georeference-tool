"""Maintain the ``SubjectAncestor`` materialization.

Per-subject SPARQL SELECT against Oxigraph produces the same set of
category-relevant ancestors the autocomplete used to walk on the fly
(class chain, brand, direct part-of, qualifier-shaped part-of). The
result is atomically swapped into Postgres so the autocomplete can run
as a simple indexed Django ORM query instead of a property-path traversal
that OOMs on non-trivial datasets.

Per-subject scoping is what makes this tractable. Same SPARQL shape
that exhausts memory when run over all Subjects at once is bounded
when the seed is a single IRI — the engine isn't tracking N parallel
walks, just one.
"""

import logging

from django.db import transaction

from .models import SubjectAncestor, WikidataItem
from .oxigraph import OxigraphClient
from .sparql_safety import sparql_wikidata_entity_iri
from .wikidata_closure import iri_to_qid

logger = logging.getLogger(__name__)


_ANCESTOR_SELECT = """\
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX pq: <http://www.wikidata.org/prop/qualifier/>

SELECT DISTINCT ?ancestor WHERE {{
  {{
    {seed} (wdt:P31?/wdt:P279*|wdt:P1716|wdt:P361) ?ancestor .
  }} UNION {{
    {seed} ?stmt_pred ?stmt .
    ?stmt pq:P361 ?ancestor .
  }}
  FILTER(?ancestor != {seed})
  FILTER(STRSTARTS(STR(?ancestor), "http://www.wikidata.org/entity/Q"))
}}
"""


def _select_ancestor_qids(client, qid):
    """Return distinct ancestor Q-IDs for ``qid`` via the per-subject SELECT."""
    seed = sparql_wikidata_entity_iri(qid)
    rows = client.select(_ANCESTOR_SELECT.format(seed=seed))
    return [iri_to_qid(row["ancestor"]) for row in rows]


def update_subject_ancestors(subject, client):
    """Replace ``subject``'s ``SubjectAncestor`` rows from Oxigraph.

    Atomic to concurrent readers: the delete + bulk_create inside
    ``transaction.atomic()`` swaps the row set as one Postgres
    transaction, so readers see either the old set or the new set
    (never a mix).

    Returns the number of rows written.

    Ancestors whose ``WikidataItem`` row doesn't yet exist are dropped
    silently — shouldn't happen post-``commit_closure_to_oxigraph`` (it
    bulk-creates them), but defensive against future drift between the
    Oxigraph load and the Postgres mirror.
    """
    qid = subject.wikidata_item.wikidata_id
    ancestor_qids = _select_ancestor_qids(client, qid)

    ancestor_pks = list(
        WikidataItem.objects.filter(wikidata_id__in=ancestor_qids).values_list(
            "pk", flat=True
        )
    )

    with transaction.atomic():
        SubjectAncestor.objects.filter(subject=subject).delete()
        if ancestor_pks:
            SubjectAncestor.objects.bulk_create(
                [
                    SubjectAncestor(subject_id=subject.pk, ancestor_id=pk)
                    for pk in ancestor_pks
                ],
                ignore_conflicts=True,
            )
    return len(ancestor_pks)


def rebuild_all_subject_ancestors():
    """Replace every Subject's ancestor rows from Oxigraph.

    Backfill / one-off entry point — callable from a Django shell when
    you need to populate the table without waiting for each Subject's
    next Beat refresh.
    """
    from .models import Subject

    count = 0
    with OxigraphClient() as client:
        for subject in (
            Subject.objects.filter(wikidata_item__isnull=False)
            .select_related("wikidata_item")
            .iterator()
        ):
            try:
                update_subject_ancestors(subject, client)
                count += 1
            except Exception:
                logger.exception(
                    "Failed to refresh SubjectAncestor for subject %s", subject.pk
                )
    return count
