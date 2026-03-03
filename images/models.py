import uuid

from django.contrib.admin.utils import quote
from django.contrib.auth.models import User
from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.fields import ArrayField
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Count, F, Q

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


class TileVersion(models.Model):
    """
    Singleton model for tracking the tile cache version.
    When georeferences change, the version is bumped to invalidate cached tiles.
    Stored in the database to persist across deployments and cache clears.
    """

    version = models.PositiveIntegerField(default=1)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_version(cls):
        """Get the current tile version, creating the row if needed."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj.version

    @classmethod
    def bump(cls):
        """Increment the tile version atomically."""
        cls.objects.get_or_create(pk=1)
        cls.objects.filter(pk=1).update(version=F("version") + 1)
        return cls.objects.get(pk=1).version

    class Meta:
        verbose_name = "tile version"
        verbose_name_plural = "tile version"


class SiteSettings(models.Model):
    """
    Singleton model for site-wide configuration settings.
    Used to store deployment-specific text and preferences.
    """

    site_title = models.CharField(
        max_length=200,
        default="Yesterdays",
        help_text="Main title displayed on the homepage",
    )
    site_subtitle = models.TextField(
        default="Place historical images on the map!",
        help_text="Subtitle/description displayed on the homepage",
    )
    footer_content = models.TextField(
        default='Yesterdays is proudly built by <a href="https://maprva.org" target="_blank" class="text-decoration-none">MapRVA</a>',
        help_text="HTML content for the site footer",
    )
    admin_email = models.EmailField(
        blank=True,
        null=True,
        help_text="Admin contact email, used for external API requests (e.g., Nominatim geocoder)",
    )
    default_map_longitude = models.FloatField(
        default=-77.43916,
        help_text="Default map center longitude",
    )
    default_map_latitude = models.FloatField(
        default=37.54376,
        help_text="Default map center latitude",
    )
    default_map_zoom = models.FloatField(
        default=10.0,
        help_text="Default map zoom level (0-22, supports decimals like 11.5)",
    )

    class Meta:
        verbose_name = "Site Settings"
        verbose_name_plural = "Site Settings"

    def __str__(self):
        return "Site Settings"

    def save(self, *args, **kwargs):
        # Ensure only one instance can exist
        self.pk = 1
        super().save(*args, **kwargs)
        # Invalidate cache so all processes pick up the new settings
        cache.delete("site_settings")

    @classmethod
    def load(cls):
        """Get the singleton instance, creating it if it doesn't exist"""

        cached = cache.get("site_settings")
        if cached is not None:
            return cached
        obj, created = cls.objects.get_or_create(pk=1)
        cache.set("site_settings", obj, timeout=300)  # 5 minutes
        return obj


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


class License(models.Model):
    """License under which an image is published"""

    name = models.CharField(max_length=500)
    display_name = models.CharField(
        max_length=500,
        help_text="Name shown on the site",
    )
    permalink = models.URLField(
        null=True, blank=True, help_text="Link to license information"
    )
    description = models.TextField(
        blank=True, help_text="Internal notes about this license"
    )
    flickr_id = models.SmallIntegerField(
        null=True, blank=True, unique=True, help_text="Flickr license ID"
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]


