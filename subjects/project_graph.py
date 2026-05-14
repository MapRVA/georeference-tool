"""Maintain the ``<urn:yesterdays:subjects>`` named graph in Oxigraph.

The graph is small - one marker triple per Subject that has a linked
WikidataItem - and exists so that SPARQL queries can join across Wikidata
data and our own notion of "which entities are Subjects in this project."

Triples have the shape::

    <http://www.wikidata.org/entity/Q12345> a <urn:yesterdays:Subject> .

The graph rebuilds wholesale (it's tiny) on demand. Django signals issue
targeted INSERT/DELETE on Subject save/delete so the graph stays warm
between rebuilds. Signal failures are logged and swallowed - they must
not break Subject saves, and the next rebuild fixes any drift.
"""

import logging

import requests
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Subject
from .oxigraph import OxigraphClient
from .sparql_safety import UnsafeSparqlInput, sparql_wikidata_entity_iri

logger = logging.getLogger(__name__)

PROJECT_GRAPH_IRI = "urn:yesterdays:subjects"
SUBJECT_CLASS_IRI = "urn:yesterdays:Subject"
RDF_TYPE_IRI = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


def _marker_triple(qid):
    """Single ``<wd:Qxxx> rdf:type <project:Subject> .`` triple for ``qid``."""
    return f"{sparql_wikidata_entity_iri(qid)} <{RDF_TYPE_IRI}> <{SUBJECT_CLASS_IRI}> ."


def rebuild_project_graph(client=None):
    """Wholesale-rebuild the project graph from the current Subject rows.

    Cheap because the graph is tiny (one triple per Subject with a linked
    WikidataItem). Idempotent. Returns the count of marker triples written.
    """
    owns_client = client is None
    if owns_client:
        client = OxigraphClient()
    try:
        qids = list(
            Subject.objects.filter(wikidata_item__isnull=False).values_list(
                "wikidata_item__wikidata_id", flat=True
            )
        )

        triples = []
        skipped = 0
        for qid in qids:
            try:
                triples.append(_marker_triple(qid))
            except UnsafeSparqlInput as e:
                logger.warning("Skipping invalid Q-ID %r: %s", qid, e)
                skipped += 1

        triples_block = "\n".join(triples)
        update = (
            f"DROP SILENT GRAPH <{PROJECT_GRAPH_IRI}> ;\n"
            f"INSERT DATA {{ GRAPH <{PROJECT_GRAPH_IRI}> {{\n"
            f"{triples_block}\n"
            f"}} }}"
        )
        client.update(update)

        logger.info(
            "Rebuilt project graph: %d marker triples (%d skipped)",
            len(triples),
            skipped,
        )
        return len(triples)
    finally:
        if owns_client:
            client.close()


def upsert_subject_marker(qid, client=None):
    """Ensure the marker triple for ``qid`` is present in the project graph.

    RDF graphs are sets, so ``INSERT DATA`` is idempotent — re-inserting an
    existing triple is a no-op. No prior DELETE needed.
    """
    try:
        marker = _marker_triple(qid)
    except UnsafeSparqlInput as e:
        logger.warning("Refusing to upsert invalid Q-ID %r: %s", qid, e)
        return
    update = f"INSERT DATA {{ GRAPH <{PROJECT_GRAPH_IRI}> {{ {marker} }} }}"
    _safe_update(update, client, action=f"upsert marker for {qid}")


def remove_subject_marker(qid, client=None):
    """Remove the marker triple for ``qid`` from the project graph."""
    try:
        marker = _marker_triple(qid)
    except UnsafeSparqlInput as e:
        logger.warning("Refusing to remove invalid Q-ID %r: %s", qid, e)
        return
    update = f"DELETE WHERE {{ GRAPH <{PROJECT_GRAPH_IRI}> {{ {marker} }} }}"
    _safe_update(update, client, action=f"remove marker for {qid}")


def _safe_update(update, client, action):
    """Run a SPARQL Update; swallow only network/HTTP failures.

    Called from post_save/post_delete signal handlers — uncaught exceptions
    would propagate through ``Subject.save()`` and break user writes.
    ``requests.RequestException`` (network blips, Oxigraph 5xx) is swallowed
    on the assumption that the next ``rebuild_project_graph`` reconciles
    the drift. Programming errors are intentionally allowed to propagate
    so they surface instead of silently corrupting the project graph.
    """
    owns_client = client is None
    if owns_client:
        client = OxigraphClient()
    try:
        client.update(update)
    except requests.RequestException as e:
        logger.warning(
            "Oxigraph update failed during %s (network): %s — "
            "next rebuild_project_graph will reconcile",
            action,
            e,
        )
    finally:
        if owns_client:
            client.close()


@receiver(post_save, sender=Subject)
def _on_subject_saved(sender, instance, **kwargs):
    if not instance.wikidata_item_id:
        return
    upsert_subject_marker(instance.wikidata_item.wikidata_id)


@receiver(post_delete, sender=Subject)
def _on_subject_deleted(sender, instance, **kwargs):
    if not instance.wikidata_item_id:
        return
    try:
        qid = instance.wikidata_item.wikidata_id
    except Exception:
        return
    remove_subject_marker(qid)
