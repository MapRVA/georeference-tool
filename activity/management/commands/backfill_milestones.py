from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from activity.models import MILESTONE_THRESHOLDS, UserMilestone
from images.models import AerialGeoreference, Georeference


class Command(BaseCommand):
    help = "Backfill UserMilestone records from existing georeferences"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without actually creating anything",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing milestones before backfilling",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        clear = options["clear"]

        if clear and not dry_run:
            self.stdout.write("Clearing existing milestones...")
            UserMilestone.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("Cleared."))

        # Get users who have made georeferences
        users_with_georefs = (
            User.objects.filter(georeferenced_images__isnull=False).distinct()
            | User.objects.filter(aerial_georeferenced_images__isnull=False).distinct()
        )

        self.stdout.write(
            f"Found {users_with_georefs.count()} users with georeferences"
        )

        milestones_to_create = []

        for user in users_with_georefs:
            # Get all georeferences for this user, ordered by time
            point_georefs = list(
                Georeference.objects.filter(georeferenced_by=user)
                .values_list("georeferenced_at", flat=True)
                .order_by("georeferenced_at")
            )
            aerial_georefs = list(
                AerialGeoreference.objects.filter(georeferenced_by=user)
                .values_list("georeferenced_at", flat=True)
                .order_by("georeferenced_at")
            )

            # Merge and sort all timestamps
            all_timestamps = sorted(point_georefs + aerial_georefs)

            if not all_timestamps:
                continue

            # Check existing milestones for this user
            existing_milestones = set(
                UserMilestone.objects.filter(user=user).values_list("count", flat=True)
            )

            # Walk through timestamps and record when milestones were hit
            for milestone in MILESTONE_THRESHOLDS:
                if milestone in existing_milestones:
                    continue
                if len(all_timestamps) >= milestone:
                    # The milestone was reached at the Nth georeference
                    reached_at = all_timestamps[milestone - 1]
                    milestones_to_create.append(
                        {
                            "user": user,
                            "count": milestone,
                            "reached_at": reached_at,
                        }
                    )

        self.stdout.write(f"Will create {len(milestones_to_create)} milestones")

        if dry_run:
            # Show breakdown by milestone
            by_milestone = {}
            for m in milestones_to_create:
                count = m["count"]
                by_milestone[count] = by_milestone.get(count, 0) + 1

            for milestone in MILESTONE_THRESHOLDS:
                if milestone in by_milestone:
                    self.stdout.write(
                        f"  {milestone} georeferences: {by_milestone[milestone]} users"
                    )

            self.stdout.write(self.style.WARNING("Dry run - nothing created"))
            return

        # Create milestones
        with transaction.atomic():
            created = 0
            for milestone_data in milestones_to_create:
                UserMilestone.objects.create(
                    user=milestone_data["user"],
                    count=milestone_data["count"],
                    reached_at=milestone_data["reached_at"],
                )
                created += 1

        self.stdout.write(self.style.SUCCESS(f"Created {created} milestones"))
