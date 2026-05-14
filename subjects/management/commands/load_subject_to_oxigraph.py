"""Load a subject's class-ancestor closure into Oxigraph in one go.

One WDQS query gets the seed entity and its P31?/P279* ancestors (labels +
class edges only). The response is parsed into per-entity named graphs and
loaded atomically into Oxigraph with a single SPARQL Update.

Now mostly used for manual refresh: the same closure load fires
automatically from ``WikidataItem.save()`` when a new Wikidata-backed
Subject is created. Running this command for an existing Subject
re-pulls and re-applies the metadata + closure.
"""

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db.models import F
from django.utils import timezone

from subjects.models import Subject, WikidataItem
from subjects.sparql_safety import looks_like_qid
from subjects.wikidata_closure import (
    SEED_METADATA_FIELDS,
    ClosureLoadError,
    commit_closure_to_oxigraph,
    fetch_seed_data,
)


def resolve_wikidata_id(value):
    """Accept either a Q-ID or a Subject slug; return the Q-ID."""
    if looks_like_qid(value):
        return value
    try:
        subject = Subject.objects.select_related("wikidata_item").get(slug=value)
    except Subject.DoesNotExist:
        raise CommandError(
            f'"{value}" is not a Q-ID and no Subject exists with that slug'
        )
    if not subject.wikidata_item:
        raise CommandError(f'Subject "{subject.slug}" has no linked WikidataItem')
    return subject.wikidata_item.wikidata_id


class Command(BaseCommand):
    help = (
        "Fetch a subject's class-ancestor closure from the Wikidata Query "
        "Service in one CONSTRUCT, then atomically load each entity into "
        "Oxigraph as its own named graph."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "identifier",
            help='Wikidata ID (e.g. "Q12345") or a Subject slug',
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=60,
            help="Timeout in seconds for the WDQS query (default: 60)",
        )

    def handle(self, *args, **options):
        seed_qid = resolve_wikidata_id(options["identifier"])
        self.stdout.write(f"Fetching closure for {seed_qid} from WDQS")

        try:
            data = fetch_seed_data(seed_qid, timeout=options["timeout"])
        except requests.RequestException as e:
            WikidataItem.objects.filter(wikidata_id=seed_qid).update(
                sparql_fetch_failures=F("sparql_fetch_failures") + 1,
            )
            raise CommandError(f"WDQS request failed for {seed_qid}: {e}") from e
        except ClosureLoadError as e:
            raise CommandError(str(e)) from e

        self.stdout.write(f"Got {len(data['turtle']):,} bytes of Turtle")
        triple_count = sum(len(ts) for ts in data["groups"].values())
        self.stdout.write(
            f"Parsed {triple_count:,} triples across {len(data['groups'])} entities"
        )

        # If this Q-ID is already a Subject, ancestors discovered by the
        # closure walk should point to it via ``discovered_via``.
        seed_subject = Subject.objects.filter(
            wikidata_item__wikidata_id=seed_qid
        ).first()

        seed_item = WikidataItem.objects.filter(wikidata_id=seed_qid).first()
        now = timezone.now()
        if seed_item is None:
            # No row yet for the seed - create one with the metadata we
            # just fetched. bulk_create bypasses save()'s SPARQL fetch,
            # which we already did.
            metadata = data["metadata"]
            seed_item = WikidataItem(
                wikidata_id=seed_qid,
                title=metadata["title"],
                description=metadata["description"],
                wikipedia_url=metadata["wikipedia_url"],
                architect=metadata["architect"],
                image_url=metadata["image_url"],
                inception=metadata["inception"],
                sparql_last_loaded_at=now,
                sparql_fetch_failures=0,
            )
            WikidataItem.objects.bulk_create([seed_item])
            self.stdout.write(f"Created WikidataItem row for {seed_qid}")
        else:
            seed_item._apply_seed_metadata(data["metadata"])
            seed_item.sparql_last_loaded_at = now
            seed_item.sparql_fetch_failures = 0
            # update_fields skips save()'s is_new branch (it's not new),
            # so no SPARQL re-fetch is triggered.
            seed_item.save(update_fields=list(SEED_METADATA_FIELDS))

        try:
            new_count = commit_closure_to_oxigraph(
                seed_qid,
                data["groups"],
                data["labels"],
                discovered_via=seed_subject,
            )
        except requests.RequestException as e:
            WikidataItem.objects.filter(wikidata_id=seed_qid).update(
                sparql_fetch_failures=F("sparql_fetch_failures") + 1,
            )
            raise CommandError(f"Oxigraph update failed: {e}") from e

        # +1 to account for the seed which commit_closure deliberately
        # skips (we handled its row above).
        refreshed = len(data["groups"]) - new_count
        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(data['groups'])} entities for {seed_qid} "
                f"({new_count} new, {refreshed} refreshed)"
            )
        )
