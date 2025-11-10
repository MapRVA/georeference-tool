from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = (
        "Refresh the materialized view for tile generation (public_georeferences_mvt)"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--concurrent",
            action="store_true",
            help="Use CONCURRENT refresh (non-blocking, requires unique index)",
        )

    def handle(self, *args, **options):
        concurrent = options.get("concurrent", False)

        refresh_method = (
            "REFRESH MATERIALIZED VIEW CONCURRENTLY"
            if concurrent
            else "REFRESH MATERIALIZED VIEW"
        )

        try:
            with connection.cursor() as cursor:
                cursor.execute(f"{refresh_method} public_georeferences_mvt")

            method_name = "concurrently" if concurrent else "blocking"
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully refreshed public_georeferences_mvt ({method_name})"
                )
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(
                    f"Failed to refresh public_georeferences_mvt: {str(e)}"
                )
            )
            raise
