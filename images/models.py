import urllib.parse

import requests
from django.contrib.admin.utils import quote
from django.contrib.auth.models import User
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.contrib.gis.db import models as gis_models
from django.db import models
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Conditionally import SearchVectorField only if using PostgreSQL
try:
    from django.contrib.postgres.search import SearchVectorField

    HAS_POSTGRES_SEARCH = True
except ImportError:
    HAS_POSTGRES_SEARCH = False
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils.text import slugify
from edtf import parse_edtf
from edtf.parser.edtf_exceptions import EDTFParseException


class Source(models.Model):
    """Archive source containing collections of images"""

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    url = models.URLField()
    description = models.TextField()
    public = models.BooleanField(
        default=True, help_text="Whether this source is visible to users"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("images:source_detail", kwargs={"slug": self.slug})

    class Meta:
        ordering = ["name"]


class Collection(models.Model):
    """Collection within a source containing images"""

    source = models.ForeignKey(
        Source, on_delete=models.CASCADE, related_name="collections"
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField()
    url = models.URLField()
    description = models.TextField(blank=True)
    public = models.BooleanField(
        default=True, help_text="Whether this collection is visible to users"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.source.name} - {self.name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name[:50])
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse(
            "images:collection_detail",
            kwargs={"source_slug": self.source.slug, "collection_slug": self.slug},
        )

    @property
    def is_public(self):
        """Check if both collection and source are public"""
        return self.public and self.source.public

    class Meta:
        ordering = ["source__name", "name"]
        unique_together = ["source", "name", "slug"]


class PreCollection(models.Model):
    """Collection within a source containing images that have yet to be reviewed for inclusion"""

    source = models.ForeignKey(
        Source, on_delete=models.CASCADE, related_name="pre_collections"
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField()
    url = models.URLField()
    description = models.TextField(blank=True)
    complete = models.BooleanField(
        default=False,
        help_text="Whether this collection has been reviewed and is complete",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.source.name} - {self.name} (Pre-review)"

    def clean(self):
        """Validate model fields"""
        super().clean()

        # Prevent marking collection as complete if any images have null keep values
        if self.complete and self.pk:
            images_with_null_keep = self.images.filter(keep__isnull=True)
            if images_with_null_keep.exists():
                raise ValidationError(
                    {
                        "complete": f"Cannot mark collection as complete. {images_with_null_keep.count()} images still need review (keep field is null)."
                    }
                )

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name[:50])
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse(
            "images:pre_collection_detail",
            kwargs={"source_slug": self.source.slug, "collection_slug": self.slug},
        )

    @property
    def is_public(self):
        """Check if both collection and source are public"""
        return self.public and self.source.public

    class Meta:
        ordering = ["source__name", "name"]
        unique_together = ["source", "name", "slug"]


class Image(models.Model):
    """Individual image to be georeferenced"""

    DIFFICULTY_CHOICES = [
        ("easy", "Easy"),
        ("medium", "Medium"),
        ("hard", "Hard"),
    ]

    collection = models.ForeignKey(
        Collection, on_delete=models.CASCADE, related_name="images"
    )

    title = models.CharField(max_length=500)
    permalink = models.URLField(
        help_text="Direct link to the image (CDN or processed URL)"
    )
    original_url = models.URLField(
        null=True, help_text="Original URL from the source website"
    )
    description = models.TextField(null=True)
    license_title = models.CharField(null=True, max_length=500)
    license_permalink = models.URLField(
        null=True, help_text="Link to license information"
    )

    creator = models.CharField(
        null=True, max_length=100, help_text="Creator(s) of the work"
    )
    ref = models.CharField(
        null=True, max_length=50, help_text="Source-specific reference"
    )

    original_date = models.CharField(
        null=True, max_length=50, help_text="Date information from source"
    )
    edtf_date = models.CharField(
        null=True, max_length=50, help_text="Date parsed as EDTF"
    )
    start_decdate = models.IntegerField(
        null=True, help_text="Start of date range in decimal format"
    )
    fuzzy_start_decdate = models.IntegerField(
        null=True, help_text="Fuzzy start of date range in decimal format"
    )
    end_decdate = models.IntegerField(
        null=True, help_text="End of date range in decimal format"
    )
    fuzzy_end_decdate = models.IntegerField(
        null=True, help_text="Fuzzy end of date range in decimal format"
    )

    def clean(self):
        """Validate model fields"""
        super().clean()

        # Validate EDTF date format if provided
        if self.edtf_date:
            try:
                parse_edtf(self.edtf_date)
            except EDTFParseException as e:
                raise ValidationError({"edtf_date": f"Invalid EDTF format: {str(e)}"})

        # Prevent chains of duplicates
        if self.duplicate_of:
            # Check if any other image is already marked as a duplicate of this image
            if self.pk and Image.objects.filter(duplicate_of=self.pk).exists():
                raise ValidationError(
                    {
                        "duplicate_of": "Cannot mark this image as a duplicate because other images are already marked as duplicates of this one. Chains of duplicates are not allowed."
                    }
                )

        # Prevent marking georeferenced images as duplicates
        if self.duplicate_of and self.pk:
            # Check if this image has any georeferences
            if self.georeferences.exists():
                raise ValidationError(
                    {
                        "duplicate_of": "Cannot mark this image as a duplicate because it has already been georeferenced. Georeferenced images should not be marked as duplicates."
                    }
                )

    def save(self, *args, **kwargs):
        """Validate EDTF date format and pre-calculate decimal dates before saving"""
        if self.edtf_date:
            try:
                edtf_date = parse_edtf(self.edtf_date)
                self.start_decdate = edtf_date.lower_strict()[0]
                self.fuzzy_start_decdate = edtf_date.lower_fuzzy()[0]
                self.end_decdate = edtf_date.upper_strict()[0]
                self.fuzzy_end_decdate = edtf_date.upper_fuzzy()[0]
            except EDTFParseException as e:
                raise ValidationError(f'Invalid EDTF date "{self.edtf_date}": {str(e)}')
        else:
            self.start_decdate = None
            self.fuzzy_start_decdate = None
            self.end_decdate = None
            self.fuzzy_end_decdate = None
        super().save(*args, **kwargs)

    # Georeferencing metadata
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES, null=True)
    will_not_georef = models.BooleanField(default=False)
    skip_count = models.PositiveIntegerField(default=0)
    duplicate_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="duplicates",
        help_text="ID of another Image if this is a duplicate",
    )

    # Image embedding for CLIP similarity search
    embedding = ArrayField(
        models.FloatField(),
        null=True,
        blank=True,
        help_text="CLIP embedding vector for image similarity search (dimension varies by model)",
    )

    # Subjects that appear in this image
    subjects = models.ManyToManyField(
        "Subject",
        through="SubjectMapping",
        blank=True,
        help_text="Subjects (buildings, people, monuments, etc.) that appear in this image",
    )

    # Full-text search vector (only works with PostgreSQL, ignored in SQLite)
    if HAS_POSTGRES_SEARCH:
        search_vector = SearchVectorField(
            null=True,
            blank=True,
            help_text="Full-text search vector for title, description, location, and year",
        )
    else:
        search_vector = models.TextField(
            null=True,
            blank=True,
            help_text="Full-text search vector for title, description, location, and year",
        )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        if self.title:
            return f"{self.title} ({self.id})"
        return f"Image {self.id} from {self.collection.name}"

    def get_absolute_url(self):
        return reverse("images:image_detail", kwargs={"image_id": self.id})

    @property
    def date_display(self):
        if self.original_date:
            return str(self.original_date)
        return "Unknown date"

    @property
    def is_georeferenced(self):
        """Check if this image has been georeferenced"""
        return self.georeferences.exists()

    @property
    def georeference_count(self):
        """Number of georeferences submitted for this image"""
        return self.georeferences.count()

    @property
    def georeference_status(self):
        """Get the current georeferencing status"""
        if self.duplicate_of:
            return "duplicate"
        elif self.will_not_georef:
            return "will_not_georef"
        elif self.is_georeferenced:
            # Check if any georeferences have validations
            if any(
                georeference.validations.exists()
                for georeference in self.georeferences.all()
            ):
                return "validated"
            else:
                return "georeferenced"
        else:
            return "pending"

    def get_georeference(self):
        """Get the most recent georeference for this image"""
        return self.georeferences.order_by("-georeferenced_at").first()

    class Meta:
        ordering = ["collection__source__name", "collection__name", "id"]
        indexes = [
            models.Index(fields=["collection", "will_not_georef"]),
            models.Index(fields=["difficulty"]),
        ]


