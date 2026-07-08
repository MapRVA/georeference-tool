import datetime
from contextlib import contextmanager
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.gis.geos import Point, Polygon
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from images.models import (
    AerialGeoreference,
    Collection,
    CollectionStats,
    Georeference,
    Image,
    ImageOfTheDay,
    Source,
)
from images.tasks import reconcile_collection_stats
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
