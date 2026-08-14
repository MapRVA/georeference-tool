"""Maintain the ``RegionAncestor`` materialization.

Per-region Cypher traversal against the Memgraph mirror projects each
Region's transitive P131 containment chain (the region closure variant
of the WDQS CONSTRUCT mirrors those edges — see
``subjects.wikidata_closure``). The result is atomically swapped into
Postgres so "regions transitively inside X" runs as a simple indexed
Django ORM query instead of a graph traversal.

Per-region scoping mirrors ``subjects.subject_ancestors`` and keeps each
traversal bounded: the engine tracks one walk from one seed.
"""

import logging

from django.db import transaction

from subjects.memgraph import MemgraphClient
from subjects.models import WikidataItem
from subjects.sparql_safety import validate_qid

from .models import Region, RegionAncestor

logger = logging.getLogger(__name__)


# One arm only: the transitive P131 containment chain. Unlike the
# SubjectAncestor query (which folds in P31?/P279*, P1716, and P361 for
# category browse), regions project pure administrative containment.
# Memgraph never reuses an edge within a path, so upstream P131 cycles
# terminate; the id guard drops the seed if a cycle loops back to it.
_ANCESTOR_QUERY = """\
MATCH (s:Entity {id: $qid})-[:P131*1..]->(a:Entity)
WHERE a.id <> $qid
RETURN DISTINCT a.id AS ancestor
"""


def _select_ancestor_qids(client, qid):
    """Return distinct containment-ancestor Q-IDs for ``qid``."""
    validate_qid(qid)
    rows = client.read(_ANCESTOR_QUERY, qid=qid)
    return [row["ancestor"] for row in rows]


def update_region_ancestors(region, client):
    """Replace ``region``'s ``RegionAncestor`` rows from the Memgraph mirror.

    Atomic to concurrent readers: the delete + bulk_create inside
    ``transaction.atomic()`` swaps the row set as one Postgres
    transaction, so readers see either the old set or the new set
    (never a mix).

    Returns the number of rows written.

    Ancestors whose ``WikidataItem`` row doesn't yet exist are dropped
    silently — shouldn't happen post-``commit_closure_to_memgraph`` (it
    bulk-creates them), but defensive against future drift between the
    graph load and the Postgres mirror.
    """
    qid = region.wikidata_item.wikidata_id
    ancestor_qids = _select_ancestor_qids(client, qid)

    ancestor_pks = list(
        WikidataItem.objects.filter(wikidata_id__in=ancestor_qids).values_list(
            "pk", flat=True
        )
    )

    with transaction.atomic():
        RegionAncestor.objects.filter(region=region).delete()
        if ancestor_pks:
            RegionAncestor.objects.bulk_create(
                [
                    RegionAncestor(region_id=region.pk, ancestor_id=pk)
                    for pk in ancestor_pks
                ],
                ignore_conflicts=True,
            )
    return len(ancestor_pks)


def rebuild_all_region_ancestors():
    """Replace every Region's ancestor rows from the Memgraph mirror.

    Backfill / one-off entry point — callable from a Django shell when
    you need to populate the table without waiting for each Region's
    next Beat refresh.
    """
    count = 0
    with MemgraphClient() as client:
        for region in Region.objects.select_related("wikidata_item").iterator():
            try:
                update_region_ancestors(region, client)
                count += 1
            except Exception:
                logger.exception(
                    "Failed to refresh RegionAncestor for region %s", region.pk
                )
    return count
