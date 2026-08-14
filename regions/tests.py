from unittest import mock

import pyoxigraph
import requests
from django.db.models import ProtectedError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from images.models import Collection, Image, Source
from subjects.models import Subject, WikidataItem
from subjects.sparql_safety import UnsafeSparqlInput
from subjects.tasks import _do_refresh_wikidata_item, get_next_stale_wikidata_item

from .admin import RegionAdminForm
from .models import Region, RegionAncestor
from .region_ancestors import update_region_ancestors
from .wikidata_check import ALLOWED_ROOT_CLASSES, region_class_ask_query


class EffectiveRegionTests(SimpleTestCase):
    """The image -> collection -> source resolution chain.

    Pure in-memory: the properties only read FK attributes, so unsaved
    instances exercise them without a database.
    """

    def setUp(self):
        self.r_source = Region(title="Source Region", slug="source-region")
        self.r_coll = Region(title="Collection Region", slug="collection-region")
        self.r_image = Region(title="Image Region", slug="image-region")
        self.source = Source(name="Src", slug="src")
        self.collection = Collection(name="Coll", slug="coll", source=self.source)
        self.image = Image(title="Img", collection=self.collection)

    def test_image_region_wins(self):
        self.source.region = self.r_source
        self.collection.region = self.r_coll
        self.image.region = self.r_image
        self.assertIs(self.image.effective_region, self.r_image)

    def test_collection_region_when_image_none(self):
        self.source.region = self.r_source
        self.collection.region = self.r_coll
        self.assertIs(self.image.effective_region, self.r_coll)

    def test_source_region_when_collection_and_image_none(self):
        self.source.region = self.r_source
        self.assertIs(self.image.effective_region, self.r_source)

    def test_none_when_no_region_anywhere(self):
        self.assertIsNone(self.image.effective_region)

    def test_collection_effective_region_falls_back_to_source(self):
        self.source.region = self.r_source
        self.assertIs(self.collection.effective_region, self.r_source)
        self.collection.region = self.r_coll
        self.assertIs(self.collection.effective_region, self.r_coll)


class RegionProtectTests(TestCase):
    """Deleting a referenced Region must be refused, not cascaded."""

    def test_delete_refused_while_referenced(self):
        item = WikidataItem.objects.bulk_create(
            [WikidataItem(wikidata_id="Q950", title="Test Region")]
        )[0]
        region = Region.objects.create(title="Test Region", slug="test", wikidata_item=item)
        Source.objects.create(
            name="Src", slug="src", url="https://example.com", description="",
            region=region,
        )
        with self.assertRaises(ProtectedError):
            region.delete()


