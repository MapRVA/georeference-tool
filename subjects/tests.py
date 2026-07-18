from pathlib import Path

import numpy as np
import pyoxigraph
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings

from images.models import Collection, CollectionEmbeddingStats, Image, Source
from images.tasks import (
    refresh_collection_embedding_stats,
    refresh_next_collection_embedding_stats,
)

from .similarity import build_subject_query_embedding
from .sparql_safety import UnsafeSparqlInput, looks_like_pid, looks_like_qid
from .wikidata_closure import (
    build_atomic_update,
    closure_query,
    extract_seed_metadata,
    parse_closure,
)

DIM = 768


def _unit(seed):
    rng = np.random.default_rng(seed)
    v = rng.normal(size=DIM)
    return v / np.linalg.norm(v)


def _cos(a, b):
    a, b = np.asarray(a), np.asarray(b)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


class BuildSubjectQueryEmbeddingTests(TestCase):
    """The collection-centered query builder (subjects/similarity.py)."""

    @classmethod
    def setUpTestData(cls):
        cls.source = Source.objects.create(
            name="Src", slug="src", url="https://example.com", description=""
        )
        cls.coll_a = Collection.objects.create(
            source=cls.source, name="A", slug="a", url="https://example.com"
        )
        cls.coll_b = Collection.objects.create(
            source=cls.source, name="B", slug="b", url="https://example.com"
        )
        # Orthogonal-ish directions for "content" and two collection "styles"
        cls.content = _unit(1)
        cls.style_a = _unit(2)
        cls.style_b = _unit(3)

    def _image(self, style, content_weight=0.5):
        """A synthetic unit embedding: collection style plus subject content."""
        v = style + content_weight * self.content
        return (v / np.linalg.norm(v)).tolist()

    def test_no_embeddings_returns_none(self):
        self.assertIsNone(build_subject_query_embedding([]))
        self.assertIsNone(build_subject_query_embedding([(self.coll_a.pk, None)]))

    def test_without_stats_falls_back_to_plain_centroid(self):
        rows = [
            (self.coll_a.pk, self._image(self.style_a)),
            (self.coll_b.pk, self._image(self.style_b)),
        ]
        query = build_subject_query_embedding(rows)
        X = np.array([r[1] for r in rows])
        X /= np.linalg.norm(X, axis=1, keepdims=True)
        centroid = X.mean(axis=0)
        centroid /= np.linalg.norm(centroid)
        self.assertAlmostEqual(_cos(query, centroid), 1.0, places=6)
        self.assertAlmostEqual(float(np.linalg.norm(query)), 1.0, places=6)

    def test_collection_centering_cancels_style(self):
        # Collection means dominated by style; images share the content signal
        CollectionEmbeddingStats.objects.create(
            collection=self.coll_a,
            mean_embedding=self.style_a.tolist(),
            embedding_count=1000,
        )
        CollectionEmbeddingStats.objects.create(
            collection=self.coll_b,
            mean_embedding=self.style_b.tolist(),
            embedding_count=1000,
        )
        rows = [
            (self.coll_a.pk, self._image(self.style_a)),
            (self.coll_b.pk, self._image(self.style_b)),
        ]
        query = np.array(build_subject_query_embedding(rows))
        plain = np.array([r[1] for r in rows]).mean(axis=0)

        # The centered query should align with content far better than the
        # plain centroid, and style alignment should shrink
        self.assertGreater(_cos(query, self.content), _cos(plain, self.content))
        self.assertGreater(_cos(query, self.content), 0.8)
        self.assertLess(abs(_cos(query, self.style_a)), abs(_cos(plain, self.style_a)))

    def test_near_duplicates_collapse(self):
        # Four copies of one view plus one distinct view: without dedupe the
        # duplicated view dominates the centroid; with dedupe both views
        # contribute equally
        view1 = self._image(self.style_a, content_weight=0.3)
        view2 = self._image(self.style_b, content_weight=0.3)
        rows = [(self.coll_a.pk, view1)] * 4 + [(self.coll_b.pk, view2)]
        query = np.array(build_subject_query_embedding(rows))
        expected = np.array(view1) + np.array(view2)
        expected /= np.linalg.norm(expected)
        self.assertAlmostEqual(_cos(query, expected), 1.0, places=6)

    def test_degenerate_residuals_fall_back_to_centroid(self):
        # A set image exactly at its (unshrunk-dominant) collection mean has
        # no residual; with only such images the builder falls back
        big_n = 10**9  # overwhelm shrinkage so mu_c ~= mean_c
        emb = self._image(self.style_a)
        CollectionEmbeddingStats.objects.create(
            collection=self.coll_a, mean_embedding=emb, embedding_count=big_n
        )
        query = build_subject_query_embedding([(self.coll_a.pk, emb)])
        self.assertAlmostEqual(_cos(query, np.array(emb)), 1.0, places=5)


