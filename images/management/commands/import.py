"""
Import images from various sources.

Usage:
    uv run manage.py import <source> [source-specific args]
"""

import sys
from importlib import import_module

from django.core.management.base import BaseCommand, CommandError

from images.models import License


def prompt_license():
    """Prompt the user to select a license from the database, or skip."""
    licenses = list(License.objects.all())
    if not licenses:
        print("No licenses found in the database. Proceeding without a license.")
        return None

    print("\nSelect a license for imported images:")
    print("  0) No license")
    for i, lic in enumerate(licenses, start=1):
        print(f"  {i}) {lic.name}")

    while True:
        try:
            choice = int(input("\nEnter number: "))
        except (ValueError, EOFError):
            print("Please enter a valid number.")
            continue
        if choice == 0:
            return None
        if 1 <= choice <= len(licenses):
            selected = licenses[choice - 1]
            print(f"Selected: {selected.name}")
            return selected
        print(f"Please enter a number between 0 and {len(licenses)}.")


class Command(BaseCommand):
    help = "Import images from a source. Run 'manage.py import <source> --help' for source-specific options."

    def _get_source_module(self, source_name):
        try:
            return import_module(f".importers.{source_name}", package=__package__)
        except ModuleNotFoundError:
            raise CommandError(f"Unknown source: '{source_name}'")

    def create_parser(self, prog_name, subcommand, **kwargs):
        parser = super().create_parser(prog_name, subcommand, **kwargs)

        # Peek at argv to find the source name so we can add its arguments
        # This makes --help work correctly for each source
        for arg in sys.argv[2:]:
            if not arg.startswith("-"):
                try:
                    module = self._get_source_module(arg)
                    module.add_arguments(parser)
                except CommandError:
                    pass
                break

        return parser

    def add_arguments(self, parser):
        parser.add_argument(
            "source", type=str, help="Source to import from (e.g. valentine)"
        )

    def handle(self, *args, **options):
        module = self._get_source_module(options["source"])
        if not getattr(module, "SKIP_LICENSE_PROMPT", False):
            options["license"] = prompt_license()
        module.handle(options)
