from django.core.management.base import BaseCommand
from django.db import transaction

from activity.models import SITEWIDE_MILESTONE_THRESHOLDS, SitewideMilestone
from images.models import AerialGeoreference, Georeference, Image


class Command(BaseCommand):
    help = "Backfill SitewideMilestone records from existing georeferences"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without actually creating anything",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing sitewide milestones before backfilling",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        clear = options["clear"]

        if clear and not dry_run:
            self.stdout.write("Clearing existing sitewide milestones...")
            SitewideMilestone.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("Cleared."))

        # Get existing milestones to skip
        existing_milestones = set(
            SitewideMilestone.objects.values_list("count", flat=True)
        )

        # Get all first georeferences per image (the one that initially georeferenced it)
        # For point georeferences (non-aerial images)
        point_first_georefs = (
            Georeference.objects.filter(
                image__aerial=False,
                image__duplicate_of__isnull=True,
                image__will_not_georef=False,
            )
            .order_by("image_id", "georeferenced_at")
            .distinct("image_id")
            .values_list("georeferenced_at", flat=True)
        )

        # For aerial georeferences (aerial images)
        aerial_first_georefs = (
            AerialGeoreference.objects.filter(
                image__aerial=True,
                image__duplicate_of__isnull=True,
                image__will_not_georef=False,
            )
            .order_by("image_id", "georeferenced_at")
            .distinct("image_id")
            .values_list("georeferenced_at", flat=True)
        )

        # Merge and sort all timestamps
        all_timestamps = sorted(list(point_first_georefs) + list(aerial_first_georefs))

        self.stdout.write(f"Found {len(all_timestamps)} georeferenced images")

        milestones_to_create = []

        # Walk through thresholds and find when each was reached
        for milestone in SITEWIDE_MILESTONE_THRESHOLDS:
            if milestone in existing_milestones:
                self.stdout.write(f"  {milestone}: already exists, skipping")
                continue
            if len(all_timestamps) >= milestone:
                # The milestone was reached when the Nth image was georeferenced
                reached_at = all_timestamps[milestone - 1]
                milestones_to_create.append(
                    {
                        "count": milestone,
                        "reached_at": reached_at,
                    }
                )

        self.stdout.write(
            f"Will create {len(milestones_to_create)} sitewide milestones"
        )

        if dry_run:
            for m in milestones_to_create:
                self.stdout.write(
                    f"  {m['count']} images: reached at {m['reached_at']}"
                )
            self.stdout.write(self.style.WARNING("Dry run - nothing created"))
            return

        # Create milestones
        with transaction.atomic():
            created = 0
            for milestone_data in milestones_to_create:
                SitewideMilestone.objects.create(
                    count=milestone_data["count"],
                    reached_at=milestone_data["reached_at"],
                )
                created += 1

        self.stdout.write(self.style.SUCCESS(f"Created {created} sitewide milestones"))