class RefreshCollectionEmbeddingStatsTests(TestCase):
    """The per-collection mean embedding refresh tasks."""

    @classmethod
    def setUpTestData(cls):
        cls.source = Source.objects.create(
            name="Src", slug="src", url="https://example.com", description=""
        )
        cls.collection = Collection.objects.create(
            source=cls.source, name="A", slug="a", url="https://example.com"
        )
        cls.other = Collection.objects.create(
            source=cls.source, name="B", slug="b", url="https://example.com"
        )

    def _image(self, title, embedding, collection=None, **kwargs):
        return Image.objects.create(
            collection=collection or self.collection,
            title=title,
            permalink=f"https://img.example.com/{title}.jpg",
            embedding=embedding,
            **kwargs,
        )

    def test_computes_mean_and_count(self):
        self._image("one", [1.0] * DIM)
        self._image("two", [3.0] * DIM)
        self._image("no-embedding", None)

        refresh_collection_embedding_stats()

        stats = CollectionEmbeddingStats.objects.get(collection=self.collection)
        self.assertEqual(stats.embedding_count, 2)
        self.assertEqual(len(stats.mean_embedding), DIM)
        self.assertAlmostEqual(stats.mean_embedding[0], 2.0, places=5)

    def test_duplicates_excluded_even_when_searchable(self):
        original = self._image("one", [1.0] * DIM)
        duplicate = self._image("dupe", [9.0] * DIM)
        # Bypass signals so is_searchable stays True: the explicit
        # duplicate_of condition alone must exclude this image
        Image.objects.filter(pk=duplicate.pk).update(duplicate_of=original.pk)
        self.assertTrue(Image.objects.get(pk=duplicate.pk).is_searchable)

        refresh_collection_embedding_stats()

        stats = CollectionEmbeddingStats.objects.get(collection=self.collection)
        self.assertEqual(stats.embedding_count, 1)
        self.assertAlmostEqual(stats.mean_embedding[0], 1.0, places=5)

    def test_unsearchable_images_excluded_and_stale_rows_removed(self):
        image = self._image("one", [1.0] * DIM)
        refresh_collection_embedding_stats()
        self.assertTrue(
            CollectionEmbeddingStats.objects.filter(collection=self.collection).exists()
        )

        Image.objects.filter(pk=image.pk).update(is_searchable=False)
        refresh_collection_embedding_stats()
        self.assertFalse(
            CollectionEmbeddingStats.objects.filter(collection=self.collection).exists()
        )

    def test_refresh_next_picks_most_stale_collection(self):
        # collection drifts by 2 images, other by 1 -> collection goes first
        self._image("a1", [1.0] * DIM)
        self._image("a2", [1.0] * DIM)
        self._image("b1", [2.0] * DIM, collection=self.other)

        refresh_next_collection_embedding_stats()
        self.assertTrue(
            CollectionEmbeddingStats.objects.filter(collection=self.collection).exists()
        )
        self.assertFalse(
            CollectionEmbeddingStats.objects.filter(collection=self.other).exists()
        )

        refresh_next_collection_embedding_stats()
        self.assertTrue(
            CollectionEmbeddingStats.objects.filter(collection=self.other).exists()
        )

    def test_refresh_next_noop_when_in_sync(self):
        self._image("one", [1.0] * DIM)
        refresh_collection_embedding_stats()
        stats = CollectionEmbeddingStats.objects.get(collection=self.collection)
        before = stats.updated_at

        refresh_next_collection_embedding_stats()

        stats.refresh_from_db()
        self.assertEqual(stats.updated_at, before)
        # No row invented for the empty collection either
        self.assertFalse(
            CollectionEmbeddingStats.objects.filter(collection=self.other).exists()
        )

    def test_refresh_next_removes_row_when_collection_empties(self):
        image = self._image("one", [1.0] * DIM)
        refresh_collection_embedding_stats()

        Image.objects.filter(pk=image.pk).update(is_searchable=False)
        refresh_next_collection_embedding_stats()

        self.assertFalse(
            CollectionEmbeddingStats.objects.filter(collection=self.collection).exists()
        )