class PreImage(models.Model):
    """Individual image that has yet to be reviewed for inclusion in the site"""

    DIFFICULTY_CHOICES = [
        ("easy", "Easy"),
        ("medium", "Medium"),
        ("hard", "Hard"),
    ]

    collection = models.ForeignKey(
        PreCollection, on_delete=models.CASCADE, related_name="images"
    )

    title = models.CharField(max_length=500)
    permalink = models.URLField(
        help_text="Direct link to the image (CDN or processed URL)"
    )
    description = models.TextField(null=True)
    license_title = models.CharField(null=True, max_length=500)
    license_permalink = models.URLField(
        null=True, help_text="Link to license information"
    )

    creator = models.CharField(
        null=True, max_length=100, help_text="Creator(s) of the work"
    )
    ref = models.CharField(
        null=True, max_length=50, help_text="Source-specific reference"
    )

    original_date = models.CharField(
        null=True, max_length=50, help_text="Date information from source"
    )
    edtf_date = models.CharField(
        null=True, max_length=50, help_text="Date parsed as EDTF"
    )

    def clean(self):
        """Validate model fields"""
        super().clean()

        # Validate EDTF date format if provided
        if self.edtf_date:
            try:
                parse_edtf(self.edtf_date)
            except EDTFParseException as e:
                raise ValidationError({"edtf_date": f"Invalid EDTF format: {str(e)}"})

    # Review metadata
    keep = models.BooleanField(
        null=True,
        default=None,
        help_text="Whether to keep this image for the main collection",
    )
    imported = models.BooleanField(
        default=False,
        help_text="Whether this image has been imported",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        if self.title:
            return f"{self.title} (Pre-review)"
        return f"PreImage {self.id} from {self.collection.name}"

    def get_absolute_url(self):
        # PreImages are for review only, link to admin interface
        return f"/admin/images/preimage/{quote(self.pk)}/change/"

    @property
    def date_display(self):
        if self.original_date:
            return str(self.original_date)
        return "Unknown date"


class Georeference(models.Model):
    """Georeference data for an image - multiple submissions allowed"""

    CONFIDENCE_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
    ]

    image = models.ForeignKey(
        Image, on_delete=models.CASCADE, related_name="georeferences"
    )

    # Coordinate data
    point = gis_models.PointField(spatial_index=True)
    direction = models.IntegerField(
        null=True,
        validators=[MinValueValidator(0), MaxValueValidator(359)],
        help_text="Direction in degrees (0-359), where 0 is North",
    )

    # Confidence level - mandatory field
    confidence = models.CharField(
        max_length=10,
        choices=CONFIDENCE_CHOICES,
        default="medium",
        help_text="Confidence level in the accuracy of this georeference",
    )

    # Tracking information
    georeferenced_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="georeferenced_images",
        null=True,
        help_text="User who submitted the georeference (null for anonymous submissions)",
    )
    georeferenced_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Quality/confidence notes from contributor
    confidence_notes = models.TextField(
        blank=True,
        help_text="Optional notes about the georeferencing confidence or methodology",
    )

    def __str__(self):
        by_user = (
            self.georeferenced_by.username if self.georeferenced_by else "Anonymous"
        )
        return f"Georeference for {self.image} by {by_user}"

    @property
    def validation_count(self):
        """Number of validations this georeference has received"""
        return self.validations.count()

    def get_validation_counts(self):
        """Get counts for each validation type"""
        from django.db.models import Count, Q

        return self.validations.aggregate(
            correct=Count("pk", filter=Q(validation="correct")),
            uncertain=Count("pk", filter=Q(validation="uncertain")),
            incorrect=Count("pk", filter=Q(validation="incorrect")),
        )

    class Meta:
        indexes = [
            models.Index(fields=["image", "georeferenced_by"]),
            models.Index(fields=["georeferenced_by"]),
            models.Index(fields=["georeferenced_at"]),
        ]
        constraints = [
            # Removed unique constraint to allow multiple georeferences per user per image
            # This enables correction submissions and maintains full georeferencing history
        ]