class Image(models.Model):
    """Individual image to be georeferenced"""

    DIFFICULTY_CHOICES = [
        ("easy", "Easy"),
        ("medium", "Medium"),
        ("hard", "Hard"),
    ]

    ROTATION_CHOICES = [
        (0, "None"),
        (90, "90°"),
        (180, "180°"),
        (270, "270°"),
    ]

    MIRROR_CHOICES = [
        ("none", "None"),
        ("h", "Horizontal"),
        ("v", "Vertical"),
    ]

    collection = models.ForeignKey(
        Collection, on_delete=models.CASCADE, related_name="images"
    )

    title = models.CharField(max_length=500)
    permalink = models.URLField(
        help_text="Direct link to the image (CDN or processed URL)"
    )
    thumbnail = models.URLField(
        null=True,
        blank=True,
        help_text="Direct link to the thumbnail (CDN or processed URL)",
    )
    transformed_permalink = models.URLField(
        null=True,
        blank=True,
        help_text="Transformed version of the image (rotated/mirrored), generated automatically",
    )
    original_url = models.URLField(
        null=True, help_text="Original URL from the source website"
    )
    description = models.TextField(null=True)
    license = models.ForeignKey(
        License, null=True, blank=True, on_delete=models.SET_NULL, related_name="images"
    )

    creator = models.CharField(
        null=True, max_length=100, help_text="Creator(s) of the work"
    )
    ref = models.CharField(
        null=True, max_length=100, help_text="Source-specific reference"
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

    @property
    def has_transform(self):
        """Whether this image has any rotation or mirror transform applied."""
        return self.rotation != 0 or self.mirror != "none"

    @property
    def display_permalink(self):
        """The URL to use when displaying this image.

        Returns transformed_permalink if available, otherwise permalink.
        """
        return self.transformed_permalink or self.permalink

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

        # When transforms change, clear stale assets immediately so the user
        # sees the original image while the background task regenerates them.
        update_fields = kwargs.get("update_fields")
        if self.pk and (
            update_fields is None or {"rotation", "mirror"} & set(update_fields)
        ):
            try:
                old = Image.objects.only("rotation", "mirror").get(pk=self.pk)
                if old.rotation != self.rotation or old.mirror != self.mirror:
                    self.transformed_permalink = None
                    self.thumbnail = None
            except Image.DoesNotExist:
                pass

        super().save(*args, **kwargs)

    # Is this image an aerial?
    aerial = models.BooleanField(default=False)

    # Georeferencing metadata
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES, null=True)
    scale = models.IntegerField(
        null=True,
        blank=True,
        default=None,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Scale: 1 (close-up/indoor), 2 (single building), 3 (multiple buildings), 4 (city block), 5 (wide landscape).",
    )
    will_not_georef = models.BooleanField(default=False)
    rotation = models.IntegerField(
        choices=ROTATION_CHOICES,
        default=0,
        help_text="Clockwise rotation to apply when displaying this image",
    )
    mirror = models.CharField(
        max_length=4,
        choices=MIRROR_CHOICES,
        default="none",
        help_text="Mirror transform to apply when displaying this image",
    )
    skip_count = models.PositiveIntegerField(default=0)
    source_point = gis_models.PointField(
        null=True,
        blank=True,
        spatial_index=False,
        help_text="Location hint from source metadata (e.g., embedded coordinates from archive)",
    )
    detected_address = gis_models.PointField(
        null=True,
        blank=True,
        spatial_index=False,
        help_text="Location detected from address parsing in image metadata",
    )
    duplicate_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="duplicates",
        help_text="ID of another Image if this is a duplicate",
    )

    # Denormalized visibility field for search performance
    # Computed from: collection.public AND collection.source.public AND duplicate_of IS NULL
    # Kept in sync via Django signals on Source, Collection, and Image changes
    is_searchable = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether this image appears in search results (auto-computed from collection/source visibility and duplicate status)",
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
        "subjects.Subject",
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
        """Check if this image has been georeferenced.

        For aerial (from-above) images: requires a polygon georeference.
        Point georeferences may exist but don't count toward this status.

        For regular images: requires a point georeference.
        """
        if self.aerial:
            return self.aerial_georeferences.exists()
        return self.georeferences.exists()

    @property
    def georeference_count(self):
        """Number of georeferences submitted for this image"""
        return self.georeferences.count()

    @property
    def georeference_status(self):
        """Get the current georeferencing status.

        Returns one of: "duplicate", "will_not_georef", "georeferenced",
        or "pending".
        """
        if self.duplicate_of:
            return "duplicate"
        elif self.will_not_georef:
            return "will_not_georef"
        elif self.is_georeferenced:
            return "georeferenced"
        else:
            return "pending"

    def get_georeference(self):
        """Get the most recent georeference for this image"""
        return self.georeferences.order_by("-georeferenced_at").first()

    def get_aerial_georeference(self):
        """Get the most recent aerial georeference for this image"""
        return self.aerial_georeferences.order_by("-georeferenced_at").first()

    def get_next_image(self):
        """Get the next image in the same collection (ordered by ID)"""
        return (
            Image.objects.filter(
                collection=self.collection,
                id__gt=self.id,
            )
            .order_by("id")
            .first()
        )

    def get_previous_image(self):
        """Get the previous image in the same collection (ordered by ID)"""
        return (
            Image.objects.filter(
                collection=self.collection,
                id__lt=self.id,
            )
            .order_by("-id")
            .first()
        )

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
    license = models.ForeignKey(
        License,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pre_images",
    )

    creator = models.CharField(
        null=True, max_length=100, help_text="Creator(s) of the work"
    )
    ref = models.CharField(
        null=True, max_length=100, help_text="Source-specific reference"
    )

    original_date = models.CharField(
        null=True, max_length=50, help_text="Date information from source"
    )
    edtf_date = models.CharField(
        null=True, max_length=50, help_text="Date parsed as EDTF"
    )
    source_point = gis_models.PointField(
        null=True,
        blank=True,
        spatial_index=False,
        help_text="Location hint from source metadata (e.g., embedded coordinates from archive)",
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
    confidence_notes_html = models.TextField(
        blank=True,
        editable=False,
        help_text="Cached rendered HTML of confidence_notes",
    )

    def __str__(self):
        by_user = (
            self.georeferenced_by.get_display_name()
            if self.georeferenced_by
            else "Anonymous"
        )
        return f"Georeference for {self.image} by {by_user}"

    def save(self, *args, **kwargs):
        from .utils import render_markdown_safe

        self.confidence_notes_html = render_markdown_safe(self.confidence_notes)
        super().save(*args, **kwargs)

    @property
    def validation_count(self):
        """Number of validations this georeference has received"""
        return self.validations.count()

    def get_validation_counts(self):
        """Get counts for each validation type"""

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


class AerialGeoreference(models.Model):
    """Aerial georeference data for an image - polygon-based submissions"""

    CONFIDENCE_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
    ]

    image = models.ForeignKey(
        Image, on_delete=models.CASCADE, related_name="aerial_georeferences"
    )

    # Coordinate data - polygon instead of point
    polygon = gis_models.PolygonField(spatial_index=True)

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
        related_name="aerial_georeferenced_images",
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
    confidence_notes_html = models.TextField(
        blank=True,
        editable=False,
        help_text="Cached rendered HTML of confidence_notes",
    )

    def __str__(self):
        by_user = (
            self.georeferenced_by.get_display_name()
            if self.georeferenced_by
            else "Anonymous"
        )
        return f"Aerial Georeference for {self.image} by {by_user}"

    def save(self, *args, **kwargs):
        from .utils import render_markdown_safe

        self.confidence_notes_html = render_markdown_safe(self.confidence_notes)
        super().save(*args, **kwargs)

    @property
    def validation_count(self):
        """Number of validations this georeference has received"""
        return self.validations.count()

    def get_validation_counts(self):
        """Get counts for each validation type"""

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


