import datetime
from contextlib import contextmanager
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.gis.geos import Point, Polygon
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import F
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image as PILImage

from images.models import (
    AerialGeoreference,
    Collection,
    CollectionStats,
    Georeference,
    Image,
    ImageOfTheDay,
    Source,
)
from images.tasks import process_image, reconcile_collection_stats
from images.utils import get_confidence_breakdown, get_overall_stats


class ImageOfTheDayTests(TestCase):
    """Behavior of the Image of the Day queue: default slotting, the ripple on
    insert, the slide-back on delete, locked anchors, and the deferred unique
    constraint that makes the reflow possible."""

    # A fixed anchor so day arithmetic in assertions is easy to read:
    # self.d(1) is June 1 2026, self.d(2) is June 2, and so on.
    BASE = datetime.date(2026, 6, 1)

    @classmethod
    def setUpTestData(cls):
        cls.source = Source.objects.create(
            name="Src", slug="src", url="https://example.com", description=""
        )
        cls.collection = Collection.objects.create(
            source=cls.source, name="Col", slug="col", url="https://example.com"
        )

    # -- helpers ------------------------------------------------------------

    def d(self, n):
        """Day N of the queue (1-indexed) as a concrete date."""
        return self.BASE + datetime.timedelta(days=n - 1)

    def img(self, title):
        return Image.objects.create(
            collection=self.collection,
            title=title,
            permalink=f"https://img.example.com/{title}.jpg",
        )

    def queue(self):
        """The current queue as {day: image_title} for compact assertions."""
        return {
            e.day: e.image.title for e in ImageOfTheDay.objects.select_related("image")
        }

    # -- next_available_day -------------------------------------------------

    def test_next_available_day_empty_is_today(self):
        with patch.object(timezone, "localdate", return_value=self.d(1)):
            self.assertEqual(ImageOfTheDay.next_available_day(), self.d(1))

    def test_next_available_day_skips_taken_day(self):
        ImageOfTheDay.objects.create(image=self.img("A"), day=self.d(1))
        with patch.object(timezone, "localdate", return_value=self.d(1)):
            self.assertEqual(ImageOfTheDay.next_available_day(), self.d(2))

    def test_next_available_day_after_contiguous_run(self):
        for n in (1, 2, 3):
            ImageOfTheDay.objects.create(image=self.img(f"I{n}"), day=self.d(n))
        with patch.object(timezone, "localdate", return_value=self.d(1)):
            self.assertEqual(ImageOfTheDay.next_available_day(), self.d(4))

    def test_next_available_day_fills_gap_left_by_lock(self):
        # Day 1 taken, day 3 locked, day 2 free -> day 2 is returned, not day 4.
        ImageOfTheDay.objects.create(image=self.img("A"), day=self.d(1))
        ImageOfTheDay.objects.create(image=self.img("L"), day=self.d(3), locked=True)
        with patch.object(timezone, "localdate", return_value=self.d(1)):
            self.assertEqual(ImageOfTheDay.next_available_day(), self.d(2))

    # -- timezone correctness ----------------------------------------------

    @override_settings(TIME_ZONE="America/New_York")
    def test_next_available_day_uses_site_timezone(self):
        # 03:30 UTC on June 2 is still 23:30 on June 1 in New York.
        instant = datetime.datetime(2026, 6, 2, 3, 30, tzinfo=datetime.timezone.utc)
        with patch.object(timezone, "now", return_value=instant):
            self.assertEqual(
                ImageOfTheDay.next_available_day(), datetime.date(2026, 6, 1)
            )

    @override_settings(TIME_ZONE="America/New_York")
    def test_for_today_uses_site_timezone(self):
        instant = datetime.datetime(2026, 6, 2, 3, 30, tzinfo=datetime.timezone.utc)
        entry = ImageOfTheDay.objects.create(
            image=self.img("A"), day=datetime.date(2026, 6, 1)
        )
        with patch.object(timezone, "now", return_value=instant):
            # Local day is June 1; a UTC reading would wrongly return None.
            self.assertEqual(ImageOfTheDay.for_today(), entry)

    def test_for_today_returns_none_when_empty(self):
        with patch.object(timezone, "localdate", return_value=self.d(1)):
            self.assertIsNone(ImageOfTheDay.for_today())

    # -- place: append ------------------------------------------------------

    def test_place_appends_today_then_forward(self):
        with patch.object(timezone, "localdate", return_value=self.d(1)):
            first = ImageOfTheDay.place(self.img("A"))
            second = ImageOfTheDay.place(self.img("B"))
        self.assertEqual(first.day, self.d(1))
        self.assertEqual(second.day, self.d(2))

    def test_place_append_skips_locked_today(self):
        with patch.object(timezone, "localdate", return_value=self.d(1)):
            ImageOfTheDay.objects.create(
                image=self.img("L"), day=self.d(1), locked=True
            )
            entry = ImageOfTheDay.place(self.img("A"))
        self.assertEqual(entry.day, self.d(2))

    def test_place_records_locked_flag(self):
        entry = ImageOfTheDay.place(self.img("A"), day=self.d(1), locked=True)
        entry.refresh_from_db()
        self.assertTrue(entry.locked)

    # -- place: explicit day ------------------------------------------------

    def test_place_on_free_day_moves_nothing(self):
        ImageOfTheDay.objects.create(image=self.img("A"), day=self.d(1))
        ImageOfTheDay.place(self.img("B"), day=self.d(5))
        self.assertEqual(self.queue(), {self.d(1): "A", self.d(5): "B"})

    def test_place_on_occupied_day_ripples_forward(self):
        for n, name in ((1, "A"), (2, "B"), (3, "C")):
            ImageOfTheDay.objects.create(image=self.img(name), day=self.d(n))
        ImageOfTheDay.place(self.img("D"), day=self.d(1))
        self.assertEqual(
            self.queue(),
            {self.d(1): "D", self.d(2): "A", self.d(3): "B", self.d(4): "C"},
        )

    def test_place_hops_over_locked_anchor(self):
        a = ImageOfTheDay.objects.create(image=self.img("A"), day=self.d(1))
        b = ImageOfTheDay.objects.create(image=self.img("B"), day=self.d(2))
        locked = ImageOfTheDay.objects.create(
            image=self.img("L"), day=self.d(3), locked=True
        )
        c = ImageOfTheDay.objects.create(image=self.img("C"), day=self.d(4))

        ImageOfTheDay.place(self.img("D"), day=self.d(1))

        # Unlocked entries flow around the locked anchor at day 3.
        self.assertEqual(
            self.queue(),
            {
                self.d(1): "D",
                self.d(2): "A",
                self.d(3): "L",
                self.d(4): "B",
                self.d(5): "C",
            },
        )
        locked.refresh_from_db()
        self.assertEqual(locked.day, self.d(3))
        self.assertTrue(locked.locked)

    def test_place_on_locked_day_raises_and_changes_nothing(self):
        ImageOfTheDay.objects.create(image=self.img("A"), day=self.d(1))
        ImageOfTheDay.objects.create(image=self.img("L"), day=self.d(2), locked=True)
        before = self.queue()
        with self.assertRaises(ValidationError):
            ImageOfTheDay.place(self.img("X"), day=self.d(2))
        self.assertEqual(self.queue(), before)

    # -- delete: slide back -------------------------------------------------

    def test_delete_middle_slides_later_entries_back(self):
        entries = {}
        for n, name in ((1, "A"), (2, "B"), (3, "C")):
            entries[name] = ImageOfTheDay.objects.create(
                image=self.img(name), day=self.d(n)
            )
        entries["B"].delete()
        self.assertEqual(self.queue(), {self.d(1): "A", self.d(2): "C"})

    def test_delete_last_moves_nothing(self):
        ImageOfTheDay.objects.create(image=self.img("A"), day=self.d(1))
        last = ImageOfTheDay.objects.create(image=self.img("B"), day=self.d(2))
        last.delete()
        self.assertEqual(self.queue(), {self.d(1): "A"})

    def test_delete_slides_back_around_locked_anchor(self):
        a = ImageOfTheDay.objects.create(image=self.img("A"), day=self.d(1))
        locked = ImageOfTheDay.objects.create(
            image=self.img("L"), day=self.d(2), locked=True
        )
        ImageOfTheDay.objects.create(image=self.img("C"), day=self.d(3))

        a.delete()

        # C slides back past the locked anchor into the freed day 1.
        self.assertEqual(self.queue(), {self.d(1): "C", self.d(2): "L"})
        locked.refresh_from_db()
        self.assertEqual(locked.day, self.d(2))

    def test_delete_locked_entry_raises_and_keeps_it(self):
        locked = ImageOfTheDay.objects.create(
            image=self.img("L"), day=self.d(1), locked=True
        )
        with self.assertRaises(ValidationError):
            locked.delete()
        self.assertTrue(ImageOfTheDay.objects.filter(pk=locked.pk).exists())

    # -- clean: locked move guard ------------------------------------------

    def test_clean_blocks_moving_locked_entry(self):
        locked = ImageOfTheDay.objects.create(
            image=self.img("L"), day=self.d(1), locked=True
        )
        locked.day = self.d(2)
        with self.assertRaises(ValidationError):
            locked.full_clean()

    def test_clean_allows_moving_unlocked_entry(self):
        entry = ImageOfTheDay.objects.create(image=self.img("A"), day=self.d(1))
        entry.day = self.d(5)
        entry.full_clean()  # should not raise

    def test_clean_allows_toggling_lock_without_moving(self):
        entry = ImageOfTheDay.objects.create(image=self.img("A"), day=self.d(1))
        entry.locked = True
        entry.full_clean()  # locking in place is allowed
        entry.save()
        entry.locked = False
        entry.full_clean()  # and so is unlocking it

    # -- the deferred unique constraint ------------------------------------

    def test_day_is_unique(self):
        ImageOfTheDay.objects.create(image=self.img("A"), day=self.d(1))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ImageOfTheDay.objects.create(image=self.img("B"), day=self.d(1))
                # The constraint is deferred, so force it to be checked now
                # rather than waiting for a commit that the test never makes.
                connection.cursor().execute("SET CONSTRAINTS ALL IMMEDIATE")

    def test_unique_constraint_is_deferred(self):
        a = ImageOfTheDay.objects.create(image=self.img("A"), day=self.d(1))
        b = ImageOfTheDay.objects.create(image=self.img("B"), day=self.d(2))
        # Swapping two days requires the rows to transiently share a day.
        # This only succeeds because the constraint is validated at COMMIT,
        # not per-statement -- the same property the ripple relies on.
        with transaction.atomic():
            a.day = self.d(2)
            a.save(update_fields=["day", "updated"])
            b.day = self.d(1)
            b.save(update_fields=["day", "updated"])
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.day, self.d(2))
        self.assertEqual(b.day, self.d(1))

    # -- foreign key reuse --------------------------------------------------

    def test_same_image_can_be_featured_on_multiple_days(self):
        image = self.img("A")
        ImageOfTheDay.objects.create(image=image, day=self.d(1))
        ImageOfTheDay.objects.create(image=image, day=self.d(2))
        self.assertEqual(image.featured_days.count(), 2)

    # -- move: relocate and pin --------------------------------------------

    def test_move_ripples_at_destination_and_locks(self):
        for n, name in ((1, "A"), (2, "B"), (3, "C"), (4, "D"), (5, "E")):
            ImageOfTheDay.objects.create(image=self.img(name), day=self.d(n))
        entry = ImageOfTheDay.objects.get(day=self.d(5))

        moved = ImageOfTheDay.move(entry, self.d(2))

        # E lands pinned at day 2; the entries it displaces ripple forward.
        self.assertEqual(
            self.queue(),
            {
                self.d(1): "A",
                self.d(2): "E",
                self.d(3): "B",
                self.d(4): "C",
                self.d(5): "D",
            },
        )
        self.assertEqual(moved.day, self.d(2))
        self.assertTrue(moved.locked)

    def test_move_vacates_old_day_and_slides_back(self):
        for n, name in ((1, "A"), (2, "B"), (3, "C")):
            ImageOfTheDay.objects.create(image=self.img(name), day=self.d(n))
        entry = ImageOfTheDay.objects.get(day=self.d(1))

        ImageOfTheDay.move(entry, self.d(5))

        # Leaving day 1 pulls B and C back; A is pinned out at day 5.
        self.assertEqual(
            self.queue(),
            {self.d(1): "B", self.d(2): "C", self.d(5): "A"},
        )

    def test_move_relocks_already_locked_entry(self):
        ImageOfTheDay.objects.create(image=self.img("A"), day=self.d(1))
        ImageOfTheDay.objects.create(image=self.img("B"), day=self.d(2))
        ImageOfTheDay.objects.create(image=self.img("L"), day=self.d(3), locked=True)
        ImageOfTheDay.objects.create(image=self.img("C"), day=self.d(4))
        locked = ImageOfTheDay.objects.get(day=self.d(3))

        moved = ImageOfTheDay.move(locked, self.d(1))

        self.assertEqual(
            self.queue(),
            {
                self.d(1): "L",
                self.d(2): "A",
                self.d(3): "B",
                self.d(4): "C",
            },
        )
        self.assertTrue(moved.locked)

    def test_move_to_locked_day_raises_and_rolls_back(self):
        ImageOfTheDay.objects.create(image=self.img("A"), day=self.d(1))
        ImageOfTheDay.objects.create(image=self.img("L"), day=self.d(2), locked=True)
        entry = ImageOfTheDay.objects.get(day=self.d(1))
        before = self.queue()

        with self.assertRaises(ValidationError):
            ImageOfTheDay.move(entry, self.d(2))

        # The whole move rolls back: the entry is neither deleted nor moved.
        self.assertEqual(self.queue(), before)
        self.assertFalse(ImageOfTheDay.objects.get(day=self.d(1)).locked)
        self.assertTrue(ImageOfTheDay.objects.get(day=self.d(2)).locked)

    def test_move_carries_note_and_user(self):
        user = User.objects.create_user(username="osm_1", first_name="Alice")
        entry = ImageOfTheDay.objects.create(
            image=self.img("A"), day=self.d(1), note="keep me", user=user
        )

        moved = ImageOfTheDay.move(entry, self.d(5), note="keep me", user=user)

        moved.refresh_from_db()
        self.assertEqual(moved.day, self.d(5))
        self.assertTrue(moved.locked)
        self.assertEqual(moved.note, "keep me")
        self.assertEqual(moved.user, user)
        # The entry is recreated, so the old row is gone.
        self.assertNotEqual(moved.pk, entry.pk)
        self.assertFalse(ImageOfTheDay.objects.filter(pk=entry.pk).exists())

    # -- unlock: free and compact ------------------------------------------

    def test_unlock_moves_to_first_available_day(self):
        for n, name in ((1, "A"), (2, "B"), (3, "C")):
            ImageOfTheDay.objects.create(image=self.img(name), day=self.d(n))
        anchor = ImageOfTheDay.objects.create(
            image=self.img("D"), day=self.d(10), locked=True
        )

        with patch.object(timezone, "localdate", return_value=self.d(1)):
            ImageOfTheDay.unlock(anchor)

        # Freed from day 10, D drops into the first open day, 4.
        self.assertEqual(
            self.queue(),
            {self.d(1): "A", self.d(2): "B", self.d(3): "C", self.d(4): "D"},
        )
        self.assertFalse(ImageOfTheDay.objects.get(day=self.d(4)).locked)

    def test_unlock_stays_when_already_earliest(self):
        anchor = ImageOfTheDay.objects.create(
            image=self.img("A"), day=self.d(1), locked=True
        )
        ImageOfTheDay.objects.create(image=self.img("B"), day=self.d(2))
        ImageOfTheDay.objects.create(image=self.img("C"), day=self.d(3))

        with patch.object(timezone, "localdate", return_value=self.d(1)):
            ImageOfTheDay.unlock(anchor)

        # Day 1 is already the earliest slot, so it just unlocks in place.
        self.assertEqual(
            self.queue(),
            {self.d(1): "A", self.d(2): "B", self.d(3): "C"},
        )
        self.assertFalse(ImageOfTheDay.objects.get(day=self.d(1)).locked)

    def test_unlock_slides_later_entries_back(self):
        ImageOfTheDay.objects.create(image=self.img("A"), day=self.d(1))
        ImageOfTheDay.objects.create(image=self.img("B"), day=self.d(2))
        anchor = ImageOfTheDay.objects.create(
            image=self.img("L"), day=self.d(5), locked=True
        )
        ImageOfTheDay.objects.create(image=self.img("C"), day=self.d(6))

        with patch.object(timezone, "localdate", return_value=self.d(1)):
            ImageOfTheDay.unlock(anchor)

        # L drops to the first open day (3); C compacts up behind it.
        self.assertEqual(
            self.queue(),
            {self.d(1): "A", self.d(2): "B", self.d(3): "L", self.d(4): "C"},
        )

    def test_unlock_compacts_around_remaining_locks(self):
        ImageOfTheDay.objects.create(image=self.img("A"), day=self.d(1))
        ImageOfTheDay.objects.create(image=self.img("B"), day=self.d(2))
        ImageOfTheDay.objects.create(image=self.img("L"), day=self.d(3), locked=True)
        anchor = ImageOfTheDay.objects.create(
            image=self.img("T"), day=self.d(10), locked=True
        )

        with patch.object(timezone, "localdate", return_value=self.d(1)):
            ImageOfTheDay.unlock(anchor)

        # T drops to day 4 (1, 2 taken, 3 still locked); the other lock holds.
        self.assertEqual(
            self.queue(),
            {self.d(1): "A", self.d(2): "B", self.d(3): "L", self.d(4): "T"},
        )
        self.assertTrue(ImageOfTheDay.objects.get(day=self.d(3)).locked)
        self.assertFalse(ImageOfTheDay.objects.get(day=self.d(4)).locked)