class GeoreferenceValidation(models.Model):
    """Validation of a georeference by other users"""

    VALIDATION_CHOICES = [
        ("correct", "Correct"),
        ("incorrect", "Incorrect"),
        ("uncertain", "Uncertain"),
    ]

    georeference = models.ForeignKey(
        Georeference, on_delete=models.CASCADE, related_name="validations"
    )
    validated_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="georeference_validations"
    )
    validation = models.CharField(max_length=10, choices=VALIDATION_CHOICES)
    notes = models.TextField(blank=True, help_text="Optional validation notes")
    validated_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.validation} validation by {self.validated_by.username}"

    class Meta:
        unique_together = ["georeference", "validated_by"]
        indexes = [
            models.Index(fields=["georeference", "validation"]),
            models.Index(fields=["validated_by"]),
        ]


class ImageSkip(models.Model):
    """Track when users skip images"""

    image = models.ForeignKey(Image, on_delete=models.CASCADE, related_name="skips")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="image_skips")
    skipped_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(
        max_length=100, blank=True, help_text="Optional reason for skipping"
    )

    def __str__(self):
        return f"Skip by {self.user.username} for {self.image}"

    class Meta:
        unique_together = ["image", "user"]
        indexes = [
            models.Index(fields=["image"]),
            models.Index(fields=["user"]),
            models.Index(fields=["skipped_at"]),
        ]


