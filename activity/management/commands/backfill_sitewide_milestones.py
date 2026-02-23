from django.core.management.base import BaseCommand
from django.db import connection, transaction

from activity.models import SITEWIDE_MILESTONE_THRESHOLDS, SitewideMilestone


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

        # Get the first georeference timestamp for each image across both tables
        query = """
            SELECT image_id, MIN(georeferenced_at) AS first_georeferenced_at
            FROM (
                SELECT g.image_id, g.georeferenced_at
                FROM images_georeference g
                JOIN images_image i ON g.image_id = i.id
                WHERE i.duplicate_of_id IS NULL AND i.will_not_georef = FALSE
                  AND i.aerial = FALSE
                UNION ALL
                SELECT ag.image_id, ag.georeferenced_at
                FROM images_aerialgeoreference ag
                JOIN images_image i ON ag.image_id = i.id
                WHERE i.duplicate_of_id IS NULL AND i.will_not_georef = FALSE
                  AND i.aerial = TRUE
            ) AS all_georefs
            GROUP BY image_id
            ORDER BY first_georeferenced_at
        """
        with connection.cursor() as cursor:
            cursor.execute(query)
            all_timestamps = [row[1] for row in cursor.fetchall()]

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
