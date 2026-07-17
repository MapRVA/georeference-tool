import numpy as np
from django.test import TestCase

from images.models import Collection, CollectionEmbeddingStats, Image, Source
from images.tasks import (
    refresh_collection_embedding_stats,
    refresh_next_collection_embedding_stats,
)

from .similarity import build_subject_query_embedding

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
