import json
import time

import requests
from django.contrib.gis.geos import GEOSGeometry
from django.core.management.base import BaseCommand
from tqdm import tqdm

from subjects.models import OsmElement, Subject
from subjects.tasks import (
    create_request_session,
    fetch_osm_features,
    get_postpass_timeout,
    get_postpass_url,
)


class Command(BaseCommand):
    help = "Populate OSM elements for subjects that have Wikidata items attached"

    def add_arguments(self, parser):
        parser.add_argument(
            "--wait",
            type=int,
            default=10,
            help="Seconds to wait between API requests (default: 10)",
        )
        parser.add_argument(
            "--postpass-url",
            type=str,
            default=None,
            help="URL of the Postpass API instance (default: from settings)",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=None,
            help="Timeout for API requests in seconds (default: from settings)",
        )
        parser.add_argument(
            "--refresh",
            action="store_true",
            help="Re-query all OSM elements for subjects with Wikidata items. Deletes OsmElements that are no longer found in OSM.",
        )

    def handle(self, *args, **options):
        wait_time = options["wait"]
        postpass_url = options["postpass_url"] or get_postpass_url()
        timeout = options["timeout"] or get_postpass_timeout()
        refresh = options["refresh"]

        if refresh:
            # Get all subjects with Wikidata items (regardless of OSM element status)
            subjects = Subject.objects.filter(wikidata_item__isnull=False)
            tqdm.write(self.style.SUCCESS("Running in refresh mode"))
        else:
            # Get all subjects with Wikidata items but no OSM elements
            subjects = Subject.objects.filter(
                wikidata_item__isnull=False, osm_elements__isnull=True
            )

        if not subjects.exists():
            tqdm.write(self.style.SUCCESS("No subjects found that need OSM elements"))
            return

        subject_list = list(subjects)
        subject_count = len(subject_list)
        tqdm.write(f"Found {subject_count} subjects to process")

        session = create_request_session()
        processed = 0
        skipped = 0
        deleted = 0

        progress = tqdm(subject_list, desc="Processing subjects", unit="subject")
        for i, subject in enumerate(progress):
            wikidata_id = subject.wikidata_item.wikidata_id
            progress.set_description(f"Processing {subject.title[:30]}")

            try:
                features = fetch_osm_features(
                    session, wikidata_id, postpass_url=postpass_url, timeout=timeout
                )

                if not features:
                    tqdm.write(
                        self.style.WARNING(
                            f"  No OSM elements found for {subject.title} ({wikidata_id})"
                        )
                    )
                    if refresh and subject.osm_elements.exists():
                        # In refresh mode, delete OSM elements if no longer found in OSM
                        old_osm_ids = list(
                            subject.osm_elements.values_list("osm_id", flat=True)
                        )
                        delete_count = subject.osm_elements.count()
                        subject.osm_elements.all().delete()
                        tqdm.write(
                            self.style.SUCCESS(
                                f"  Deleted {delete_count} OSM element(s) {old_osm_ids} (no longer found in OSM)"
                            )
                        )
                        deleted += delete_count
                    else:
                        skipped += 1
                else:
                    # Get current OSM IDs for this subject
                    current_osm_ids = set(
                        subject.osm_elements.values_list("osm_id", flat=True)
                    )
                    new_osm_ids = {f["properties"]["osm_id"] for f in features}

                    # In refresh mode, delete OSM elements that are no longer in the API response
                    if refresh:
                        stale_osm_ids = current_osm_ids - new_osm_ids
                        if stale_osm_ids:
                            stale_count = subject.osm_elements.filter(
                                osm_id__in=stale_osm_ids
                            ).delete()[0]
                            tqdm.write(
                                self.style.SUCCESS(
                                    f"  Deleted {stale_count} stale OSM element(s) for {subject.title}"
                                )
                            )
                            deleted += stale_count

                    # Create or update OsmElements for all features
                    created_count = 0
                    updated_count = 0
                    for feature in features:
                        osm_id = feature["properties"]["osm_id"]
                        geometry = feature["geometry"]

                        osm_element, created = OsmElement.objects.get_or_create(
                            osm_id=osm_id,
                            defaults={
                                "subject": subject,
                                "geometry": GEOSGeometry(json.dumps(geometry)),
                            },
                        )
                        if not created:
                            # Update geometry and subject link if element already exists
                            osm_element.subject = subject
                            osm_element.geometry = GEOSGeometry(json.dumps(geometry))
                            osm_element.save()
                            updated_count += 1
                        else:
                            created_count += 1

                    if created_count > 0 or updated_count > 0:
                        tqdm.write(
                            self.style.SUCCESS(
                                f"  {subject.title}: created {created_count}, updated {updated_count} OSM element(s)"
                            )
                        )

                    processed += 1

                # Wait before next request to be respectful to the API
                if i < subject_count - 1:
                    time.sleep(wait_time)

            except requests.Timeout:
                tqdm.write(
                    self.style.WARNING(
                        f"  Request timed out for {subject.title}, skipping"
                    )
                )
                skipped += 1
            except requests.RequestException as e:
                tqdm.write(
                    self.style.WARNING(
                        f"  HTTP error for {subject.title}: {str(e)}, skipping"
                    )
                )
                skipped += 1
            except Exception as e:
                tqdm.write(
                    self.style.ERROR(f"  Error processing {subject.title}: {str(e)}")
                )
                skipped += 1

        progress.close()
        session.close()

        if refresh:
            tqdm.write(
                self.style.SUCCESS(
                    f"\nComplete! Processed: {processed}, Deleted: {deleted}, Skipped: {skipped}"
                )
            )
        else:
            tqdm.write(
                self.style.SUCCESS(
                    f"\nComplete! Processed: {processed}, Skipped: {skipped}"
                )
            )