@mock.patch("regions.admin.check_region_class")
class RegionAdminFormTests(TestCase):
    """Q-ID validation and WikidataItem wiring in the admin form."""

    @classmethod
    def setUpTestData(cls):
        # bulk_create bypasses WikidataItem.save(), which fetches live
        # Wikidata metadata on insert.
        cls.existing_item = WikidataItem.objects.bulk_create(
            [WikidataItem(wikidata_id="Q1370", title="Virginia")]
        )[0]

    def _form(self, instance=None, **data):
        payload = {"title": "Somewhere", "slug": "somewhere", "wikidata_id": "Q43421"}
        payload.update(data)
        return RegionAdminForm(payload, instance=instance)

    def test_rejects_bad_qid_grammar(self, check):
        for bad in ("", "P31", "Q042", "Q42 x", "43421"):
            form = self._form(wikidata_id=bad)
            self.assertFalse(form.is_valid(), bad)
            self.assertIn("wikidata_id", form.errors)
        check.assert_not_called()

    def test_normalizes_lowercase_qid(self, check):
        check.return_value = True
        form = self._form(wikidata_id="q43421")
        self.assertTrue(form.is_valid(), form.errors)
        check.assert_called_once_with("Q43421")
        with mock.patch.object(
            WikidataItem, "populate_from_wikidata", return_value=True
        ):
            region = form.save()
        self.assertEqual(region.wikidata_item.wikidata_id, "Q43421")

    def test_rejects_qid_used_by_another_region(self, check):
        Region.objects.create(
            title="Virginia", slug="virginia", wikidata_item=self.existing_item
        )
        form = self._form(wikidata_id="Q1370")
        self.assertFalse(form.is_valid())
        self.assertIn("Virginia", str(form.errors["wikidata_id"]))
        check.assert_not_called()

    def test_failed_check_blocks_with_root_classes_in_message(self, check):
        check.return_value = False
        form = self._form(wikidata_id="Q1370")
        self.assertFalse(form.is_valid())
        message = str(form.errors["wikidata_id"])
        self.assertIn("Virginia", message)  # the cached item's label
        for root in ALLOWED_ROOT_CLASSES:
            self.assertIn(root, message)

    def test_network_failure_blocks_with_retry_message(self, check):
        check.side_effect = requests.ConnectionError("boom")
        form = self._form()
        self.assertFalse(form.is_valid())
        self.assertIn("try again", str(form.errors["wikidata_id"]))

    def test_reuses_existing_wikidata_item(self, check):
        check.return_value = True
        form = self._form(wikidata_id="Q1370")
        self.assertTrue(form.is_valid(), form.errors)
        with mock.patch.object(WikidataItem, "populate_from_wikidata") as populate:
            region = form.save()
        populate.assert_not_called()
        self.assertEqual(region.wikidata_item, self.existing_item)
        self.assertEqual(WikidataItem.objects.count(), 1)

    def test_creates_missing_wikidata_item(self, check):
        check.return_value = True
        form = self._form(wikidata_id="Q43421")
        self.assertTrue(form.is_valid(), form.errors)
        with mock.patch.object(
            WikidataItem, "populate_from_wikidata", return_value=True
        ):
            region = form.save()
        self.assertTrue(WikidataItem.objects.filter(wikidata_id="Q43421").exists())
        self.assertEqual(region.wikidata_item.wikidata_id, "Q43421")

    def test_title_defaults_to_item_label(self, check):
        check.return_value = True
        form = self._form(wikidata_id="Q1370", title="", slug="virginia")
        self.assertTrue(form.is_valid(), form.errors)
        region = form.save()
        self.assertEqual(region.title, "Virginia")

    def test_missing_slug_rejected(self, check):
        check.return_value = True
        form = self._form(slug="")
        self.assertFalse(form.is_valid())
        self.assertIn("slug", form.errors)

    def test_duplicate_slug_rejected(self, check):
        check.return_value = True
        Region.objects.create(
            title="Virginia", slug="somewhere", wikidata_item=self.existing_item
        )
        form = self._form()
        self.assertFalse(form.is_valid())
        self.assertIn("slug", form.errors)

    def test_edit_with_unchanged_qid_skips_check(self, check):
        region = Region.objects.create(
            title="Virginia", slug="virginia", wikidata_item=self.existing_item
        )
        form = self._form(
            instance=region, wikidata_id="Q1370", title="Old Virginia", slug="virginia"
        )
        self.assertTrue(form.is_valid(), form.errors)
        check.assert_not_called()
        region = form.save()
        self.assertEqual(region.title, "Old Virginia")


