import csv
import os
from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth.models import User
from images.models import Source, Collection, Image, Georeference


class Command(BaseCommand):
    help = "Import real image data from example_data.csv"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing data before importing",
        )
        parser.add_argument(
            "--file",
            type=str,
            default="example_data.csv",
            help="CSV file to import (default: example_data.csv)",
        )
        parser.add_argument(
            "--create-georeferences",
            action="store_true",
            help="Also create georeference records for images with coordinates",
        )

    def handle(self, *args, **options):
        file_path = options["file"]
        if not os.path.exists(file_path):
            self.stdout.write(self.style.ERROR(f"File not found: {file_path}"))
            return

        if options["clear"]:
            self.stdout.write("Clearing existing data...")
            with transaction.atomic():
                Georeference.objects.all().delete()
                Image.objects.all().delete()
                Collection.objects.all().delete()
                Source.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("Existing data cleared"))

        # Get or create admin user for georeferences
        admin_user = None
        if options["create_georeferences"]:
            admin_user, created = User.objects.get_or_create(
                username="admin", defaults={"is_staff": True, "is_superuser": True}
            )

        created_sources = 0
        created_collections = 0
        created_images = 0
        created_georeferences = 0
        errors = 0

        # Define source descriptions and collection mappings
        source_info = {
            "Valentine Museum": {
                "url": "https://valentine.rediscoverysoftware.com/",
                "description": "The Valentine Richmond History Center archives documenting Richmond, Virginia history through photographs and artifacts.",
            },
            "Library of Virginia": {
                "url": "https://image.lva.virginia.gov/",
                "description": "Digital collections from the Library of Virginia featuring historical photographs, maps, and documents.",
            },
            "VCU": {
                "url": "https://scholarscompass.vcu.edu/",
                "description": "Virginia Commonwealth University digital collections and scholarly materials.",
            },
        }

        # Collection mappings based on URL patterns
        collection_mappings = {
            "Valentine Museum": {
                "PHC0076": "Richmond Architecture Collection",
                "PHC0039": "Historic Richmond Photographs",
                "PHC0007": "Early Richmond Collection",
                "PHC0106": "Recent Richmond History",
                "PHC0015": "Mid-Century Richmond",
                "PHC0032": "Depression Era Richmond",
                "PHC0167": "Contemporary Richmond",
                "default": "Richmond Historical Photographs",
            },
            "Library of Virginia": {
                "survey": "Architectural Survey Collection",
                "unit": "Urban Documentation Project",
                "default": "Virginia Historical Images",
            },
            "VCU": {
                "postcard": "Historic Postcards Collection",
                "default": "VCU Digital Collections",
            },
        }

        self.stdout.write("Starting import...")

        with open(file_path, "r", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)

            with transaction.atomic():
                for row_num, row in enumerate(reader, 1):
                    try:
                        # Extract data from CSV
                        source_name = row["source"].strip()
                        source_url_from_csv = row["source_url"].strip()
                        img_url = row["img_url"].strip()
                        notes = row["notes"].strip()
                        year = self.parse_int(row["year"])
                        longitude = self.parse_float(row["longitude"])
                        latitude = self.parse_float(row["latitude"])
                        direction = self.parse_int(row["direction"])

                        if not source_name or not img_url:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"Row {row_num}: Missing source or image URL, skipping"
                                )
                            )
                            continue

                        # Get or create source
                        source_defaults = source_info.get(
                            source_name,
                            {
                                "url": source_url_from_csv,
                                "description": f"Historical image archive: {source_name}",
                            },
                        )

                        source, source_created = Source.objects.get_or_create(
                            name=source_name, defaults=source_defaults
                        )
                        if source_created:
                            created_sources += 1
                            self.stdout.write(f"Created source: {source.name}")

                        # Determine collection based on URL patterns
                        collection_name = self.determine_collection(
                            source_name, source_url_from_csv, collection_mappings
                        )

                        collection, collection_created = (
                            Collection.objects.get_or_create(
                                source=source,
                                name=collection_name,
                                defaults={
                                    "url": source_url_from_csv,
                                    "description": f"{collection_name} from {source_name}",
                                },
                            )
                        )
                        if collection_created:
                            created_collections += 1
                            self.stdout.write(f"Created collection: {collection.name}")

                        # Create image (skip if already exists by URL)
                        if Image.objects.filter(permalink=img_url).exists():
                            continue

                        # Generate title from URL or use generic
                        title = self.generate_title_from_url(img_url, source_name, year)

                        image = Image.objects.create(
                            collection=collection,
                            title=title,
                            permalink=img_url,
                            description=notes if notes else None,
                            year=year,
                        )
                        created_images += 1

                        # Create georeference if coordinates are available and requested
                        if (
                            options["create_georeferences"]
                            and longitude is not None
                            and latitude is not None
                            and admin_user
                        ):
                            georeference = Georeference.objects.create(
                                image=image,
                                latitude=latitude,
                                longitude=longitude,
                                direction=direction,
                                georeferenced_by=admin_user,
                                confidence_notes=notes
                                if notes
                                else "Imported from original data",
                            )
                            created_georeferences += 1

                    except Exception as e:
                        errors += 1
                        self.stdout.write(
                            self.style.ERROR(f"Row {row_num}: Error - {str(e)}")
                        )

        # Report results
        self.stdout.write(
            self.style.SUCCESS(
                f"\nImport completed:\n"
                f"  Sources: {created_sources}\n"
                f"  Collections: {created_collections}\n"
                f"  Images: {created_images}\n"
                f"  Georeferences: {created_georeferences}\n"
                f"  Errors: {errors}"
            )
        )

        if created_images > 0:
            self.stdout.write(f"\nYou can now browse at: http://localhost:8000/browse/")
            self.stdout.write(
                f"Start georeferencing at: http://localhost:8000/georeference/"
            )

    def determine_collection(self, source_name, source_url, collection_mappings):
        """Determine collection name based on source and URL patterns"""
        if source_name not in collection_mappings:
            return f"{source_name} Collection"

        mapping = collection_mappings[source_name]

        # Check URL for pattern matches
        for pattern, collection_name in mapping.items():
            if pattern != "default" and pattern.lower() in source_url.lower():
                return collection_name

        return mapping.get("default", f"{source_name} Collection")

    def generate_title_from_url(self, img_url, source_name, year):
        """Generate a meaningful title from the image URL"""
        # Extract filename or ID from URL
        if "valentine.rediscoverysoftware.com" in img_url:
            # Extract the image ID from Valentine Museum URLs
            parts = img_url.split("/")
            for part in parts:
                if (
                    part.startswith("I_")
                    or part.startswith("V_")
                    or part.startswith("P_")
                ):
                    # Clean up the ID
                    clean_id = part.split("-")[0]  # Remove file extension parts
                    clean_id = clean_id.replace("_", ".")
                    year_str = f" ({year})" if year else ""
                    return f"Image {clean_id}{year_str}"

        elif "lva.virginia.gov" in img_url:
            # Extract image code from Library of Virginia URLs
            parts = img_url.split("/")
            for part in parts:
                if part.endswith(".jpg") and ("A00" in part or "D0" in part):
                    clean_id = part.replace(".jpg", "")
                    year_str = f" ({year})" if year else ""
                    return f"LVA {clean_id}{year_str}"

        elif "vcu.edu" in img_url:
            year_str = f" ({year})" if year else ""
            return f"VCU Postcard{year_str}"

        # Fallback
        year_str = f" ({year})" if year else ""
        return f"{source_name} Image{year_str}"

    def parse_int(self, value):
        """Parse integer value, return None if empty or invalid"""
        if not value or str(value).strip() == "":
            return None
        try:
            return int(float(value))  # Handle strings like "1980.0"
        except (ValueError, TypeError):
            return None

    def parse_float(self, value):
        """Parse float value, return None if empty or invalid"""
        if not value or str(value).strip() == "":
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