class LayerCollection(models.Model):
    """Collection of map layers that can be toggled together"""

    name = models.CharField(
        max_length=200, help_text="Display name for this collection"
    )

    description = models.TextField(
        blank=True, help_text="Optional description of this collection"
    )
    order = models.PositiveIntegerField(
        default=0, help_text="Display order (lower numbers first)"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["order", "name"]


class MapLayer(models.Model):
    """Individual map layer with pmtiles URL and metadata"""

    TYPE_CHOICES = [
        ("pmtiles", "PMTiles"),
        ("xyz", "XYZ Tiles"),
    ]

    name = models.CharField(max_length=200, help_text="Display name for this layer")

    type = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
        default="pmtiles",
        help_text="Type of map layer (PMTiles or XYZ)",
    )
    url = models.URLField(
        help_text="URL to the tile source (PMTiles file or XYZ endpoint)"
    )
    attribution = models.TextField(blank=True, help_text="Optional attribution text")
    collection = models.ForeignKey(
        LayerCollection,
        on_delete=models.CASCADE,
        related_name="layers",
        help_text="Collection this layer belongs to",
    )
    order = models.PositiveIntegerField(
        default=0, help_text="Display order within collection (lower numbers first)"
    )

    # Optional metadata
    description = models.TextField(
        blank=True, help_text="Optional description of this layer"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.collection.name})"

    class Meta:
        ordering = ["collection__order", "collection__name", "order", "name"]


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
        auto_now=True, help_text="When metadata was last fetched from Wikidata"
    )
    created_at = models.DateTimeField(auto_now_add=True)

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
                    from datetime import datetime

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

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title[:50])
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("images:subject_detail", kwargs={"subject_slug": self.slug})

    class Meta:
        ordering = ["title"]


class SubjectMapping(models.Model):
    """Through model connecting images to subjects with ordering"""

    image = models.ForeignKey(
        Image, on_delete=models.CASCADE, related_name="subject_mappings"
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="image_mappings"
    )
    order = models.PositiveIntegerField(
        default=0, help_text="Display order on image page (lower numbers first)"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.image} - {self.subject}"

    class Meta:
        unique_together = ["image", "subject"]
        ordering = ["image", "order", "subject__title"]


@receiver([post_save, post_delete], sender=ImageSkip)
def update_skip_count(sender, instance, **kwargs):
    """Update the skip_count on Image when ImageSkip is created/deleted"""
    instance.image.skip_count = instance.image.skips.count()
    instance.image.save(update_fields=["skip_count"])
