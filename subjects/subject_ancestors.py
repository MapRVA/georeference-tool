"""Maintain the ``SubjectAncestor`` materialization.

Per-subject Cypher traversal against the Memgraph mirror produces the
same set of category-relevant ancestors the autocomplete used to walk on
the fly (class chain, brand, direct part-of, qualifier-shaped part-of).
The result is atomically swapped into Postgres so the autocomplete can
run as a simple indexed Django ORM query instead of a graph traversal.

Per-subject scoping (inherited from the SPARQL era, where the
all-Subjects-at-once form OOMed the engine) keeps each traversal bounded:
the engine tracks one walk from one seed, not N parallel walks.
"""

import logging

from django.db import transaction

from .memgraph import MemgraphClient
from .models import SubjectAncestor, WikidataItem
from .sparql_safety import validate_qid

logger = logging.getLogger(__name__)


# Three UNIONed arms, mirroring the old SPARQL property path
# ``(wdt:P31?/wdt:P279*|wdt:P1716|wdt:P361)`` plus the qualifier arm:
#   1. optional instance-of hop, then any number of subclass-of hops
#      (``*0..`` includes the zero-length path, so the seed binds as its
#      own ancestor and is excluded by the id filter, as in SPARQL);
#   2. brand (P1716) or part-of (P361) direct claims;
#   3. part-of expressed as a statement qualifier (``pq:P361``).
_ANCESTOR_QUERY = """\
MATCH (s:Entity {id: $qid})-[:P31*0..1]->()-[:P279*0..]->(a:Entity)
WHERE a.id <> $qid
RETURN DISTINCT a.id AS ancestor
UNION
MATCH (s:Entity {id: $qid})-[:P1716|P361]->(a:Entity)
WHERE a.id <> $qid
RETURN DISTINCT a.id AS ancestor
UNION
MATCH (s:Entity {id: $qid})-[:STATEMENT]->(:Statement)-[q:QUALIFIER]->(a:Entity)
WHERE q.pid = 'P361' AND a.id <> $qid
RETURN DISTINCT a.id AS ancestor
"""


def _select_ancestor_qids(client, qid):
    """Return distinct ancestor Q-IDs for ``qid`` via the per-seed traversal."""
    validate_qid(qid)
    rows = client.read(_ANCESTOR_QUERY, qid=qid)
    return [row["ancestor"] for row in rows]


def update_subject_ancestors(subject, client):
    """Replace ``subject``'s ``SubjectAncestor`` rows from the Memgraph mirror.

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
    """Replace every Subject's ancestor rows from the Memgraph mirror.

    Backfill / one-off entry point — callable from a Django shell when
    you need to populate the table without waiting for each Subject's
    next Beat refresh.
    """
    from .models import Subject

    count = 0
    with MemgraphClient() as client:
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