class CollectionStatsTests(TestCase):
    """The denormalized CollectionStats rows stay correct as images and
    georeferences change. Refreshes run via transaction.on_commit, so tests
    wrap writes in captureOnCommitCallbacks (and mute the image-processing
    task that Image saves also enqueue on commit)."""

    @classmethod
    def setUpTestData(cls):
        cls.source = Source.objects.create(
            name="Src", slug="src", url="https://example.com", description=""
        )
        cls.collection = Collection.objects.create(
            source=cls.source, name="Col", slug="col", url="https://example.com"
        )

    @contextmanager
    def stats_events(self):
        with (
            patch("images.tasks.process_image.apply_async"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            yield

    def img(self, title, **kwargs):
        with self.stats_events():
            return Image.objects.create(
                collection=kwargs.pop("collection", self.collection),
                title=title,
                permalink=f"https://img.example.com/{title}.jpg",
                **kwargs,
            )

    def stats(self, collection=None):
        return CollectionStats.objects.get(pk=(collection or self.collection).pk)

    def counts(self, collection=None):
        s = self.stats(collection)
        return (
            s.total_images,
            s.georeferenced_images,
            s.will_not_georef_images,
            s.pending_images,
        )

    def test_new_collection_seeds_zeroed_row(self):
        with self.stats_events():
            collection = Collection.objects.create(
                source=self.source, name="New", slug="new", url="https://example.com"
            )
        self.assertEqual(self.counts(collection), (0, 0, 0, 0))

    def test_georeference_lifecycle(self):
        image = self.img("A")
        self.assertEqual(self.counts(), (1, 0, 0, 1))

        with self.stats_events():
            georef = Georeference.objects.create(
                image=image, point=Point(-77.43, 37.54, srid=4326), confidence="high"
            )
        self.assertEqual(self.counts(), (1, 1, 0, 0))
        self.assertEqual(self.stats().georeferenced_high, 1)

        with self.stats_events():
            georef.delete()
        self.assertEqual(self.counts(), (1, 0, 0, 1))

    def test_confidence_follows_most_recent_georeference(self):
        image = self.img("A")
        with self.stats_events():
            Georeference.objects.create(
                image=image, point=Point(-77.43, 37.54, srid=4326), confidence="low"
            )
        old = Georeference.objects.get(image=image)
        Georeference.objects.filter(pk=old.pk).update(
            georeferenced_at=timezone.now() - datetime.timedelta(days=1)
        )
        with self.stats_events():
            Georeference.objects.create(
                image=image, point=Point(-77.44, 37.54, srid=4326), confidence="medium"
            )
        s = self.stats()
        self.assertEqual(
            (s.georeferenced_low, s.georeferenced_medium, s.georeferenced_high),
            (0, 1, 0),
        )
        self.assertEqual(s.georeferenced_images, 1)

    def test_aerial_image_counts_only_via_aerial_georeference(self):
        aerial = self.img("Aerial", aerial=True)
        with self.stats_events():
            AerialGeoreference.objects.create(
                image=aerial,
                polygon=Polygon(
                    (
                        (-77.44, 37.53),
                        (-77.43, 37.53),
                        (-77.43, 37.54),
                        (-77.44, 37.54),
                        (-77.44, 37.53),
                    ),
                    srid=4326,
                ),
                confidence="medium",
            )
        self.assertEqual(self.counts(), (1, 1, 0, 0))

        # An aerial image with ONLY a point georeference is not "done" — it
        # still needs a polygon georeference, so it stays available (pending).
        aerial_pt = self.img("AerialPoint", aerial=True)
        with self.stats_events():
            Georeference.objects.create(
                image=aerial_pt,
                point=Point(-77.43, 37.54, srid=4326),
                confidence="low",
            )
        # total 2, only the polygon-georeferenced aerial is done, the other pends
        self.assertEqual(self.counts(), (2, 1, 0, 1))
        s = self.stats()
        self.assertEqual(s.georeferenced_images, 1)
        self.assertEqual(s.georeferenced_low, 0)

    def test_will_not_georef_and_duplicates(self):
        image = self.img("A")
        self.img("Dup", duplicate_of=image)
        self.assertEqual(self.counts(), (1, 0, 0, 1))

        image.will_not_georef = True
        with self.stats_events():
            image.save()
        self.assertEqual(self.counts(), (1, 0, 1, 0))

    def test_image_move_refreshes_both_collections(self):
        other = Collection.objects.create(
            source=self.source, name="Other", slug="other", url="https://example.com"
        )
        image = self.img("A")
        image.collection = other
        with self.stats_events():
            image.save()
        self.assertEqual(self.counts(), (0, 0, 0, 0))
        self.assertEqual(self.counts(other), (1, 0, 0, 1))

    def test_image_delete_refreshes_stats(self):
        image = self.img("A")
        with self.stats_events():
            image.delete()
        self.assertEqual(self.counts(), (0, 0, 0, 0))

    def test_reconcile_task_heals_drift(self):
        self.img("A")
        CollectionStats.objects.filter(pk=self.collection.pk).update(
            total_images=99, georeferenced_high=42
        )
        reconcile_collection_stats()
        self.assertEqual(self.counts(), (1, 0, 0, 1))

    def test_refresh_skips_rows_computed_from_newer_snapshot(self):
        """The upsert's freshness guard: a refresh whose snapshot is older
        than the row's updated_at must leave the row untouched, so a stale
        concurrent refresh (or the reconcile) can't clobber fresher counts."""
        self.img("A")
        CollectionStats.objects.filter(pk=self.collection.pk).update(
            total_images=99,
            updated_at=timezone.now() + datetime.timedelta(hours=1),
        )
        CollectionStats.refresh_for([self.collection.pk])
        self.assertEqual(self.stats().total_images, 99)

    def test_overall_stats_and_confidence_breakdown(self):
        image = self.img("A")
        self.img("B")
        self.img("C", will_not_georef=True)
        with self.stats_events():
            Georeference.objects.create(
                image=image, point=Point(-77.43, 37.54, srid=4326), confidence="high"
            )
        # A private collection's images must not leak into sitewide numbers
        hidden = Collection.objects.create(
            source=self.source,
            name="Hidden",
            slug="hidden",
            url="https://example.com",
            public=False,
        )
        self.img("H", collection=hidden)

        overall = get_overall_stats()
        self.assertEqual(overall["total_images"], 2)  # excludes wnf + hidden
        self.assertEqual(overall["total_georeferenced"], 1)
        self.assertEqual(overall["georeferenced_percentage"], 50.0)

        breakdown = get_confidence_breakdown()
        self.assertEqual(
            breakdown,
            {"not_georeferenced": 1, "low": 0, "medium": 0, "high": 1},
        )


class ProcessImageGenerationGuardTests(TestCase):
    """process_image must never persist asset URLs from a superseded
    generation. cleanup_old_image_assets deletes every R2 generation
    directory except the current asset_generation's, so a stale write leaves
    the DB pointing at objects that no longer exist (404 thumbnails). This
    is exactly what happened when API imports queued several concurrent
    process_image tasks per image: each claimed its own generation, and the
    last DB write was not always the task holding the newest one."""

    @classmethod
    def setUpTestData(cls):
        cls.source = Source.objects.create(
            name="Src", slug="src", url="https://example.com", description=""
        )
        cls.collection = Collection.objects.create(
            source=cls.source, name="Col", slug="col", url="https://example.com"
        )

    def make_image(self):
        with patch("images.tasks.process_image.apply_async"):
            return Image.objects.create(
                collection=self.collection,
                title="Test",
                permalink="https://img.example.com/test.jpg",
            )

    @contextmanager
    def run_environment(self, download_side_effect):
        """Patch process_image's collaborators: image download, R2 uploads
        (return a URL derived from the key), and the tile task."""
        uploader = patch("images.tasks.R2Uploader").start()
        uploader.return_value.upload_file_content.side_effect = (
            lambda content, key, **kwargs: f"https://cdn.test/{key}"
        )
        patch("images.tasks.download_image", side_effect=download_side_effect).start()
        tiles = patch("images.tasks.generate_iiif_tiles.delay").start()
        try:
            yield tiles
        finally:
            patch.stopall()

    def test_persists_thumbnail_for_current_generation(self):
        image = self.make_image()

        def download(url, **kwargs):
            return PILImage.new("RGB", (600, 400))

        with self.run_environment(download) as tiles:
            process_image(image.id)

        image.refresh_from_db()
        self.assertEqual(image.asset_generation, 1)
        self.assertEqual(
            image.thumbnail,
            f"https://cdn.test/images/{image.id}/1/thumbnail.webp",
        )
        tiles.assert_called_once_with(image.id)

    def test_discards_write_when_generation_superseded(self):
        """Simulate a concurrent process_image run claiming a newer
        generation while this one is mid-flight (during the download): the
        stale run must not persist its URLs or queue tiling."""
        image = self.make_image()

        def download(url, **kwargs):
            Image.objects.filter(pk=image.id).update(
                asset_generation=F("asset_generation") + 1
            )
            return PILImage.new("RGB", (600, 400))

        with self.run_environment(download) as tiles:
            process_image(image.id)

        image.refresh_from_db()
        self.assertEqual(image.asset_generation, 2)
        # The superseded run uploaded to .../1/thumbnail.webp; persisting
        # that URL is the bug — generation 1's directory gets deleted by
        # cleanup_old_image_assets once generation 2 completes.
        self.assertFalse(image.thumbnail)
        tiles.assert_not_called()


class QueueImageProcessingSignalTests(TestCase):
    """Exactly one process_image task per imported image. The API import
    flow saves the Image twice in one transaction (placeholder insert, then
    the permalink update after the S3 copy); only the save that sets the
    permalink should queue processing."""

    @classmethod
    def setUpTestData(cls):
        cls.source = Source.objects.create(
            name="Src", slug="src", url="https://example.com", description=""
        )
        cls.collection = Collection.objects.create(
            source=cls.source, name="Col", slug="col", url="https://example.com"
        )

    def test_import_commit_sequence_queues_one_task(self):
        with (
            patch("images.tasks.process_image.apply_async") as apply_async,
            self.captureOnCommitCallbacks(execute=True),
        ):
            image = Image.objects.create(
                collection=self.collection,
                title="Imported",
                permalink="",
            )
            image.permalink = "https://cdn.test/images/1/original.jpg"
            image.save(update_fields=["permalink"])

        apply_async.assert_called_once_with(args=[image.id])

    def test_save_without_permalink_queues_nothing(self):
        with (
            patch("images.tasks.process_image.apply_async") as apply_async,
            self.captureOnCommitCallbacks(execute=True),
        ):
            Image.objects.create(
                collection=self.collection,
                title="Placeholder",
                permalink="",
            )

        apply_async.assert_not_called()


# Coordinates for a small aerial-georeference footprint (a closed ring).
_SEARCH_POLYGON = (
    (-77.44, 37.53),
    (-77.43, 37.53),
    (-77.43, 37.54),
    (-77.44, 37.54),
    (-77.44, 37.53),
)


class SearchGeoreferenceFilterTests(TestCase):
    """The "georeferenced only" / "not georeferenced only" search filters must
    respect BOTH kinds of georeference, mirroring ``Image.is_georeferenced``:
    point georefs for regular images and aerial (polygon) georefs for aerial
    images.

    Regression test: the raw-SQL search filters used to check only the point
    ``images_georeference`` table, so an aerial image with only a polygon georef
    leaked through "not georeferenced only" (and was wrongly hidden by
    "georeferenced only"). Covers the ``semantic_search`` and ``text_search``
    endpoints; ``reverse_image_search`` shares ``semantic_search``'s SQL.
    """

    # A distinctive token in every image's description so a single trigram query
    # matches all fixtures regardless of their georeference state.
    TOKEN = "riverbend"

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="osm_1", password="test")
        cls.source = Source.objects.create(
            name="Src",
            slug="src",
            url="https://example.com",
            description="",
            public=True,
        )
        cls.collection = Collection.objects.create(
            source=cls.source,
            name="Col",
            slug="col",
            url="https://example.com",
            public=True,
        )

        # Non-aerial image with a point georeference -> georeferenced.
        cls.img_point = cls._make_image("Point photo")
        Georeference.objects.create(
            image=cls.img_point,
            point=Point(-77.43, 37.54, srid=4326),
            confidence="high",
            georeferenced_by=cls.user,
        )
        # Aerial image with a polygon georeference -> georeferenced. THE BUG CASE.
        cls.img_aerial = cls._make_image("Aerial photo", aerial=True)
        AerialGeoreference.objects.create(
            image=cls.img_aerial,
            polygon=Polygon(_SEARCH_POLYGON, srid=4326),
            confidence="high",
            georeferenced_by=cls.user,
        )
        # Non-aerial image with no georeference -> not georeferenced.
        cls.img_plain = cls._make_image("Plain photo")
        # Aerial image with no georeference -> not georeferenced.
        cls.img_aerial_plain = cls._make_image("Aerial pending photo", aerial=True)

        cls.all_ids = {
            cls.img_point.id,
            cls.img_aerial.id,
            cls.img_plain.id,
            cls.img_aerial_plain.id,
        }
        cls.georeferenced_ids = {cls.img_point.id, cls.img_aerial.id}
        cls.not_georeferenced_ids = {cls.img_plain.id, cls.img_aerial_plain.id}

    @classmethod
    def _make_image(cls, title, aerial=False):
        img = Image.objects.create(
            collection=cls.collection,
            title=title,
            permalink=f"https://img.example.com/{title}.jpg",
            description=f"A photograph of the {cls.TOKEN} district.",
            aerial=aerial,
            embedding=[0.1] * 768,
        )
        # Pick up the signal-computed is_searchable flag.
        img.refresh_from_db()
        return img

    # -- text search (trigram) ---------------------------------------------

    def _text_search_ids(self, **params):
        resp = self.client.get("/api/v1/search/text/", {"q": self.TOKEN, **params})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        return {r["id"] for r in data["results"]}

    def test_text_search_no_filter_returns_all(self):
        self.assertEqual(self._text_search_ids(), self.all_ids)

    def test_text_search_not_georeferenced_only_excludes_aerial_polygon(self):
        ids = self._text_search_ids(non_georeferenced_only="true")
        # The aerial image is georeferenced via a polygon and must NOT leak
        # through the "not georeferenced only" filter.
        self.assertNotIn(self.img_aerial.id, ids)
        self.assertEqual(ids, self.not_georeferenced_ids)

    def test_text_search_georeferenced_only_includes_aerial_polygon(self):
        ids = self._text_search_ids(georeferenced_only="true")
        # The aerial-with-polygon image must be counted as georeferenced.
        self.assertIn(self.img_aerial.id, ids)
        self.assertEqual(ids, self.georeferenced_ids)

    # -- semantic search (CLIP embeddings; query encoding mocked) -----------

    def _semantic_search_ids(self, **params):
        with patch("images.views.search._get_text_embedding", return_value=[0.1] * 768):
            resp = self.client.get("/api/v1/search/", {"q": self.TOKEN, **params})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        return {r["id"] for r in data["results"]}

    def test_semantic_search_no_filter_returns_all(self):
        self.assertEqual(self._semantic_search_ids(), self.all_ids)

    def test_semantic_search_not_georeferenced_only_excludes_aerial_polygon(self):
        ids = self._semantic_search_ids(non_georeferenced_only="true")
        self.assertNotIn(self.img_aerial.id, ids)
        self.assertEqual(ids, self.not_georeferenced_ids)

    def test_semantic_search_georeferenced_only_includes_aerial_polygon(self):
        ids = self._semantic_search_ids(georeferenced_only="true")
        self.assertIn(self.img_aerial.id, ids)
        self.assertEqual(ids, self.georeferenced_ids)


class BulkImageFlagTests(TestCase):
    """The staff-only bulk endpoints that mark images "from above" (aerial) or
    "will not georeference". They report the number of images actually changed
    (excluding those already tagged) and refresh CollectionStats, which the
    underlying queryset UPDATE would otherwise bypass."""

    FROM_ABOVE_URL = "/api/v1/bulk/from-above/"
    WILL_NOT_GEOREF_URL = "/api/v1/bulk/will-not-georef/"

    @classmethod
    def setUpTestData(cls):
        cls.source = Source.objects.create(
            name="Src", slug="src", url="https://example.com", description=""
        )
        cls.collection = Collection.objects.create(
            source=cls.source, name="Col", slug="col", url="https://example.com"
        )
        cls.staff = User.objects.create_user(
            username="osm_staff", first_name="Sam", is_staff=True
        )
        cls.regular = User.objects.create_user(username="osm_regular", first_name="Reg")

    def make_images(self, n, **kwargs):
        return [
            Image.objects.create(
                collection=self.collection,
                title=f"img{i}",
                permalink=f"https://img.example.com/{i}.jpg",
                **kwargs,
            )
            for i in range(n)
        ]

    def post(self, url, image_ids):
        return self.client.post(
            url, {"image_ids": image_ids}, content_type="application/json"
        )

    # -- happy path --------------------------------------------------------

    def test_staff_marks_from_above(self):
        images = self.make_images(3)
        self.client.force_login(self.staff)
        resp = self.post(self.FROM_ABOVE_URL, [img.id for img in images])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"success": True, "updated_count": 3})
        for img in images:
            img.refresh_from_db()
            self.assertTrue(img.aerial)

    def test_staff_marks_will_not_georef(self):
        images = self.make_images(2)
        self.client.force_login(self.staff)
        resp = self.post(self.WILL_NOT_GEOREF_URL, [img.id for img in images])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["updated_count"], 2)
        for img in images:
            img.refresh_from_db()
            self.assertTrue(img.will_not_georef)

    # -- the "actual number changed" logic ---------------------------------

    def test_updated_count_excludes_already_tagged(self):
        already = self.make_images(1, aerial=True)[0]
        fresh = self.make_images(2)
        self.client.force_login(self.staff)
        resp = self.post(self.FROM_ABOVE_URL, [already.id, *[img.id for img in fresh]])
        self.assertEqual(resp.status_code, 200)
        # 3 selected, 1 already aerial -> only 2 actually changed.
        self.assertEqual(resp.json()["updated_count"], 2)
        for img in fresh:
            img.refresh_from_db()
            self.assertTrue(img.aerial)

    def test_updated_count_zero_when_all_already_tagged(self):
        images = self.make_images(2, will_not_georef=True)
        self.client.force_login(self.staff)
        resp = self.post(self.WILL_NOT_GEOREF_URL, [img.id for img in images])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["updated_count"], 0)

    # -- CollectionStats stays in sync despite the queryset UPDATE ----------

    def test_marking_refreshes_collection_stats(self):
        images = self.make_images(3)
        self.client.force_login(self.staff)
        self.post(self.WILL_NOT_GEOREF_URL, [img.id for img in images])
        stats = CollectionStats.objects.get(pk=self.collection.pk)
        self.assertEqual(stats.will_not_georef_images, 3)

    # -- permissions -------------------------------------------------------

    def test_anonymous_is_unauthorized(self):
        images = self.make_images(2)
        resp = self.post(self.FROM_ABOVE_URL, [img.id for img in images])
        self.assertEqual(resp.status_code, 401)
        for img in images:
            img.refresh_from_db()
            self.assertFalse(img.aerial)

    def test_non_staff_is_forbidden(self):
        images = self.make_images(2)
        self.client.force_login(self.regular)
        resp = self.post(self.WILL_NOT_GEOREF_URL, [img.id for img in images])
        self.assertEqual(resp.status_code, 403)
        for img in images:
            img.refresh_from_db()
            self.assertFalse(img.will_not_georef)

    # -- input validation --------------------------------------------------

    def test_empty_image_ids_is_bad_request(self):
        self.client.force_login(self.staff)
        resp = self.post(self.FROM_ABOVE_URL, [])
        self.assertEqual(resp.status_code, 400)

    def test_get_is_not_allowed(self):
        self.client.force_login(self.staff)
        resp = self.client.get(self.FROM_ABOVE_URL)
        self.assertEqual(resp.status_code, 405)


