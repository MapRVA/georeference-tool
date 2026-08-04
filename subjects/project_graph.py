"""Maintain the ``:ProjectSubject`` markers in the Memgraph mirror.

The marker set is small - one labeled ``:Entity`` node per Subject that
has a linked WikidataItem *and* at least one image tagged with it - and
exists so graph queries can join across Wikidata data and our own notion
of "which entities are Subjects with images in this project."

Markers rebuild wholesale (the set is tiny) on demand. Django signals on
Subject and SubjectMapping save/delete issue targeted label SET/REMOVE so
the markers stay warm between rebuilds. Signal failures are logged and
swallowed - they must not break user writes, and the next rebuild fixes
any drift.
"""

import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .memgraph import GRAPH_ERRORS, MemgraphClient, ensure_schema
from .models import Subject
from .sparql_safety import looks_like_qid

logger = logging.getLogger(__name__)

PROJECT_SUBJECT_LABEL = "ProjectSubject"

_CLEAR_MARKERS_QUERY = "MATCH (n:ProjectSubject) REMOVE n:ProjectSubject"

# MERGE keeps the old RDF behavior of markers existing for entities that
# aren't mirrored yet: the stub node is invisible to the autocomplete
# (no ``label_en``) until the closure load fills it in.
_SET_MARKERS_QUERY = """\
UNWIND $qids AS qid
MERGE (e:Entity {id: qid})
SET e:ProjectSubject
"""

_UPSERT_MARKER_QUERY = "MERGE (e:Entity {id: $qid}) SET e:ProjectSubject"

_REMOVE_MARKER_QUERY = "MATCH (e:Entity {id: $qid}) REMOVE e:ProjectSubject"


def rebuild_project_graph(client=None):
    """Wholesale-rebuild the marker set from the current Subject rows.

    Cheap because the marker set is tiny (one labeled node per Subject
    that both has a linked WikidataItem and at least one image mapping).
    Idempotent. Returns the count of markers written.
    """
    owns_client = client is None
    if owns_client:
        client = MemgraphClient()
    try:
        qids = list(
            Subject.objects.filter(
                wikidata_item__isnull=False,
                image_mappings__isnull=False,
            )
            .distinct()
            .values_list("wikidata_item__wikidata_id", flat=True)
        )

        valid_qids = []
        skipped = 0
        for qid in qids:
            if looks_like_qid(qid):
                valid_qids.append(qid)
            else:
                logger.warning("Skipping invalid Q-ID %r", qid)
                skipped += 1

        ensure_schema(client)

        def _rebuild(tx):
            tx.run(_CLEAR_MARKERS_QUERY)
            if valid_qids:
                tx.run(_SET_MARKERS_QUERY, qids=valid_qids)

        client.write_tx(_rebuild)

        logger.info(
            "Rebuilt project markers: %d subject(s) (%d skipped)",
            len(valid_qids),
            skipped,
        )
        return len(valid_qids)
    finally:
        if owns_client:
            client.close()


def sync_subject_marker(subject, client=None):
    """Add or remove ``subject``'s marker based on whether it qualifies.

    A Subject qualifies for a marker iff it has a linked WikidataItem
    *and* at least one image mapping. This is the single source of
    truth that both signal handlers (Subject + SubjectMapping) call.
    """
    if not subject.wikidata_item_id:
        return
    qid = subject.wikidata_item.wikidata_id
    if subject.image_mappings.exists():
        upsert_subject_marker(qid, client=client)
    else:
        remove_subject_marker(qid, client=client)


def upsert_subject_marker(qid, client=None):
    """Ensure the ``:ProjectSubject`` label is set for ``qid``.

    ``MERGE`` + ``SET`` label is idempotent — re-marking a marked entity
    is a no-op, like the ``INSERT DATA`` it replaces.
    """
    if not looks_like_qid(qid):
        logger.warning("Refusing to upsert marker for invalid Q-ID %r", qid)
        return
    _safe_write(
        _UPSERT_MARKER_QUERY, client, qid=qid, action=f"upsert marker for {qid}"
    )


def remove_subject_marker(qid, client=None):
    """Remove the ``:ProjectSubject`` label from ``qid`` (no-op if absent)."""
    if not looks_like_qid(qid):
        logger.warning("Refusing to remove marker for invalid Q-ID %r", qid)
        return
    _safe_write(
        _REMOVE_MARKER_QUERY, client, qid=qid, action=f"remove marker for {qid}"
    )


def _safe_write(query, client, *, qid, action):
    """Run a marker write; swallow only graph/transport failures.

    Called from post_save/post_delete signal handlers — uncaught exceptions
    would propagate through ``Subject.save()`` and break user writes.
    ``GRAPH_ERRORS`` (network blips, Memgraph server errors) is swallowed
    on the assumption that the next ``rebuild_project_graph`` reconciles
    the drift. Programming errors are intentionally allowed to propagate
    so they surface instead of silently corrupting the marker set.
    """
    owns_client = client is None
    if owns_client:
        client = MemgraphClient()
    try:
        client.write(query, qid=qid)
    except GRAPH_ERRORS as e:
        logger.warning(
            "Memgraph write failed during %s: %s — "
            "next rebuild_project_graph will reconcile",
            action,
            e,
        )
    finally:
        if owns_client:
            client.close()


@receiver(post_save, sender=Subject)
def _on_subject_saved(sender, instance, **kwargs):
    sync_subject_marker(instance)


@receiver(post_delete, sender=Subject)
def _on_subject_deleted(sender, instance, **kwargs):
    if not instance.wikidata_item_id:
        return
    try:
        qid = instance.wikidata_item.wikidata_id
    except Exception:
        return
    remove_subject_marker(qid)


def _import_subject_mapping():
    """Lazy import to avoid a circular at app-init time."""
    from images.models import SubjectMapping

    return SubjectMapping


def _on_subject_mapping_saved(sender, instance, **kwargs):
    sync_subject_marker(instance.subject)


def _on_subject_mapping_deleted(sender, instance, **kwargs):
    # The Subject row may already be gone (cascade); a missing Subject
    # means our marker is being removed by ``_on_subject_deleted`` anyway.
    subject = Subject.objects.filter(pk=instance.subject_id).first()
    if subject is None:
        return
    sync_subject_marker(subject)


SubjectMapping = _import_subject_mapping()
post_save.connect(_on_subject_mapping_saved, sender=SubjectMapping)
post_delete.connect(_on_subject_mapping_deleted, sender=SubjectMapping)
