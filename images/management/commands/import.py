"""
Import images from various sources.

Usage:
    uv run manage.py import <source> [source-specific args]
"""

import sys
from importlib import import_module

from django.core.management.base import BaseCommand, CommandError


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
        module.handle(options)
