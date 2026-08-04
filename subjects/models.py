import urllib
import urllib.parse
from datetime import datetime

import requests
from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class WikidataItem(models.Model):
    """Wikidata item with cached metadata"""

    wikidata_id = models.CharField(
        max_length=20, unique=True, help_text="Wikidata ID (e.g., Q123456)"
    )
    title = models.CharField(max_length=500, help_text="Title from Wikidata")
    description = models.TextField(blank=True, help_text="Description from Wikidata")
    wikipedia_url = models.URLField(
        blank=True, help_text="URL to Wikipedia page (if available)"
    )
    va_landmark_id = models.CharField(
        max_length=30, blank=True, help_text="Virginia Landmarks Registry ID"
    )
    architect = models.TextField(
        blank=True, help_text="Architect(s) - multiple names can be separated by commas"
    )
    image_url = models.URLField(
        max_length=500,
        blank=True,
        help_text="URL to representative image from Wikidata",
    )
    inception = models.DateField(
        null=True, blank=True, help_text="Date of construction/inception"
    )
    last_updated = models.DateTimeField(
        auto_now=True, help_text="When this row was last modified"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # Metadata refresh tracking
    metadata_last_fetched = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When we last attempted to fetch metadata from Wikidata",
    )
    metadata_fetch_failures = models.PositiveIntegerField(
        default=0,
        help_text="Consecutive fetch failures (resets on success)",
    )

    # WDQS mirror tracking - separate cadence from the JSON metadata fetch
    # above. Populated when we load this entity's closure (fetched from
    # WDQS via SPARQL) into the Memgraph mirror.
    sparql_last_loaded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this entity's RDF was last loaded into Oxigraph",
    )
    sparql_fetch_failures = models.PositiveIntegerField(
        default=0,
        help_text="Consecutive SPARQL mirror load failures (resets on success)",
    )
    discovered_via = models.ForeignKey(
        "Subject",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text=(
            "For ancestor entities pulled in by the closure walk, the Subject "
            "whose graph first surfaced this entity. Null for entities that "
            "are themselves Subjects."
        ),
    )

    def __str__(self):
        return f"{self.wikidata_id}: {self.title}"

    @property
    def wikidata_url(self):
        """Generate Wikidata URL from ID"""
        return f"https://www.wikidata.org/wiki/{self.wikidata_id}"

    def _fetch_wikidata_info(self):
        """Internal method to fetch and parse data from Wikidata API."""
        # Configure session with retry strategy
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        try:
            url = f"https://www.wikidata.org/wiki/Special:EntityData/{self.wikidata_id}.json"
            headers = {
                "User-Agent": "GeoreferenceTool/1.0 (https://github.com/mapRVA/georeference-tool)"
            }
            response = session.get(url, headers=headers, timeout=15)
            response.raise_for_status()

            if not response.text.strip():
                return None

            data = response.json()
            entity = data.get("entities", {}).get(self.wikidata_id)

            if not entity or "missing" in entity:
                return None

            title = entity.get("labels", {}).get("en", {}).get("value", "")
            description = entity.get("descriptions", {}).get("en", {}).get("value", "")
            wiki_title = entity.get("sitelinks", {}).get("enwiki", {}).get("title")
            wikipedia_url = (
                f"https://en.wikipedia.org/wiki/{urllib.parse.quote(wiki_title.replace(' ', '_'))}"
                if wiki_title
                else ""
            )

            architect = ""
            image_url = ""
            inception = None

            claims = entity.get("claims", {})
            if "P84" in claims:
                architects = []
                for claim in claims["P84"]:
                    if claim.get("mainsnak", {}).get("snaktype") == "value":
                        entity_id = claim["mainsnak"]["datavalue"]["value"]["id"]
                        architects.append(f"Wikidata:{entity_id}")
                architect = ", ".join(architects)

            if "P18" in claims:
                for claim in claims["P18"]:
                    if claim.get("mainsnak", {}).get("snaktype") == "value":
                        filename = claim["mainsnak"]["datavalue"]["value"]
                        filename_encoded = urllib.parse.quote(
                            filename.replace(" ", "_")
                        )
                        image_url = f"https://commons.wikimedia.org/w/index.php?title=Special:Redirect/file/{filename_encoded}&width=300"
                        break

            if "P571" in claims:
                for claim in claims["P571"]:
                    if claim.get("mainsnak", {}).get("snaktype") == "value":
                        time_data = claim["mainsnak"]["datavalue"]["value"]
                        if "time" in time_data and time_data["time"].startswith("+"):
                            inception = time_data["time"][1:11]
                            break

            return {
                "title": title or self.wikidata_id,
                "description": description,
                "wikipedia_url": wikipedia_url,
                "architect": architect,
                "image_url": image_url,
                "inception": inception,
            }

        except requests.RequestException as e:
            # Raise a validation error to be caught by the save method
            raise ValidationError(
                f"Network error fetching Wikidata info for {self.wikidata_id}: {e}"
            )
        except Exception as e:
            raise ValidationError(
                f"Unexpected error fetching Wikidata info for {self.wikidata_id}: {e}"
            )
        finally:
            session.close()

    def populate_from_wikidata(self):
        """Fetch and populate metadata from Wikidata API."""
        wikidata_info = self._fetch_wikidata_info()
        if wikidata_info:
            self.title = wikidata_info["title"]
            self.description = wikidata_info["description"]
            self.wikipedia_url = wikidata_info["wikipedia_url"]
            self.architect = wikidata_info["architect"]
            self.image_url = wikidata_info["image_url"]

            if wikidata_info["inception"]:
                try:
                    self.inception = datetime.strptime(
                        wikidata_info["inception"], "%Y-%m-%d"
                    ).date()
                except (ValueError, TypeError):
                    pass
            return True
        return False

    def _apply_seed_metadata(self, meta):
        """Apply a dict from extract_seed_metadata onto self in-place."""
        self.title = meta["title"]
        self.description = meta["description"]
        self.wikipedia_url = meta["wikipedia_url"]
        self.architect = meta["architect"]
        self.image_url = meta["image_url"]
        if meta["inception"]:
            self.inception = meta["inception"]

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if is_new:
            # On creation, title is required. Placeholder until SPARQL fills it.
            if not self.title:
                self.title = self.wikidata_id
            # Sync path is only the cheap entity-JSON fetch: confirms the
            # Q-ID resolves and gives us a label/description to return to
            # the caller. The P31?/P279* ancestor walk + Memgraph load is
            # deferred to ``hydrate_wikidata_item`` on the urgent queue.
            # ``sparql_last_loaded_at`` stays NULL so the Beat refresher
            # picks the row up too if that task never runs.
            if not self.populate_from_wikidata():
                raise ValidationError(
                    f"No Wikidata entity found for {self.wikidata_id}"
                )

        super().save(*args, **kwargs)

        if is_new:
            from .tasks import hydrate_wikidata_item

            qid = self.wikidata_id
            transaction.on_commit(lambda: hydrate_wikidata_item.delay(qid))

    class Meta:
        ordering = ["title"]
        indexes = [
            models.Index(fields=["sparql_last_loaded_at"]),
            # Trigram index on the English label backs the autocomplete
            # categories query, which uses ``title__icontains`` to find
            # matching ancestors. Django's ``__icontains`` translates to
            # ``ILIKE '%q%'`` on Postgres, which a GIN index with
            # ``gin_trgm_ops`` accelerates from a full scan to an indexed
            # lookup. Requires the ``pg_trgm`` extension (already enabled
            # by ``images/migrations/0035_enhance_search_vector.py``).
            GinIndex(
                fields=["title"],
                name="wikidataitem_title_trgm",
                opclasses=["gin_trgm_ops"],
            ),
        ]


