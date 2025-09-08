from django.core.management.base import BaseCommand
from django.db import transaction
from images.models import Image, Georeference
import random


class Command(BaseCommand):
    help = "Setup data for testing georeferencing interface"

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep-percent",
            type=int,
            default=20,
            help="Percentage of georeferences to keep (default: 20)",
        )
        parser.add_argument(
            "--add-difficulties",
            action="store_true",
            help="Also add random difficulty levels to images",
        )

    def handle(self, *args, **options):
        keep_percent = options["keep_percent"]

        with transaction.atomic():
            # Get all existing georeferences
            all_georeferences = list(Georeference.objects.all())
            total_count = len(all_georeferences)

            if total_count == 0:
                self.stdout.write(self.style.WARNING("No georeferences found"))
                return

            # Calculate how many to keep
            keep_count = int(total_count * keep_percent / 100)

            # Randomly select which ones to keep
            random.shuffle(all_georeferences)
            to_delete = all_georeferences[keep_count:]

            self.stdout.write(
                f"Deleting {len(to_delete)} of {total_count} georeferences..."
            )
            self.stdout.write(f"Keeping {keep_count} georeferences ({keep_percent}%)")

            # Delete the selected georeferences
            deleted_count = 0
            for georeference in to_delete:
                georeference.delete()
                deleted_count += 1

            self.stdout.write(
                self.style.SUCCESS(f"Deleted {deleted_count} georeferences")
            )

            # Add random difficulties if requested
            if options["add_difficulties"]:
                self.stdout.write("Adding random difficulty levels...")

                # Get all images without difficulty
                images_without_difficulty = list(
                    Image.objects.filter(difficulty__isnull=True)
                )

                if images_without_difficulty:
                    random.shuffle(images_without_difficulty)
                    total_images = len(images_without_difficulty)

                    # Distribution: 40% easy, 35% medium, 20% hard, 5% unrated
                    easy_count = int(total_images * 0.4)
                    medium_count = int(total_images * 0.35)
                    hard_count = int(total_images * 0.2)

                    difficulties_assigned = 0

                    # Assign easy
                    for i in range(easy_count):
                        images_without_difficulty[i].difficulty = "easy"
                        images_without_difficulty[i].save(update_fields=["difficulty"])
                        difficulties_assigned += 1

                    # Assign medium
                    for i in range(easy_count, easy_count + medium_count):
                        images_without_difficulty[i].difficulty = "medium"
                        images_without_difficulty[i].save(update_fields=["difficulty"])
                        difficulties_assigned += 1

                    # Assign hard
                    for i in range(
                        easy_count + medium_count,
                        easy_count + medium_count + hard_count,
                    ):
                        images_without_difficulty[i].difficulty = "hard"
                        images_without_difficulty[i].save(update_fields=["difficulty"])
                        difficulties_assigned += 1

                    # Remaining stay unrated

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Added difficulty levels to {difficulties_assigned} images"
                        )
                    )

        # Show final statistics
        final_stats = {
            "total_images": Image.objects.count(),
            "georeferenced": Image.objects.filter(georeference__isnull=False).count(),
            "pending": Image.objects.filter(
                georeference__isnull=True, will_not_georef=False
            ).count(),
            "will_not_georef": Image.objects.filter(will_not_georef=True).count(),
        }

        difficulty_stats = {
            "easy": Image.objects.filter(difficulty="easy").count(),
            "medium": Image.objects.filter(difficulty="medium").count(),
            "hard": Image.objects.filter(difficulty="hard").count(),
            "unrated": Image.objects.filter(difficulty__isnull=True).count(),
        }

        self.stdout.write("\n" + "=" * 50)
        self.stdout.write("FINAL STATISTICS")
        self.stdout.write("=" * 50)

        self.stdout.write(f"Total Images: {final_stats['total_images']}")
        self.stdout.write(f"Already Georeferenced: {final_stats['georeferenced']}")
        self.stdout.write(f"Available for Georeferencing: {final_stats['pending']}")
        self.stdout.write(
            f'Marked "Will Not Georeference": {final_stats["will_not_georef"]}'
        )

        self.stdout.write("\nDifficulty Distribution:")
        self.stdout.write(f"  Easy: {difficulty_stats['easy']}")
        self.stdout.write(f"  Medium: {difficulty_stats['medium']}")
        self.stdout.write(f"  Hard: {difficulty_stats['hard']}")
        self.stdout.write(f"  Unrated: {difficulty_stats['unrated']}")

        self.stdout.write("\nYou can now test:")
        self.stdout.write("  Browse: http://localhost:8000/browse/")
        self.stdout.write("  Georeference: http://localhost:8000/georeference/")
        self.stdout.write("  Admin: http://localhost:8000/admin/ (admin/admin)")
