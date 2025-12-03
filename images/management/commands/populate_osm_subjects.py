import json
import time

import requests
from django.contrib.gis.geos import GEOSGeometry
from django.core.management.base import BaseCommand
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from images.models import OsmElement, Subject


class Command(BaseCommand):
    help = "Populate OSM elements for subjects that have Wikidata items attached"

    def add_arguments(self, parser):
        parser.add_argument(
            "--wait",
            type=int,
            default=10,
            help="Seconds to wait between API requests (default: 30)",
        )
        parser.add_argument(
            "--postpass-url",
            type=str,
            default="https://postpass.geofabrik.de/api/0.2/interpreter",
            help="URL of the Postpass API instance",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=60,
            help="Timeout for API requests in seconds (default: 60)",
        )

    def handle(self, *args, **options):
        wait_time = options["wait"]
        postpass_url = options["postpass_url"]
        timeout = options["timeout"]

        # Get all subjects with Wikidata items but no OSM element
        subjects = Subject.objects.filter(
            wikidata_item__isnull=False, osm_element__isnull=True
        )

        if not subjects.exists():
            self.stdout.write(
                self.style.SUCCESS("No subjects found that need OSM elements")
            )
            return

        self.stdout.write(f"Found {subjects.count()} subjects to process")

        session = self._create_session()

        processed = 0
        skipped = 0

        for subject in subjects:
            wikidata_id = subject.wikidata_item.wikidata_id
            self.stdout.write(f"\nProcessing {subject.title} ({wikidata_id})...")

            try:
                # Print the query that will be sent to Postpass
                bbox_clause = "ST_SetSRID(ST_MakeBox2D(ST_MakePoint(-84.72, 35.90), ST_MakePoint(-74.97, 39.71)), 4326)"
                sql_query = f"""SELECT osm_id, tags, geom FROM postpass_pointlinepolygon WHERE tags->>'wikidata' = '{wikidata_id}' AND geom && {bbox_clause}"""
                self.stdout.write(f"  Query:\n{sql_query}\n")

                features = self._fetch_osm_features(session, postpass_url, wikidata_id, timeout, bbox_clause)

                if not features:
                    self.stdout.write(
                        self.style.WARNING(f"  No OSM elements found for {wikidata_id}")
                    )
                    skipped += 1
                else:
                    # Process the first (best match) feature
                    feature = features[0]
                    osm_id = feature["properties"]["osm_id"]
                    geometry = feature["geometry"]

                    # Create or update OsmElement
                    osm_element, created = OsmElement.objects.get_or_create(
                        osm_id=osm_id,
                        defaults={"geometry": GEOSGeometry(json.dumps(geometry))},
                    )

                    if not created:
                        # Update geometry if it changed
                        osm_element.geometry = GEOSGeometry(json.dumps(geometry))
                        osm_element.save()

                    # Link to subject
                    subject.osm_element = osm_element
                    subject.save()

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  Linked OSM element {osm_element.osm_id} to {subject.title}"
                        )
                    )
                    processed += 1

                # Wait before next request to be respectful to the API
                if subject != subjects.last():
                    self.stdout.write(f"  Waiting {wait_time}s before next request...")
                    time.sleep(wait_time)

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"  Error processing {subject.title}: {str(e)}")
                )
                skipped += 1

        session.close()

        self.stdout.write(
            self.style.SUCCESS(f"\nComplete! Processed: {processed}, Skipped: {skipped}")
        )

    def _create_session(self):
        """Create a requests session with retry strategy"""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _fetch_osm_features(self, session, postpass_url, wikidata_id, timeout, bbox_clause):
        """Fetch OSM features from Postpass API for a Wikidata item"""
        # Query the combined geometry view for all element types within Virginia bounds
        sql_query = f"""
        SELECT osm_id, tags, geom FROM postpass_pointlinepolygon WHERE tags->>'wikidata' = '{wikidata_id}' AND geom && {bbox_clause}
        """

        try:
            response = session.post(
                postpass_url,
                data={"data": sql_query},
                timeout=timeout,
            )
            response.raise_for_status()

            data = response.json()

            if not data.get("features"):
                return []

            # Add osm_id to properties if not already present
            for feature in data["features"]:
                if "osm_id" not in feature.get("properties", {}):
                    # Try to extract from the feature if available
                    feature["properties"]["osm_id"] = feature["properties"].get(
                        "osm_id", 0
                    )

            return data["features"]

        except requests.Timeout as e:
            raise Exception(
                f"Request to Postpass API timed out after {timeout}s. "
                f"Try increasing timeout with --timeout flag: {str(e)}"
            )
        except requests.RequestException as e:
            raise Exception(f"Failed to fetch from Postpass API: {str(e)}")
        except (json.JSONDecodeError, KeyError) as e:
            raise Exception(f"Failed to parse Postpass response: {str(e)}")
