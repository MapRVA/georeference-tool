import datetime
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from images.models import Collection, Image, ImageOfTheDay, Source


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
            e.day: e.image.title
            for e in ImageOfTheDay.objects.select_related("image")
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
        ImageOfTheDay.objects.create(
            image=self.img("L"), day=self.d(3), locked=True
        )
        with patch.object(timezone, "localdate", return_value=self.d(1)):
            self.assertEqual(ImageOfTheDay.next_available_day(), self.d(2))

    # -- timezone correctness ----------------------------------------------

    @override_settings(TIME_ZONE="America/New_York")
    def test_next_available_day_uses_site_timezone(self):
        # 03:30 UTC on June 2 is still 23:30 on June 1 in New York.
        instant = datetime.datetime(
            2026, 6, 2, 3, 30, tzinfo=datetime.timezone.utc
        )
        with patch.object(timezone, "now", return_value=instant):
            self.assertEqual(
                ImageOfTheDay.next_available_day(), datetime.date(2026, 6, 1)
            )

    @override_settings(TIME_ZONE="America/New_York")
    def test_for_today_uses_site_timezone(self):
        instant = datetime.datetime(
            2026, 6, 2, 3, 30, tzinfo=datetime.timezone.utc
        )
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
        ImageOfTheDay.objects.create(
            image=self.img("L"), day=self.d(2), locked=True
        )
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
        ImageOfTheDay.objects.create(
            image=self.img("L"), day=self.d(3), locked=True
        )
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
        ImageOfTheDay.objects.create(
            image=self.img("L"), day=self.d(2), locked=True
        )
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
        ImageOfTheDay.objects.create(
            image=self.img("L"), day=self.d(3), locked=True
        )
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