# --- Wikidata closure tests -------------------------------------------------

_WD = "http://www.wikidata.org/entity/"
_WDS = "http://www.wikidata.org/entity/statement/"
_WDT = "http://www.wikidata.org/prop/direct/"
_RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"


def _wd(local):
    return pyoxigraph.NamedNode(f"{_WD}{local}")


def _wdt(pid):
    return pyoxigraph.NamedNode(f"{_WDT}{pid}")


def _label(entity, text, lang="en"):
    return pyoxigraph.Triple(
        _wd(entity),
        pyoxigraph.NamedNode(_RDFS_LABEL),
        pyoxigraph.Literal(text, language=lang),
    )


# A miniature Wikidata neighbourhood for running the closure CONSTRUCT
# against in-memory. Exercises what a recorded WDQS fixture can't: triples
# that must be EXCLUDED (off-language labels, non-nav predicates on
# nav-profile entities, entities no branch selects).
_CLOSURE_FIXTURE_TTL = """\
@prefix wd: <http://www.wikidata.org/entity/> .
@prefix wds: <http://www.wikidata.org/entity/statement/> .
@prefix wdt: <http://www.wikidata.org/prop/direct/> .
@prefix p: <http://www.wikidata.org/prop/> .
@prefix ps: <http://www.wikidata.org/prop/statement/> .
@prefix pq: <http://www.wikidata.org/prop/qualifier/> .
@prefix wikibase: <http://wikiba.se/ontology#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <http://schema.org/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

# Seed: a historic hall with a heritage-designation statement (qualified
# by the district it sits in) and an authority-control identifier.
wd:Q100 rdfs:label "Test Hall"@en, "Salle d'essai"@fr ;
    schema:description "historic building"@en ;
    wdt:P31 wd:Q200 ;
    wdt:P84 wd:Q300 ;
    wdt:P1435 wd:Q400 ;
    wdt:P5473 "127-0345" ;
    p:P1435 wds:Q100-aaaa-bbbb .

wds:Q100-aaaa-bbbb ps:P1435 wd:Q400 ;
    pq:P361 wd:Q500 .

# Class chain: Q100 -P31-> Q200 -P279-> Q210
wd:Q200 rdfs:label "building"@en, "bâtiment"@fr ;
    wdt:P279 wd:Q210 .
wd:Q210 rdfs:label "structure"@en .

# Direct reference (architect) with its own onward claim.
wd:Q300 rdfs:label "Test Architect"@en ;
    wdt:P31 wd:Q5 ;
    wdt:P800 wd:Q999 .

# Only reachable one hop past a direct reference - no branch selects it.
wd:Q5 rdfs:label "human"@en .

wd:Q400 rdfs:label "historic landmark"@en .

# Qualifier target: nav profile only, so its P571 must not come along.
wd:Q500 rdfs:label "Test District"@en, "Quartier d'essai"@fr ;
    wdt:P571 "1900-01-01T00:00:00Z"^^xsd:dateTime .

# P1629 target of the authority property: nav profile.
wd:Q600 rdfs:label "Test Register"@en, "Registre d'essai"@fr ;
    wdt:P571 "1966-01-01T00:00:00Z"^^xsd:dateTime .

# A non-authority property descriptor - the generalized descriptor branch
# must mirror it too.
wd:P1435 wikibase:directClaim wdt:P1435 ;
    rdfs:label "heritage designation"@en ;
    wdt:P31 wd:Q18608871 .

# An authority-control property descriptor (P31 Q18618628).
wd:P5473 wikibase:directClaim wdt:P5473 ;
    rdfs:label "Test Register number"@en, "numéro au registre"@fr ;
    wdt:P31 wd:Q18618628 ;
    wdt:P1630 "https://register.example/$1" ;
    wdt:P1629 wd:Q600 .

<https://en.wikipedia.org/wiki/Test_Hall> schema:about wd:Q100 ;
    schema:isPartOf <https://en.wikipedia.org/> .
"""