class AerialGeoreferenceValidation(models.Model):
    """Validation of an aerial georeference by other users"""

    VALIDATION_CHOICES = [
        ("correct", "Correct"),
        ("incorrect", "Incorrect"),
        ("uncertain", "Uncertain"),
    ]

    georeference = models.ForeignKey(
        AerialGeoreference, on_delete=models.CASCADE, related_name="validations"
    )
    validated_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="aerial_georeference_validations"
    )
    validation = models.CharField(max_length=10, choices=VALIDATION_CHOICES)
    notes = models.TextField(blank=True, help_text="Optional validation notes")
    notes_html = models.TextField(
        blank=True,
        editable=False,
        help_text="Cached rendered HTML of notes",
    )
    validated_at = models.DateTimeField(auto_now_add=True)

    @property
    def image(self):
        return self.georeference.image

    def __str__(self):
        return f"{self.validation} validation by {self.validated_by.username}"

    def save(self, *args, **kwargs):
        from .utils import render_markdown_safe

        self.notes_html = render_markdown_safe(self.notes)
        super().save(*args, **kwargs)

    class Meta:
        unique_together = ["georeference", "validated_by"]
        indexes = [
            models.Index(fields=["georeference", "validation"]),
            models.Index(fields=["validated_by"]),
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
    notes_html = models.TextField(
        blank=True,
        editable=False,
        help_text="Cached rendered HTML of notes",
    )
    validated_at = models.DateTimeField(auto_now_add=True)

    @property
    def image(self):
        return self.georeference.image

    def __str__(self):
        return f"{self.validation} validation by {self.validated_by.username}"

    def save(self, *args, **kwargs):
        from .utils import render_markdown_safe

        self.notes_html = render_markdown_safe(self.notes)
        super().save(*args, **kwargs)

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


class SubjectMapping(models.Model):
    """Through model connecting images to subjects with ordering"""

    image = models.ForeignKey(
        Image, on_delete=models.CASCADE, related_name="subject_mappings"
    )
    subject = models.ForeignKey(
        "subjects.Subject", on_delete=models.CASCADE, related_name="image_mappings"
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


class Comment(models.Model):
    """Comments on images"""

    image = models.ForeignKey(Image, on_delete=models.CASCADE, related_name="comments")

    # Content
    text = models.TextField(help_text="Comment text content")
    text_html = models.TextField(
        blank=True,
        editable=False,
        help_text="Cached rendered HTML of text",
    )

    # Tracking information
    commented_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="image_comments",
        help_text="User who made the comment",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        preview = self.text[:50]
        return f"Comment by {self.commented_by.username}: {preview}..."

    def save(self, *args, **kwargs):
        from .utils import render_markdown_safe

        self.text_html = render_markdown_safe(self.text)
        super().save(*args, **kwargs)

    class Meta:
        ordering = ["image", "-created_at"]
        indexes = [
            models.Index(fields=["image"]),
            models.Index(fields=["commented_by"]),
            models.Index(fields=["-created_at"]),
        ]


class ImageRating(models.Model):
    """Rating of an image by a user (1-10 scale)"""

    image = models.ForeignKey(Image, on_delete=models.CASCADE, related_name="ratings")
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="image_ratings"
    )
    rating = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Rating from 1-10",
    )
    rated_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} rated {self.image} as {self.rating}/10"

    class Meta:
        unique_together = ["image", "user"]
        indexes = [
            models.Index(fields=["image"]),
            models.Index(fields=["user"]),
        ]