class OsmElement(models.Model):
    """OpenStreetMap element with cached geometry"""

    osm_id = models.BigIntegerField(unique=True, help_text="OpenStreetMap element ID")
    subject = models.ForeignKey(
        "Subject",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="osm_elements",
        help_text="Subject this OSM element belongs to",
    )
    geometry = gis_models.GeometryField(
        spatial_index=True,
        help_text="Geometry of the OSM element (point, polygon, multipolygon, etc.)",
    )
    centroid = gis_models.PointField(
        null=True,
        blank=True,
        spatial_index=True,
        help_text="Centroid of the geometry (auto-populated on save)",
    )
    geometry_area = models.FloatField(
        default=0,
        help_text="Cached area of the geometry in square degrees (used for render ordering)",
    )
    updated_at = models.DateTimeField(
        auto_now=True, help_text="When this row was last updated"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"OSM Element {self.osm_id}"

    def save(self, *args, **kwargs):
        """Calculate geometry area and centroid before saving"""
        if self.geometry:
            self.geometry_area = self.geometry.area
            self.centroid = self.geometry.centroid
        super().save(*args, **kwargs)

    class Meta:
        ordering = ["osm_id"]


class Person(models.Model):
    first_name = models.CharField(max_length=200, blank=True)
    middle_name = models.CharField(max_length=200, blank=True)
    last_name = models.CharField(max_length=200, blank=True)
    suffix = models.CharField(max_length=50, blank=True, help_text="e.g. Jr., Sr., III")
    birth_date = models.CharField(
        max_length=50, blank=True, help_text="Birth date as EDTF string"
    )
    merged_into = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="merged_from",
        help_text="If set, this person has been merged into another record",
    )

    def __str__(self):
        parts = filter(
            None, [self.first_name, self.middle_name, self.last_name, self.suffix]
        )
        return " ".join(parts) or "Unknown Person"

    class Meta:
        verbose_name_plural = "people"
        ordering = ["last_name", "first_name"]