class RegionSaveHydrationTests(TestCase):
    """Region.save() re-hydrates already-mirrored items (for P131)."""

    @classmethod
    def setUpTestData(cls):
        cls.hydrated, cls.fresh = WikidataItem.objects.bulk_create(
            [
                WikidataItem(
                    wikidata_id="Q9001",
                    title="Hydrated",
                    sparql_last_loaded_at=timezone.now(),
                ),
                WikidataItem(wikidata_id="Q9002", title="Fresh"),
            ]
        )

    def test_attach_to_hydrated_item_enqueues_rehydration(self):
        with mock.patch("subjects.tasks.hydrate_wikidata_item.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                Region.objects.create(
                    title="R", slug="r1", wikidata_item=self.hydrated
                )
        delay.assert_called_once_with("Q9001")

    def test_attach_to_unhydrated_item_does_not_enqueue(self):
        # The item's own save() already queued hydration, which runs
        # post-commit and therefore sees the Region row.
        with mock.patch("subjects.tasks.hydrate_wikidata_item.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                Region.objects.create(title="R", slug="r2", wikidata_item=self.fresh)
        delay.assert_not_called()

    def test_qid_change_on_edit_enqueues_rehydration(self):
        region = Region.objects.create(
            title="R", slug="r3", wikidata_item=self.fresh
        )
        with mock.patch("subjects.tasks.hydrate_wikidata_item.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                region.wikidata_item = self.hydrated
                region.save()
        delay.assert_called_once_with("Q9001")

    def test_title_only_edit_does_not_enqueue(self):
        # Created outside captureOnCommitCallbacks, so the creation's own
        # on_commit callback is never executed.
        region = Region.objects.create(
            title="R", slug="r4", wikidata_item=self.hydrated
        )
        with mock.patch("subjects.tasks.hydrate_wikidata_item.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                region.title = "Renamed"
                region.save()
        delay.assert_not_called()


class _RecordingClient:
    """Stands in for MemgraphClient: canned rows, recorded queries."""

    def __init__(self, rows):
        self._rows = rows
        self.queries = []

    def read(self, query, **params):
        self.queries.append((query, params))
        return self._rows


class RegionAncestorUpdateTests(TestCase):
    """The Memgraph -> Postgres containment projection."""

    @classmethod
    def setUpTestData(cls):
        cls.seed, cls.county, cls.state = WikidataItem.objects.bulk_create(
            [
                WikidataItem(wikidata_id="Q800", title="Test Town"),
                WikidataItem(wikidata_id="Q810", title="Test County"),
                WikidataItem(wikidata_id="Q820", title="Test State"),
            ]
        )
        cls.region = Region.objects.create(
            title="Test Town", slug="test-town", wikidata_item=cls.seed
        )

    def _ancestor_qids(self):
        return set(
            self.region.ancestors.values_list("ancestor__wikidata_id", flat=True)
        )

    def test_update_replaces_rows(self):
        RegionAncestor.objects.create(region=self.region, ancestor=self.state)
        count = update_region_ancestors(
            self.region, _RecordingClient([{"ancestor": "Q810"}])
        )
        self.assertEqual(count, 1)
        self.assertEqual(self._ancestor_qids(), {"Q810"})

    def test_ancestors_without_wikidataitem_rows_dropped(self):
        count = update_region_ancestors(
            self.region,
            _RecordingClient([{"ancestor": "Q810"}, {"ancestor": "Q999"}]),
        )
        self.assertEqual(count, 1)
        self.assertEqual(self._ancestor_qids(), {"Q810"})

    def test_query_is_containment_only(self):
        client = _RecordingClient([])
        update_region_ancestors(self.region, client)
        query, params = client.queries[0]
        self.assertEqual(params, {"qid": "Q800"})
        self.assertIn("P131", query)
        for excluded in (":P31", "P279", "P361", "P1716", "QUALIFIER"):
            self.assertNotIn(excluded, query)


# A miniature P31/P279 neighbourhood for evaluating the ASK in-memory.
_ASK_FIXTURE_TTL = """\
@prefix wd: <http://www.wikidata.org/entity/> .
@prefix wdt: <http://www.wikidata.org/prop/direct/> .

# Q1 -P31-> Q2 -P279-> Q3 -P279-> territory: qualifies.
wd:Q1 wdt:P31 wd:Q2 .
wd:Q2 wdt:P279 wd:Q3 .
wd:Q3 wdt:P279 wd:Q4835091 .

# Q7 is an instance of an unrelated class: does not qualify.
wd:Q7 wdt:P31 wd:Q5 .
"""


class RegionAskQueryTests(SimpleTestCase):
    """Structure and semantics of the territory ASK."""

    def test_ask_contains_all_allowed_roots(self):
        query = region_class_ask_query("Q42")
        for root in ALLOWED_ROOT_CLASSES:
            self.assertIn(f"wd:{root}", query)
        self.assertNotIn("{qid}", query)
        self.assertNotIn("{roots}", query)

    def test_rejects_invalid_qids(self):
        for bad in ("Q42; DROP ALL", "P31", "", "Q042", None, "Q42 "):
            with self.assertRaises(UnsafeSparqlInput):
                region_class_ask_query(bad)

    def test_ask_is_valid_sparql(self):
        # pyoxigraph parses the query eagerly - a syntax error raises here.
        pyoxigraph.Store().query(region_class_ask_query("Q42"))

    def test_ask_semantics(self):
        store = pyoxigraph.Store()
        store.load(_ASK_FIXTURE_TTL.encode(), format=pyoxigraph.RdfFormat.TURTLE)
        self.assertTrue(bool(store.query(region_class_ask_query("Q1"))))
        self.assertFalse(bool(store.query(region_class_ask_query("Q7"))))


@mock.patch("subjects.tasks.update_region_ancestors")
@mock.patch("subjects.tasks.update_subject_ancestors")
@mock.patch("subjects.tasks.MemgraphClient")
@mock.patch("subjects.tasks.commit_closure_to_memgraph")
@mock.patch.object(WikidataItem, "_apply_seed_metadata")
@mock.patch("subjects.tasks.fetch_seed_data")
class RefreshTaskRegionTests(TestCase):
    """Region awareness of the WikidataItem refresh machinery."""

    _SEED_DATA = {"metadata": {}, "groups": {"stub": []}, "labels": {}}

    @classmethod
    def setUpTestData(cls):
        cls.region_item, cls.subject_item, cls.bare_item = (
            WikidataItem.objects.bulk_create(
                [
                    WikidataItem(wikidata_id="Q860", title="Region Item"),
                    WikidataItem(wikidata_id="Q861", title="Subject Item"),
                    WikidataItem(wikidata_id="Q862", title="Bare Ancestor"),
                ]
            )
        )
        cls.region = Region.objects.create(
            title="Region Item", slug="region-item", wikidata_item=cls.region_item
        )
        cls.subject = Subject.objects.create(
            title="Subject Item", wikidata_item=cls.subject_item
        )

    def test_region_item_refresh_uses_p131_variant(
        self, fetch, apply_meta, commit, client, upd_subject, upd_region
    ):
        fetch.return_value = self._SEED_DATA
        result = _do_refresh_wikidata_item(self.region_item)
        self.assertEqual(result["status"], "success")
        fetch.assert_called_once_with("Q860", include_p131=True)
        upd_region.assert_called_once()
        self.assertEqual(upd_region.call_args.args[0], self.region)
        upd_subject.assert_not_called()

    def test_subject_item_refresh_uses_default_variant(
        self, fetch, apply_meta, commit, client, upd_subject, upd_region
    ):
        fetch.return_value = self._SEED_DATA
        result = _do_refresh_wikidata_item(self.subject_item)
        self.assertEqual(result["status"], "success")
        fetch.assert_called_once_with("Q861", include_p131=False)
        upd_subject.assert_called_once()
        upd_region.assert_not_called()

    def test_stale_rotation_includes_regions_but_not_bare_ancestors(
        self, fetch, apply_meta, commit, client, upd_subject, upd_region
    ):
        # All three fixture items are unhydrated; only the subject-linked
        # and region-linked ones may enter the Beat rotation.
        candidates = set()
        for _ in range(2):
            item = get_next_stale_wikidata_item()
            self.assertIsNotNone(item)
            candidates.add(item.wikidata_id)
            WikidataItem.objects.filter(pk=item.pk).update(
                sparql_last_loaded_at=timezone.now()
            )
        self.assertEqual(candidates, {"Q860", "Q861"})
        self.assertIsNone(get_next_stale_wikidata_item())