class ClosureQueryTests(SimpleTestCase):
    """Input validation and structure of the assembled closure CONSTRUCT."""

    def test_rejects_invalid_qids(self):
        for bad in ("Q42; DROP ALL", "P31", "", "Q042", None, "Q42 "):
            with self.assertRaises(UnsafeSparqlInput):
                closure_query(bad)

    def test_rejects_invalid_language_tags(self):
        with override_settings(WIKIDATA_MIRROR_LANGUAGES=['en"), DROP ALL; #']):
            with self.assertRaises(UnsafeSparqlInput):
                closure_query("Q42")

    def test_rejects_empty_language_list(self):
        with override_settings(WIKIDATA_MIRROR_LANGUAGES=[]):
            with self.assertRaises(ImproperlyConfigured):
                closure_query("Q42")

    def test_structure(self):
        query = closure_query("Q42")
        # 5 top-level branches (4 UNIONs) + 1 inner in the full-profile
        # branch + 2 inner in the nav-profile branch.
        self.assertEqual(query.count("UNION"), 7)
        # The nav predicate whitelist exists exactly once (shared tail).
        self.assertEqual(query.count("skos:altLabel"), 1)
        # One language filter per emission tail: seed, full, nav, descriptors.
        self.assertEqual(query.count('lang(?o) IN ("en")'), 4)
        # No leftover placeholders and no synthetic predicates.
        self.assertNotIn("{qid}", query)
        self.assertNotIn("{lang_filter}", query)
        self.assertNotIn("urn:yesterdays", query)
        self.assertEqual(query.count("{"), query.count("}"))

    def test_language_setting_reaches_filter(self):
        with override_settings(WIKIDATA_MIRROR_LANGUAGES=["en", "fr"]):
            self.assertIn('lang(?o) IN ("en", "fr")', closure_query("Q42"))

    def test_query_is_valid_sparql(self):
        # pyoxigraph parses the query eagerly - a syntax error raises here.
        pyoxigraph.Store().query(closure_query("Q42"))


class ClosureQuerySemanticsTests(SimpleTestCase):
    """Run the closure CONSTRUCT against the in-memory fixture graph."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.store = pyoxigraph.Store()
        cls.store.load(
            _CLOSURE_FIXTURE_TTL.encode(), format=pyoxigraph.RdfFormat.TURTLE
        )

    def _closure(self, qid="Q100"):
        return set(self.store.query(closure_query(qid)))

    def test_seed_literals_language_filtered(self):
        result = self._closure()
        self.assertIn(_label("Q100", "Test Hall"), result)
        self.assertNotIn(_label("Q100", "Salle d'essai", "fr"), result)

    def test_configured_languages_widen_the_mirror(self):
        with override_settings(WIKIDATA_MIRROR_LANGUAGES=["en", "fr"]):
            result = self._closure()
        self.assertIn(_label("Q100", "Test Hall"), result)
        self.assertIn(_label("Q100", "Salle d'essai", "fr"), result)

    def test_ancestors_get_nav_profile(self):
        result = self._closure()
        self.assertIn(_label("Q200", "building"), result)
        self.assertNotIn(_label("Q200", "bâtiment", "fr"), result)
        self.assertIn(pyoxigraph.Triple(_wd("Q200"), _wdt("P279"), _wd("Q210")), result)
        self.assertIn(_label("Q210", "structure"), result)

    def test_qualifier_target_gets_labels_but_not_statements(self):
        result = self._closure()
        self.assertIn(_label("Q500", "Test District"), result)
        self.assertFalse(
            any(
                t.subject == _wd("Q500") and t.predicate == _wdt("P571") for t in result
            )
        )

    def test_direct_reference_gets_full_profile(self):
        result = self._closure()
        self.assertIn(_label("Q300", "Test Architect"), result)
        self.assertIn(pyoxigraph.Triple(_wd("Q300"), _wdt("P800"), _wd("Q999")), result)

    def test_second_hop_entities_are_not_pulled(self):
        # Q5 is only reachable through the architect's own P31 - no branch
        # selects it, so its label stays out of the closure.
        self.assertNotIn(_label("Q5", "human"), self._closure())

    def test_statement_bodies_come_along(self):
        result = self._closure()
        stmt = pyoxigraph.NamedNode(f"{_WDS}Q100-aaaa-bbbb")
        ps = pyoxigraph.NamedNode("http://www.wikidata.org/prop/statement/P1435")
        pq = pyoxigraph.NamedNode("http://www.wikidata.org/prop/qualifier/P361")
        self.assertIn(pyoxigraph.Triple(stmt, ps, _wd("Q400")), result)
        self.assertIn(pyoxigraph.Triple(stmt, pq, _wd("Q500")), result)

    def test_descriptors_mirrored_for_every_used_property(self):
        result = self._closure()
        # Non-authority property: mirrored too (the generalization).
        self.assertIn(_label("P1435", "heritage designation"), result)
        # Authority property: full descriptor set, off-language label dropped.
        self.assertIn(_label("P5473", "Test Register number"), result)
        self.assertNotIn(_label("P5473", "numéro au registre", "fr"), result)
        self.assertIn(
            pyoxigraph.Triple(
                _wd("P5473"),
                _wdt("P1630"),
                pyoxigraph.Literal("https://register.example/$1"),
            ),
            result,
        )
        self.assertIn(
            pyoxigraph.Triple(_wd("P5473"), _wdt("P1629"), _wd("Q600")), result
        )

    def test_authority_item_mirrored_with_nav_profile(self):
        result = self._closure()
        self.assertIn(_label("Q600", "Test Register"), result)
        self.assertNotIn(_label("Q600", "Registre d'essai", "fr"), result)
        self.assertFalse(
            any(
                t.subject == _wd("Q600") and t.predicate == _wdt("P571") for t in result
            )
        )

    def test_sitelink_triples_present(self):
        result = self._closure()
        article = pyoxigraph.NamedNode("https://en.wikipedia.org/wiki/Test_Hall")
        self.assertIn(
            pyoxigraph.Triple(
                article, pyoxigraph.NamedNode("http://schema.org/about"), _wd("Q100")
            ),
            result,
        )


class ParseClosureTests(SimpleTestCase):
    """Grouping and named-graph routing of the closure response."""

    # Shaped like a (tiny) closure CONSTRUCT response.
    TTL = """\
