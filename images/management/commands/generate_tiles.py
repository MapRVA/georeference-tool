from django.core.management.base import BaseCommand

from images.models import Image
from images.tasks import generate_iiif_tiles


class Command(BaseCommand):
    help = "Queue IIIF tile generation for images that don't have tiles yet."

    def add_arguments(self, parser):
        parser.add_argument(
            "--collection",
            type=int,
            help="Only process images in this collection ID",
        )
        parser.add_argument(
            "--image",
            type=int,
            help="Only process this specific image ID",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum number of images to queue",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-generate tiles even for images that already have them",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be queued without actually queuing",
        )

    def handle(self, **options):
        qs = Image.objects.all()

        if options["image"]:
            qs = qs.filter(pk=options["image"])
        elif options["collection"]:
            qs = qs.filter(collection_id=options["collection"])

        if not options["force"]:
            qs = qs.exclude(tile_status="complete")

        qs = qs.order_by("id")

        if options["limit"]:
            qs = qs[: options["limit"]]

        image_ids = list(qs.values_list("id", flat=True))

        if options["dry_run"]:
            self.stdout.write(f"Would queue {len(image_ids)} image(s) for tile generation.")
            return

        for image_id in image_ids:
            generate_iiif_tiles.delay(image_id)

        self.stdout.write(self.style.SUCCESS(f"Queued {len(image_ids)} image(s) for tile generation."))
