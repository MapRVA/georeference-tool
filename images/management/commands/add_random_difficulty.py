import random
from django.core.management.base import BaseCommand
from images.models import Image


class Command(BaseCommand):
    help = "Add random difficulty levels to images that don't have them set"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Reset all difficulty levels and assign new random ones",
        )
        parser.add_argument(
            "--easy-percent",
            type=int,
            default=40,
            help="Percentage of images to mark as easy (default: 40)",
        )
        parser.add_argument(
            "--medium-percent",
            type=int,
            default=35,
            help="Percentage of images to mark as medium (default: 35)",
        )
        parser.add_argument(
            "--hard-percent",
            type=int,
            default=20,
            help="Percentage of images to mark as hard (default: 20)",
        )
        parser.add_argument(
            "--unrated-percent",
            type=int,
            default=5,
            help="Percentage of images to leave unrated (default: 5)",
        )

    def handle(self, *args, **options):
        easy_percent = options["easy_percent"]
        medium_percent = options["medium_percent"]
        hard_percent = options["hard_percent"]
        unrated_percent = options["unrated_percent"]

        # Validate percentages add up to 100
        total_percent = easy_percent + medium_percent + hard_percent + unrated_percent
        if total_percent != 100:
            self.stdout.write(
                self.style.ERROR(f"Percentages must add up to 100, got {total_percent}")
            )
            return

        if options["reset"]:
            # Reset all difficulty levels
            images = Image.objects.all()
            self.stdout.write(
                f"Resetting difficulty for all {images.count()} images..."
            )
        else:
            # Only update images without difficulty set
            images = Image.objects.filter(difficulty__isnull=True)
            self.stdout.write(
                f"Adding difficulty to {images.count()} unrated images..."
            )

        if not images.exists():
            self.stdout.write(self.style.WARNING("No images to update"))
            return

        # Convert to list and shuffle for randomness
        image_list = list(images)
        random.shuffle(image_list)

        total_images = len(image_list)

        # Calculate actual counts
        easy_count = int(total_images * easy_percent / 100)
        medium_count = int(total_images * medium_percent / 100)
        hard_count = int(total_images * hard_percent / 100)
        unrated_count = total_images - easy_count - medium_count - hard_count

        self.stdout.write(f"Distribution plan:")
        self.stdout.write(f"  Easy: {easy_count} ({easy_percent}%)")
        self.stdout.write(f"  Medium: {medium_count} ({medium_percent}%)")
        self.stdout.write(f"  Hard: {hard_count} ({hard_percent}%)")
        self.stdout.write(f"  Unrated: {unrated_count} ({unrated_percent}%)")

        # Assign difficulties
        updated_count = 0
        index = 0

        # Easy images
        for i in range(easy_count):
            image_list[index].difficulty = "easy"
            image_list[index].save(update_fields=["difficulty"])
            index += 1
            updated_count += 1

        # Medium images
        for i in range(medium_count):
            image_list[index].difficulty = "medium"
            image_list[index].save(update_fields=["difficulty"])
            index += 1
            updated_count += 1

        # Hard images
        for i in range(hard_count):
            image_list[index].difficulty = "hard"
            image_list[index].save(update_fields=["difficulty"])
            index += 1
            updated_count += 1

        # Remaining images stay unrated (difficulty = None)
        for i in range(unrated_count):
            image_list[index].difficulty = None
            image_list[index].save(update_fields=["difficulty"])
            index += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully updated difficulty for {updated_count} images"
            )
        )

        # Show final distribution
        final_counts = {
            "easy": Image.objects.filter(difficulty="easy").count(),
            "medium": Image.objects.filter(difficulty="medium").count(),
            "hard": Image.objects.filter(difficulty="hard").count(),
            "unrated": Image.objects.filter(difficulty__isnull=True).count(),
        }

        self.stdout.write("\nFinal difficulty distribution:")
        for level, count in final_counts.items():
            self.stdout.write(f"  {level.capitalize()}: {count}")