class UserGeoreferencesPageTests(TestCase):
    """The public "images georeferenced by <user>" page at
    /user/<osm-username>/georeferences/.

    The listing joins two multi-valued relations (point and aerial
    georeferences) with an OR, so the interesting cases are the ones where that
    fan-out could duplicate or drop rows: a user who georeferenced the same
    image twice, and a user with only one kind of georeference.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="osm_1", first_name="Alice")
        cls.other = User.objects.create_user(username="osm_2", first_name="Bob")
        cls.source = Source.objects.create(
            name="Src",
            slug="src",
            url="https://example.com",
            description="",
            public=True,
        )
        cls.collection = Collection.objects.create(
            source=cls.source,
            name="Col",
            slug="col",
            url="https://example.com",
            public=True,
        )
        # A private collection's images are excluded from the public listing.
        cls.private_collection = Collection.objects.create(
            source=cls.source,
            name="Private",
            slug="private",
            url="https://example.com",
            public=False,
        )

        cls.img_point = cls._make_image("Point photo")
        cls._point_georef(cls.img_point, cls.user)

        cls.img_aerial = cls._make_image("Aerial photo", aerial=True)
        AerialGeoreference.objects.create(
            image=cls.img_aerial,
            polygon=Polygon(_SEARCH_POLYGON, srid=4326),
            confidence="high",
            georeferenced_by=cls.user,
        )

        # Georeferenced twice by the same user: must still appear once.
        cls.img_twice = cls._make_image("Corrected photo")
        cls._point_georef(cls.img_twice, cls.user)
        cls._point_georef(cls.img_twice, cls.user)

        # Somebody else's work.
        cls.img_other = cls._make_image("Bob's photo")
        cls._point_georef(cls.img_other, cls.other)

        # Our user's work, but on a non-public collection.
        cls.img_hidden = cls._make_image(
            "Hidden photo", collection=cls.private_collection
        )
        cls._point_georef(cls.img_hidden, cls.user)

        cls.url = "/user/Alice/georeferences/"

    @classmethod
    def _make_image(cls, title, aerial=False, collection=None):
        img = Image.objects.create(
            collection=collection or cls.collection,
            title=title,
            permalink=f"https://img.example.com/{title}.jpg",
            aerial=aerial,
        )
        # Pick up the signal-computed is_searchable flag.
        img.refresh_from_db()
        return img

    @classmethod
    def _point_georef(cls, image, user):
        return Georeference.objects.create(
            image=image,
            point=Point(-77.43, 37.54, srid=4326),
            confidence="high",
            georeferenced_by=user,
        )

    def _listed_ids(self, **params):
        resp = self.client.get(self.url, params)
        self.assertEqual(resp.status_code, 200)
        return [img.id for img in resp.context["page_obj"]]

    def test_lists_point_and_aerial_georeferences(self):
        ids = self._listed_ids()
        self.assertIn(self.img_point.id, ids)
        self.assertIn(self.img_aerial.id, ids)

    def test_excludes_another_users_georeferences(self):
        self.assertNotIn(self.img_other.id, self._listed_ids())

    def test_excludes_images_hidden_from_the_public(self):
        self.assertNotIn(self.img_hidden.id, self._listed_ids())

    def test_image_georeferenced_twice_appears_once(self):
        ids = self._listed_ids()
        self.assertEqual(ids.count(self.img_twice.id), 1)
        # And the total reflects deduplicated images, not georeference rows.
        self.assertEqual(len(ids), 3)

    def test_ordered_by_most_recent_georeference_first(self):
        # img_twice was georeferenced last, so it leads.
        self.assertEqual(self._listed_ids()[0], self.img_twice.id)

    def test_counts_are_image_counts(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.context["total_images"], 3)
        self.assertEqual(resp.context["map_image_count"], 2)
        self.assertEqual(resp.context["aerial_count"], 1)

    def test_map_count_excludes_images_the_tile_layer_drops(self):
        """The tile layer is built from public_georeferences_mvt, which excludes
        will_not_georef images. Such an image still belongs in the grid -- the
        user did georeference it -- but it can never be a pin, so the "on the
        map" stat (and the map's own visibility gate) must not count it."""
        skipped = self._make_image("Skipped photo")
        self._point_georef(skipped, self.user)
        Image.objects.filter(pk=skipped.pk).update(will_not_georef=True)

        resp = self.client.get(self.url)
        self.assertIn(skipped.id, [img.id for img in resp.context["page_obj"]])
        self.assertEqual(resp.context["total_images"], 4)
        self.assertEqual(resp.context["map_image_count"], 2)

    def test_filter_params_and_paging_are_accepted(self):
        self.assertEqual(self.client.get(self.url, {"page": 2}).status_code, 200)
        self.assertEqual(
            self.client.get(self.url, {"start_year": 1900}).status_code, 200
        )
        self.assertEqual(
            self.client.get(
                self.url, {"georeference_status": "georeferenced"}
            ).status_code,
            200,
        )

    def test_user_with_no_georeferences_renders_empty(self):
        User.objects.create_user(username="osm_3", first_name="Carol")
        resp = self.client.get("/user/Carol/georeferences/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["total_images"], 0)
        self.assertEqual(len(resp.context["page_obj"]), 0)

    def test_unknown_user_is_404(self):
        self.assertEqual(
            self.client.get("/user/Nobody/georeferences/").status_code, 404
        )

    def test_profile_page_links_to_the_listing(self):
        resp = self.client.get("/user/Alice/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.url)