@prefix wd: <http://www.wikidata.org/entity/> .
@prefix wds: <http://www.wikidata.org/entity/statement/> .
@prefix wdt: <http://www.wikidata.org/prop/direct/> .
@prefix ps: <http://www.wikidata.org/prop/statement/> .
@prefix wikibase: <http://wikiba.se/ontology#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <http://schema.org/> .

wd:Q100 rdfs:label "Test Hall"@en, "Salle d'essai"@fr ;
    wdt:P31 wd:Q200 .
wds:Q100-aaaa-bbbb ps:P1435 wd:Q400 .
wds:q100-cccc-dddd ps:P1435 wd:Q400 .
wd:Q200 rdfs:label "building"@en .
wd:P5473 wikibase:directClaim wdt:P5473 ;
    rdfs:label "Test Register number"@en .
<https://en.wikipedia.org/wiki/Test_Hall> schema:about wd:Q100 .
<http://www.wikidata.org/entity/QBOGUS> rdfs:label "nope"@en .
_:blank rdfs:label "anonymous"@en .
"""

    def setUp(self):
        self.groups, self.labels = parse_closure(self.TTL.encode())

    def test_entities_grouped_by_their_own_iri(self):
        self.assertIn(f"{_WD}Q100", self.groups)
        self.assertIn(f"{_WD}Q200", self.groups)

    def test_statement_triples_routed_to_owning_entity(self):
        # Both the modern (Q100-...) and legacy-lowercase (q100-...)
        # statement IRIs resolve to the same owning entity graph.
        stmt_triples = [
            t for t in self.groups[f"{_WD}Q100"] if t.subject.value.startswith(_WDS)
        ]
        self.assertEqual(len(stmt_triples), 2)

    def test_property_descriptors_get_their_own_graph(self):
        self.assertIn(f"{_WD}P5473", self.groups)
        self.assertEqual(len(self.groups[f"{_WD}P5473"]), 2)

    def test_invalid_and_foreign_subjects_dropped(self):
        self.assertNotIn(f"{_WD}QBOGUS", self.groups)
        self.assertFalse(
            any(iri.startswith("https://en.wikipedia.org/") for iri in self.groups)
        )

    def test_labels_collect_english_q_entities_only(self):
        self.assertEqual(self.labels["Q100"], "Test Hall")
        self.assertEqual(self.labels["Q200"], "building")
        self.assertNotIn("P5473", self.labels)

    def test_atomic_update_swaps_each_graph(self):
        update = build_atomic_update(self.groups)
        self.assertEqual(update.count("DROP SILENT GRAPH"), len(self.groups))
        self.assertEqual(update.count("INSERT DATA"), len(self.groups))
        self.assertIn(f"GRAPH <{_WD}P5473>", update)
