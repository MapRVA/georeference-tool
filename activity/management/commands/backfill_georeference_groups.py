from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import CharField, Value

from activity.models import (
    GROUPING_WINDOW,
    GeoreferenceGroup,
    GeoreferenceGroupMember,
)
from images.models import AerialGeoreference, Georeference


class Command(BaseCommand):
    help = "Backfill GeoreferenceGroup and GeoreferenceGroupMember from existing georeferences"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without actually creating anything",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing groups and members before backfilling",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        clear = options["clear"]

        if clear and not dry_run:
            self.stdout.write("Clearing existing georeference groups...")
            GeoreferenceGroupMember.objects.all().delete()
            GeoreferenceGroup.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("Cleared."))

        # Get all georeferences (both types), excluding those already linked
        # to a group member. Include both logged-in and anonymous submissions.
        point_georefs = (
            Georeference.objects.filter(
                georeferencegroupmember__isnull=True,
            )
            .annotate(georef_type=Value("point", output_field=CharField()))
            .values("id", "georeferenced_by_id", "georeferenced_at", "georef_type")
        )

        aerial_georefs = (
            AerialGeoreference.objects.filter(
                georeferencegroupmember__isnull=True,
            )
            .annotate(georef_type=Value("aerial", output_field=CharField()))
            .values("id", "georeferenced_by_id", "georeferenced_at", "georef_type")
        )

        # Combine and sort by user (with None sorted separately), then timestamp
        all_georefs = list(point_georefs) + list(aerial_georefs)
        all_georefs.sort(
            key=lambda x: (
                x["georeferenced_by_id"] is None,  # None values sorted last
                x["georeferenced_by_id"] or 0,
                x["georeferenced_at"],
            )
        )

        self.stdout.write(f"Found {len(all_georefs)} georeferences to process")

        # Group by user (None key for anonymous submissions)
        georefs_by_user = {}
        for georef in all_georefs:
            user_id = georef["georeferenced_by_id"]  # None for anonymous
            if user_id not in georefs_by_user:
                georefs_by_user[user_id] = []
            georefs_by_user[user_id].append(georef)

        groups_to_create = []
        members_to_create = []

        for user_id, user_georefs in georefs_by_user.items():
            current_group = None

            for georef in user_georefs:
                timestamp = georef["georeferenced_at"]

                # Check if we need a new group
                if current_group is None:
                    # Start first group for this user
                    current_group = {
                        "user_id": user_id,
                        "started_at": timestamp,
                        "ended_at": timestamp,
                        "count": 0,
                        "members": [],
                    }
                elif (timestamp - current_group["ended_at"]) >= GROUPING_WINDOW:
                    # Gap too large, save current group and start new one
                    groups_to_create.append(current_group)
                    current_group = {
                        "user_id": user_id,
                        "started_at": timestamp,
                        "ended_at": timestamp,
                        "count": 0,
                        "members": [],
                    }

                # Add to current group
                current_group["ended_at"] = timestamp
                current_group["count"] += 1
                current_group["members"].append(georef)

            # Don't forget the last group for this user
            if current_group is not None:
                groups_to_create.append(current_group)

        # Count users (excluding anonymous which has None key)
        user_count = sum(1 for uid in georefs_by_user if uid is not None)
        anon_count = len(georefs_by_user.get(None, []))
        anon_groups = sum(1 for g in groups_to_create if g["user_id"] is None)

        self.stdout.write(
            f"Will create {len(groups_to_create)} groups for {user_count} users"
        )
        if anon_count:
            self.stdout.write(
                f"  Plus {anon_groups} anonymous group(s) with {anon_count} georeferences"
            )

        if dry_run:
            # Show some stats
            single_groups = sum(1 for g in groups_to_create if g["count"] == 1)
            multi_groups = len(groups_to_create) - single_groups
            max_count = max((g["count"] for g in groups_to_create), default=0)

            self.stdout.write(f"  Single-georeference groups: {single_groups}")
            self.stdout.write(f"  Multi-georeference groups: {multi_groups}")
            self.stdout.write(f"  Largest group: {max_count} georeferences")
            self.stdout.write(self.style.WARNING("Dry run - nothing created"))
            return

        # Create groups and members
        with transaction.atomic():
            created_groups = 0
            created_members = 0

            for group_data in groups_to_create:
                group = GeoreferenceGroup.objects.create(
                    user_id=group_data["user_id"],
                    started_at=group_data["started_at"],
                    ended_at=group_data["ended_at"],
                    count=group_data["count"],
                )
                created_groups += 1

                for member_data in group_data["members"]:
                    member_kwargs = {
                        "group": group,
                        "added_at": member_data["georeferenced_at"],
                    }
                    if member_data["georef_type"] == "point":
                        member_kwargs["georeference_id"] = member_data["id"]
                    else:
                        member_kwargs["aerial_georeference_id"] = member_data["id"]

                    GeoreferenceGroupMember.objects.create(**member_kwargs)
                    created_members += 1

                if created_groups % 100 == 0:
                    self.stdout.write(f"  Created {created_groups} groups...")

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {created_groups} groups with {created_members} members"
            )
        )