@receiver([post_save, post_delete], sender=ImageSkip)
def update_skip_count(sender, instance, **kwargs):
    """Update the skip_count on Image when ImageSkip is created/deleted"""
    instance.image.skip_count = instance.image.skips.count()
    instance.image.save(update_fields=["skip_count"])


# =============================================================================
# Signals to keep Image.is_searchable synchronized
# =============================================================================


def _compute_is_searchable(image):
    """Compute whether an image should be searchable."""
    return (
        image.collection.public
        and image.collection.source.public
        and image.duplicate_of_id is None
    )


@receiver(post_save, sender=Source)
def update_searchable_on_source_change(sender, instance, **kwargs):
    """When a Source's public status changes, update all images in its collections."""
    from django.db import connection

    # Use raw SQL because Django's update() doesn't allow joined field references
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE images_image
            SET is_searchable = (
                %s = true
                AND EXISTS (
                    SELECT 1 FROM images_collection c
                    WHERE c.id = images_image.collection_id AND c.public = true
                )
                AND images_image.duplicate_of_id IS NULL
            )
            WHERE collection_id IN (
                SELECT id FROM images_collection WHERE source_id = %s
            )
            """,
            [instance.public, instance.id],
        )


@receiver(post_save, sender=Collection)
def update_searchable_on_collection_change(sender, instance, **kwargs):
    """When a Collection's public status changes, update all its images."""
    is_public = instance.public and instance.source.public
    # This works because we're not referencing joined fields in the update value
    Image.objects.filter(collection=instance, duplicate_of__isnull=True).update(
        is_searchable=is_public
    )
    Image.objects.filter(collection=instance, duplicate_of__isnull=False).update(
        is_searchable=False
    )


@receiver(post_save, sender=Image)
def update_searchable_on_image_save(sender, instance, created, **kwargs):
    """Update is_searchable on every Image save to reflect current collection/source visibility."""
    # Compute the correct value
    should_be_searchable = _compute_is_searchable(instance)

    # Only update if the value has changed (avoid infinite recursion)
    if instance.is_searchable != should_be_searchable:
        # Use update() to avoid triggering another signal
        Image.objects.filter(pk=instance.pk).update(is_searchable=should_be_searchable)


class Album(models.Model):
    """User-created collection of images in a specific order"""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="UUID for the album (difficult to guess)",
    )

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="albums")
    title = models.CharField(max_length=500, help_text="Title of the album")
    description = models.TextField(
        blank=True, help_text="Optional description of the album"
    )
    public = models.BooleanField(
        default=False, help_text="Whether this album is visible to other users"
    )
    map_mode = models.BooleanField(
        default=False, help_text="Whether to display map, georeferencing buttons"
    )
    images = models.ManyToManyField(
        Image,
        through="AlbumImage",
        related_name="albums",
        help_text="Images in this album",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} by {self.owner.get_display_name()}"

    def get_absolute_url(self):
        display_name = (
            self.owner.get_display_name()
            if hasattr(self.owner, "get_display_name")
            else self.owner.username
        )
        return reverse(
            "images:album_detail",
            kwargs={"display_name": display_name, "album_id": self.id},
        )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "public"]),
            models.Index(fields=["owner"]),
        ]


class AlbumImage(models.Model):
    """Through model for albums to maintain image ordering"""

    album = models.ForeignKey(
        Album, on_delete=models.CASCADE, related_name="album_images"
    )
    image = models.ForeignKey(
        Image, on_delete=models.CASCADE, related_name="album_references"
    )
    order = models.PositiveIntegerField(
        default=0, help_text="Display order in the album (lower numbers first)"
    )
    added_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.album.title} - {self.image.title}"

    class Meta:
        unique_together = ["album", "image"]
        ordering = ["album", "order"]
        indexes = [
            models.Index(fields=["album", "order"]),
            models.Index(fields=["image"]),
        ]


class TopRatedImageView(models.Model):
    """
    A model representing the images_top_rated_view database view.
    This view stores image ratings and statistics for displaying top rated images.
    """

    image_id = models.IntegerField(primary_key=True)
    avg_rating = models.FloatField()
    vote_count = models.IntegerField()
    sort_value = models.FloatField()

    class Meta:
        managed = False
        db_table = "images_top_rated_view"
