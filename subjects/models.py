import urllib
import urllib.parse
from datetime import datetime

import requests
from django.contrib.gis.db import models as gis_models
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
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

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if is_new:
            # On creation, title is required. We use wikidata_id as a placeholder.
            if not self.title:
                self.title = self.wikidata_id
            self.populate_from_wikidata()

        super().save(*args, **kwargs)

    class Meta:
        ordering = ["title"]


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


class Subject(models.Model):
    """Subject that can appear in images (buildings, people, monuments, etc.)"""

    title = models.CharField(max_length=500, help_text="Name/title of the subject")
    slug = models.SlugField(unique=True)
    description = models.TextField(help_text="Admin-written description of the subject")
    wikidata_item = models.ForeignKey(
        WikidataItem,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="subjects",
        help_text="Optional linked Wikidata item",
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

    class Meta:
        ordering = ["title"]