class Business(models.Model):
    """Can represent any sort of business or similar entity"""

    name = models.CharField(max_length=500)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "businesses"
        ordering = ["name"]


class Occupation(models.Model):
    name = models.CharField(max_length=500)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]


class Subject(models.Model):
    """Subject that can appear in images (buildings, people, monuments, etc.)"""

    title = models.CharField(max_length=500, help_text="Name/title of the subject")
    slug = models.SlugField(unique=True)
    wikidata_item = models.OneToOneField(
        WikidataItem,
        on_delete=models.CASCADE,
        related_name="subject",
        help_text="Linked Wikidata item",
    )
    representative_image = models.ForeignKey(
        "images.Image",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="User-chosen representative image for this subject",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # OSM population tracking (for subjects without an osm_element yet)
    osm_last_checked = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When we last attempted to find an OSM element for this subject",
    )

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title[:50])
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("subjects:subject_detail", kwargs={"subject_slug": self.slug})

    def get_description(self):
        """Return a description for display, sourced from the Wikidata item.

        Falls back to a placeholder referencing the Wikidata ID when the
        linked item has no description. Computed on demand, never stored.
        """
        if self.wikidata_item_id:
            return self.wikidata_item.description or (
                f"Subject from Wikidata: {self.wikidata_item.wikidata_id}"
            )
        return ""

    def get_representative_image(self):
        """Return the representative image for this subject, or None.

        ``representative_image`` is kept populated by signals on
        ``SubjectMapping`` (set on first mapping, re-elected on delete), so
        the field is the source of truth. The mapping fallback handles the
        edge case of a Subject with mappings but a null FK (e.g., a row
        predating the backfill).
        """
        if self.representative_image_id is not None:
            return self.representative_image

        first_mapping = (
            self.image_mappings.select_related("image").order_by("order", "id").first()
        )
        return first_mapping.image if first_mapping else None

    class Meta:
        ordering = ["title"]
        indexes = [
            # Trigram index backing the tagging autocomplete
            # (``title__icontains``). Only the ILIKE branch of that query
            # is index-assisted; the ``word_similarity`` annotation is
            # computed per row regardless. See the migration docstring.
            GinIndex(
                fields=["title"],
                name="subject_title_trgm",
                opclasses=["gin_trgm_ops"],
            ),
        ]


class SubjectAncestor(models.Model):
    """Materialized ``Subject -> WikidataItem`` ancestor relation.

    A flat projection of each Subject's category-relevant ancestors, derived
    from the same graph paths the autocomplete used to traverse on the fly
    (``P31?/P279*``, ``P1716``, ``P361``, and ``P361`` as a qualifier on any
    of the Subject's statements). Refreshed per-subject after each Memgraph
    closure load; query-time aggregation/substring-match runs against this
    table with proper indexes instead of via graph traversal.
    """

    subject = models.ForeignKey(
        "Subject",
        on_delete=models.CASCADE,
        related_name="ancestors",
    )
    ancestor = models.ForeignKey(
        "WikidataItem",
        on_delete=models.CASCADE,
        related_name="+",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["subject", "ancestor"],
                name="subjectancestor_unique_pair",
            ),
        ]
        indexes = [
            models.Index(fields=["ancestor"]),
        ]

    def __str__(self):
        return f"{self.subject_id} -> {self.ancestor_id}"
