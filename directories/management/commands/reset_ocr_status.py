from django.core.management.base import BaseCommand

from directories.models import Page


class Command(BaseCommand):
    help = "Reset stuck OCR tasks by clearing 'processing' status back to empty."

    def add_arguments(self, parser):
        parser.add_argument(
            "--page",
            type=str,
            help="Reset a specific page by UUID instead of all stuck pages.",
        )

    def handle(self, *args, **options):
        qs = Page.objects.filter(ocr_status="processing")

        if options["page"]:
            qs = qs.filter(uuid=options["page"])

        count = qs.count()
        if not count:
            self.stdout.write("No pages stuck in 'processing' status.")
            return

        qs.update(ocr_status="", ocr_error="")
        self.stdout.write(self.style.SUCCESS(f"Reset {count} page(s)."))
