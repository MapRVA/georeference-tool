import json
import csv
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from images.models import Source, Collection, Image


class Command(BaseCommand):
    help = "Import images from CSV or JSON file"

    def add_arguments(self, parser):
        parser.add_argument("file_path", type=str, help="Path to the CSV or JSON file")
        parser.add_argument(
            "--format",
            type=str,
            choices=["csv", "json"],
            default="csv",
            help="File format (default: csv)",
        )
        parser.add_argument(
            "--source-name",
            type=str,
            help="Default source name if not specified in file",
        )
        parser.add_argument(
            "--source-url", type=str, help="Default source URL if not specified in file"
        )
        parser.add_argument(
            "--collection-name",
            type=str,
            help="Default collection name if not specified in file",
        )
        parser.add_argument(
            "--collection-url",
            type=str,
            help="Default collection URL if not specified in file",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run without making changes to the database",
        )

    def handle(self, *args, **options):
        file_path = options["file_path"]
        file_format = options["format"]
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )

        try:
            if file_format == "csv":
                self.import_from_csv(file_path, options, dry_run)
            elif file_format == "json":
                self.import_from_json(file_path, options, dry_run)
        except FileNotFoundError:
            raise CommandError(f"File not found: {file_path}")
        except Exception as e:
            raise CommandError(f"Error importing data: {e}")

    def import_from_csv(self, file_path, options, dry_run):
        """
        Import from CSV file with the following columns:
        source_name, source_url, source_description, collection_name, collection_url,
        collection_description, title, permalink, description, year, month, day
        """
        with open(file_path, "r", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            self.process_rows(reader, options, dry_run)

    def import_from_json(self, file_path, options, dry_run):
        """
        Import from JSON file with structure:
        [
          {
            "source": {"name": "...", "url": "...", "description": "..."},
            "collection": {"name": "...", "url": "...", "description": "..."},
            "images": [
              {
                "title": "...",
                "permalink": "...",
                "description": "...",
                "year": 2023,
                "month": 5,
                "day": 15
              }
            ]
          }
        ]
        """
        with open(file_path, "r", encoding="utf-8") as jsonfile:
            data = json.load(jsonfile)

        # Convert JSON structure to row format
        rows = []
        for item in data:
            source_info = item.get("source", {})
            collection_info = item.get("collection", {})

            for image in item.get("images", []):
                row = {
                    "source_name": source_info.get("name", ""),
                    "source_url": source_info.get("url", ""),
                    "source_description": source_info.get("description", ""),
                    "collection_name": collection_info.get("name", ""),
                    "collection_url": collection_info.get("url", ""),
                    "collection_description": collection_info.get("description", ""),
                    "title": image.get("title", ""),
                    "permalink": image.get("permalink", ""),
                    "description": image.get("description", ""),
                    "year": image.get("year", ""),
                    "month": image.get("month", ""),
                    "day": image.get("day", ""),
                }
                rows.append(row)

        self.process_rows(rows, options, dry_run)

    def process_rows(self, rows, options, dry_run):
        created_sources = 0
        created_collections = 0
        created_images = 0
        errors = 0

        with transaction.atomic():
            for row_num, row in enumerate(rows, 1):
                try:
                    # Get or create source
                    source_name = row.get("source_name") or options.get("source_name")
                    source_url = row.get("source_url") or options.get("source_url")

                    if not source_name or not source_url:
                        self.stdout.write(
                            self.style.ERROR(
                                f"Row {row_num}: Missing source name or URL"
                            )
                        )
                        errors += 1
                        continue

                    if not dry_run:
                        source, source_created = Source.objects.get_or_create(
                            name=source_name,
                            defaults={
                                "url": source_url,
                                "description": row.get("source_description", ""),
                            },
                        )
                        if source_created:
                            created_sources += 1
                    else:
                        source_created = not Source.objects.filter(
                            name=source_name
                        ).exists()
                        if source_created:
                            created_sources += 1

                    # Get or create collection
                    collection_name = row.get("collection_name") or options.get(
                        "collection_name"
                    )
                    collection_url = row.get("collection_url") or options.get(
                        "collection_url"
                    )

                    if not collection_name or not collection_url:
                        self.stdout.write(
                            self.style.ERROR(
                                f"Row {row_num}: Missing collection name or URL"
                            )
                        )
                        errors += 1
                        continue

                    if not dry_run:
                        collection, collection_created = (
                            Collection.objects.get_or_create(
                                source=source,
                                name=collection_name,
                                defaults={
                                    "url": collection_url,
                                    "description": row.get(
                                        "collection_description", ""
                                    ),
                                },
                            )
                        )
                        if collection_created:
                            created_collections += 1
                    else:
                        collection_created = not Collection.objects.filter(
                            name=collection_name
                        ).exists()
                        if collection_created:
                            created_collections += 1

                    # Create image
                    permalink = row.get("permalink")
                    if not permalink:
                        self.stdout.write(
                            self.style.ERROR(f"Row {row_num}: Missing permalink")
                        )
                        errors += 1
                        continue

                    # Parse date fields
                    year = self.parse_int(row.get("year"))
                    month = self.parse_int(row.get("month"))
                    day = self.parse_int(row.get("day"))

                    if not dry_run:
                        # Check if image already exists
                        if not Image.objects.filter(permalink=permalink).exists():
                            Image.objects.create(
                                collection=collection,
                                title=row.get("title") or None,
                                permalink=permalink,
                                description=row.get("description") or None,
                                year=year,
                                month=month,
                                day=day,
                            )
                            created_images += 1
                    else:
                        if not Image.objects.filter(permalink=permalink).exists():
                            created_images += 1

                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"Row {row_num}: Error processing - {e}")
                    )
                    errors += 1

        # Report results
        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"DRY RUN COMPLETE: Would create {created_sources} sources, "
                    f"{created_collections} collections, {created_images} images"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"IMPORT COMPLETE: Created {created_sources} sources, "
                    f"{created_collections} collections, {created_images} images"
                )
            )

        if errors > 0:
            self.stdout.write(self.style.ERROR(f"{errors} errors encountered"))

    def parse_int(self, value):
        """Parse integer value, return None if empty or invalid"""
        if not value or str(value).strip() == "":
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
