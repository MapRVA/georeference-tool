import datetime
import uuid

from django.contrib.admin.utils import quote
from django.contrib.auth.models import User
from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.fields import ArrayField
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import connection, models, transaction
from django.db.models import Count, F, Q
from django.db.models.functions import Lower

from .utils import render_markdown_safe

# Conditionally import SearchVectorField only if using PostgreSQL
try:
    from django.contrib.postgres.search import SearchVectorField

    HAS_POSTGRES_SEARCH = True
except ImportError:
    HAS_POSTGRES_SEARCH = False
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
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
    default_search_bbox_west = models.FloatField(
        default=-77.61976,
        help_text="Westernmost longitude for the default search bounding box (used by the geocoder and other location filters)",
    )
    default_search_bbox_south = models.FloatField(
        default=37.44393,
        help_text="Southernmost latitude for the default search bounding box",
    )
    default_search_bbox_east = models.FloatField(
        default=-77.36673,
        help_text="Easternmost longitude for the default search bounding box",
    )
    default_search_bbox_north = models.FloatField(
        default=37.60954,
        help_text="Northernmost latitude for the default search bounding box",
    )
    default_subject_bbox_west = models.FloatField(
        default=-84.72,
        help_text="Westernmost longitude for the default subject bounding box (used when refreshing OSM metadata for subjects)",
    )
    default_subject_bbox_south = models.FloatField(
        default=35.90,
        help_text="Southernmost latitude for the default subject bounding box",
    )
    default_subject_bbox_east = models.FloatField(
        default=-74.97,
        help_text="Easternmost longitude for the default subject bounding box",
    )
    default_subject_bbox_north = models.FloatField(
        default=39.71,
        help_text="Northernmost latitude for the default subject bounding box",
    )
    home_feed_item_count = models.PositiveSmallIntegerField(
        default=5,
        help_text="Number of recent activity items to show in the homepage feed embed",
    )
    home_feed_show_georeferences = models.BooleanField(
        default=True,
        help_text="Show georeference activity in the homepage feed embed",
    )
    home_feed_show_comments = models.BooleanField(
        default=True,
        help_text="Show comments in the homepage feed embed",
    )
    home_feed_show_user_milestones = models.BooleanField(
        default=True,
        help_text="Show user milestones in the homepage feed embed",
    )
    home_feed_show_site_milestones = models.BooleanField(
        default=True,
        help_text="Show sitewide milestones in the homepage feed embed",
    )
    home_feed_show_validations = models.BooleanField(
        default=False,
        help_text="Show georeference validations in the homepage feed embed",
    )
    home_feed_show_subjects = models.BooleanField(
        default=False,
        help_text="Show subject mapping activity in the homepage feed embed",
    )
    home_feed_show_new_subjects = models.BooleanField(
        default=True,
        help_text="Show new subject introductions in the homepage feed embed",
    )
    home_feed_show_new_collections = models.BooleanField(
        default=True,
        help_text="Show new collection announcements in the homepage feed embed",
    )

    class Meta:
        verbose_name = "Site Settings"
        verbose_name_plural = "Site Settings"

    def __str__(self):
        return "Site Settings"

    @property
    def home_feed_event_types(self):
        """Set of activity event-type keys enabled for the homepage feed embed."""
        enabled = {
            "group": self.home_feed_show_georeferences,
            "comment": self.home_feed_show_comments,
            "milestone": self.home_feed_show_user_milestones,
            "sitewide": self.home_feed_show_site_milestones,
            "validation": self.home_feed_show_validations,
            "subject": self.home_feed_show_subjects,
            "new_subject": self.home_feed_show_new_subjects,
            "new_collection": self.home_feed_show_new_collections,
        }
        return {key for key, on in enabled.items() if on}

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


class CollectionStats(models.Model):
    """Denormalized per-collection image statistics.

    Maintained eagerly by signal handlers whenever images or georeferences
    change (see signals.py), so browse pages can read counts without running
    aggregate queries. A periodic reconcile task self-heals any drift from
    write paths that bypass signals (bulk updates, raw SQL). Concurrent
    refreshes resolve by snapshot age, not write order: updated_at carries
    each refresh's snapshot time, and the upsert only overwrites rows computed
    from an older snapshot, so a slow stale refresh — or the full reconcile
    running alongside a live one — can never clobber fresher counts.

    An image counts as georeferenced if it is a non-aerial with a point
    georeference, or an aerial with a polygon georeference (matching
    Image.is_georeferenced). An aerial with only a point georeference does NOT
    count — it stays available. An image marked will_not_georef counts only
    as will_not_georef, even if it also has georeferences (matching
    Image.georeference_status precedence). The confidence bucket comes from
    the most recent qualifying georeference: the latest aerial georeference
    for aerials, the latest point georeference for non-aerials. Counts include
    non-public collections and sources — visibility is filtered at read time,
    so publishing a collection is reflected immediately without a recompute.
    """

    collection = models.OneToOneField(
        Collection, on_delete=models.CASCADE, primary_key=True, related_name="stats"
    )
    total_images = models.PositiveIntegerField(default=0)
    will_not_georef_images = models.PositiveIntegerField(default=0)
    georeferenced_low = models.PositiveIntegerField(default=0)
    georeferenced_medium = models.PositiveIntegerField(default=0)
    georeferenced_high = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "collection stats"

    def __str__(self):
        return f"Stats for {self.collection}"

    @property
    def georeferenced_images(self):
        return (
            self.georeferenced_low + self.georeferenced_medium + self.georeferenced_high
        )

    @property
    def pending_images(self):
        return (
            self.total_images - self.georeferenced_images - self.will_not_georef_images
        )

    REFRESH_SQL = """
    INSERT INTO images_collectionstats (
        collection_id, total_images, will_not_georef_images,
        georeferenced_low, georeferenced_medium, georeferenced_high, updated_at
    )
    SELECT
        c.id,
        COUNT(img.id),
        COUNT(img.id) FILTER (WHERE img.will_not_georef),
        COUNT(img.id) FILTER (WHERE NOT img.will_not_georef AND conf.confidence = 'low'),
        COUNT(img.id) FILTER (WHERE NOT img.will_not_georef AND conf.confidence = 'medium'),
        COUNT(img.id) FILTER (WHERE NOT img.will_not_georef AND conf.confidence = 'high'),
        -- statement start time == this statement's snapshot time (READ
        -- COMMITTED); NOW() would freeze for a whole transaction, breaking
        -- the freshness guard below under TestCase's wrapping transaction
        STATEMENT_TIMESTAMP()
    FROM images_collection c
    LEFT JOIN images_image img
        ON img.collection_id = c.id AND img.duplicate_of_id IS NULL
    LEFT JOIN LATERAL (
        SELECT CASE WHEN img.aerial THEN (
            SELECT ag.confidence FROM images_aerialgeoreference ag
            WHERE ag.image_id = img.id
            ORDER BY ag.georeferenced_at DESC LIMIT 1
        ) ELSE (
            SELECT g.confidence FROM images_georeference g
            WHERE g.image_id = img.id
            ORDER BY g.georeferenced_at DESC LIMIT 1
        ) END AS confidence
    ) conf ON TRUE
    {where_clause}
    GROUP BY c.id
    ON CONFLICT (collection_id) DO UPDATE SET
        total_images = EXCLUDED.total_images,
        will_not_georef_images = EXCLUDED.will_not_georef_images,
        georeferenced_low = EXCLUDED.georeferenced_low,
        georeferenced_medium = EXCLUDED.georeferenced_medium,
        georeferenced_high = EXCLUDED.georeferenced_high,
        updated_at = EXCLUDED.updated_at
    -- Freshest snapshot wins: a refresh computed from an older snapshot must
    -- not overwrite counts computed from a newer one, regardless of which
    -- write lands last
    WHERE images_collectionstats.updated_at < EXCLUDED.updated_at
    """

    @classmethod
    def refresh_for(cls, collection_ids=None):
        """Recompute stats rows in a single upsert query.

        Pass a list of collection ids to refresh just those collections, or
        None to refresh every collection (reconcile).
        """
        if collection_ids is not None and not collection_ids:
            return
        with connection.cursor() as cursor:
            if collection_ids is None:
                cursor.execute(cls.REFRESH_SQL.format(where_clause=""))
            else:
                cursor.execute(
                    cls.REFRESH_SQL.format(where_clause="WHERE c.id = ANY(%s)"),
                    [list(collection_ids)],
                )


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
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                name="unique_license_name_ci",
            ),
        ]


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
                parsed = parse_edtf(self.edtf_date)
            except EDTFParseException as e:
                raise ValidationError({"edtf_date": f"Invalid EDTF format: {str(e)}"})
            if isinstance(parsed.lower_strict(), float) or isinstance(
                parsed.upper_strict(), float
            ):
                raise ValidationError(
                    {
                        "edtf_date": (
                            f'EDTF date "{self.edtf_date}" is open-ended; both '
                            "a start and end date are required."
                        )
                    }
                )

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
            except EDTFParseException as e:
                raise ValidationError(f'Invalid EDTF date "{self.edtf_date}": {str(e)}')
            lower = edtf_date.lower_strict()
            upper = edtf_date.upper_strict()
            if isinstance(lower, float) or isinstance(upper, float):
                raise ValidationError(
                    f'EDTF date "{self.edtf_date}" is open-ended; both a start '
                    "and end date are required."
                )
            self.start_decdate = lower[0]
            self.fuzzy_start_decdate = edtf_date.lower_fuzzy()[0]
            self.end_decdate = upper[0]
            self.fuzzy_end_decdate = edtf_date.upper_fuzzy()[0]
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
                    self.tile_status = ""
                    self.tile_error = ""
                    self.iiif_url = None
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

    # IIIF tile fields
    tile_status = models.CharField(max_length=20, blank=True, default="")
    tile_error = models.TextField(blank=True)
    iiif_url = models.URLField(
        null=True,
        blank=True,
        help_text="Base URL for the IIIF Image Service (set when tiles are generated)",
    )
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    asset_generation = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Incremented each time generated assets (transformed image, "
            "thumbnail, IIIF tiles) are regenerated; used as a path "
            "segment to bypass CDN caching."
        ),
    )

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


class ImportSlot(models.Model):
    """Temporary slot for an image upload in progress.

    Tracks a presigned S3 key that a client is authorized to upload to.
    Once the upload is confirmed and metadata is provided, the image is
    copied to its permanent location and a real Image row is created.
    """

    slot_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    collection = models.ForeignKey(
        Collection, on_delete=models.CASCADE, related_name="import_slots"
    )
    created_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="import_slots"
    )
    s3_key = models.CharField(max_length=500)
    content_type = models.CharField(max_length=100, default="image/jpeg")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"ImportSlot {self.slot_id} ({self.s3_key})"


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


SUBJECT_MAPPING_ACTION_ADDED = "added"
SUBJECT_MAPPING_ACTION_REMOVED = "removed"
SUBJECT_MAPPING_ACTION_REORDERED = "reordered"
SUBJECT_MAPPING_ACTION_CHOICES = [
    (SUBJECT_MAPPING_ACTION_ADDED, "Added"),
    (SUBJECT_MAPPING_ACTION_REMOVED, "Removed"),
    (SUBJECT_MAPPING_ACTION_REORDERED, "Reordered"),
]


class SubjectMappingActivity(models.Model):
    """Audit log of subject changes (additions, removals, reorders) on images."""

    ACTION_ADDED = SUBJECT_MAPPING_ACTION_ADDED
    ACTION_REMOVED = SUBJECT_MAPPING_ACTION_REMOVED
    ACTION_REORDERED = SUBJECT_MAPPING_ACTION_REORDERED
    ACTION_CHOICES = SUBJECT_MAPPING_ACTION_CHOICES

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="subject_mapping_activities",
        help_text="User who made the change",
    )
    image = models.ForeignKey(
        Image,
        on_delete=models.CASCADE,
        related_name="subject_mapping_activities",
    )
    subject = models.ForeignKey(
        "subjects.Subject",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mapping_activities",
        help_text="Subject added or removed (null for reorder activities)",
    )
    action = models.CharField(max_length=20, choices=SUBJECT_MAPPING_ACTION_CHOICES)
    previous_order = models.JSONField(
        null=True,
        blank=True,
        help_text="List of subject IDs in their order before a reorder (reorder only)",
    )
    new_order = models.JSONField(
        null=True,
        blank=True,
        help_text="List of subject IDs in their order after a reorder (reorder only)",
    )
    group = models.ForeignKey(
        "activity.SubjectMappingActivityGroup",
        on_delete=models.CASCADE,
        related_name="members",
        null=True,
        blank=True,
        help_text="The activity group this activity belongs to",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"{self.user} {self.action} on image {self.image_id}"

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["image", "-created_at"]),
            models.Index(fields=["user", "-created_at"]),
        ]


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
        return reverse(
            "images:album_detail",
            kwargs={"album_id": self.id},
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


class ImageOfTheDay(models.Model):
    """Queues an Image to be featured on one specific calendar day.

    The queue is normally a contiguous run of days: an unlocked entry's
    ``day`` is just a function of where it sits in line, so inserting or
    removing an entry re-flows the days of the entries around it.

    A *locked* entry is pinned to its ``day``. It stops participating in the
    flow and its day becomes "claimed" — unlocked entries hop over it when
    they slide, and a direct insert onto a claimed day raises. Locked entries
    are the stationary anchors; unlocked entries are the water flowing around
    them. An entry must be unlocked before its day can change or it can be
    removed from the queue.
    """

    image = models.ForeignKey(
        Image,
        on_delete=models.CASCADE,
        related_name="featured_days",
        help_text="The image to feature. An image may be reused on other days.",
    )
    day = models.DateField(
        help_text="Calendar day (in the site's timezone) this image is featured on"
    )
    locked = models.BooleanField(
        default=False,
        help_text=(
            "When locked, this image is pinned to its day: it will not slide "
            "when the queue is reordered, and its day is claimed until unlocked."
        ),
    )
    note = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        help_text="Optional note about this queue entry",
    )
    note_html = models.TextField(
        blank=True,
        editable=False,
        help_text="Cached rendered HTML of note",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="image_of_the_day_entries",
        help_text="Optional user associated with this queue entry",
    )

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.day:%Y-%m-%d}: {self.image.title}"

    def save(self, *args, **kwargs):
        self.note_html = render_markdown_safe(self.note)
        # note_html is derived from note, so whenever a partial save writes
        # note we must persist the rebuilt note_html alongside it — otherwise
        # the cached HTML silently stays stale in the database.
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "note" in update_fields:
            kwargs["update_fields"] = {*update_fields, "note_html"}
        super().save(*args, **kwargs)

    class Meta:
        ordering = ["day"]
        verbose_name = "Image of the Day"
        verbose_name_plural = "Images of the Day"
        constraints = [
            # One image per day. Deferred so the bulk day-shifts in place()
            # and delete() can transiently overlap and only be validated once,
            # at COMMIT — making the reflow order-independent.
            models.UniqueConstraint(
                fields=["day"],
                name="unique_image_of_the_day",
                deferrable=models.Deferrable.DEFERRED,
            ),
        ]
        indexes = [
            models.Index(fields=["locked"]),
        ]

    # -- Day arithmetic -----------------------------------------------------

    @staticmethod
    def _next_free_day(after, locked_days):
        """The first day strictly after ``after`` not claimed by a lock."""
        candidate = after + datetime.timedelta(days=1)
        while candidate in locked_days:
            candidate += datetime.timedelta(days=1)
        return candidate

    @classmethod
    def next_available_day(cls, start=None):
        """First day >= ``start`` (default: today) with no image queued.

        Used as the default insertion point — appending to the end of the
        queue, or filling the first gap a lock has left open.
        """
        start = start or timezone.localdate()
        taken = set(cls.objects.filter(day__gte=start).values_list("day", flat=True))
        candidate = start
        while candidate in taken:
            candidate += datetime.timedelta(days=1)
        return candidate

    @classmethod
    def for_today(cls):
        """The entry featured today, or None."""
        return cls.objects.filter(day=timezone.localdate()).first()

    @classmethod
    def current_or_most_recent(cls):
        """Today's featured entry, or the most recent past one if none today.

        Used to surface a featured image even on days with nothing queued —
        the most recently featured image stands in until the next one is due.
        """
        return (
            cls.objects.filter(day__lte=timezone.localdate())
            .select_related("image__collection__source")
            .order_by("-day")
            .first()
        )

    # -- Queue operations ---------------------------------------------------

    @classmethod
    def place(cls, image, day=None, locked=False, note=None, user=None):
        """Insert ``image`` into the queue on ``day`` (default: the end).

        Unlocked entries on or after ``day`` ripple forward to the next free
        slot, hopping over days claimed by locked entries, so the queue stays
        contiguous around its anchors. Raises ``ValidationError`` if ``day``
        is already claimed by a locked entry.
        """
        if day is None:
            day = cls.next_available_day()

        locked_days = set(cls.objects.filter(locked=True).values_list("day", flat=True))
        if day in locked_days:
            raise ValidationError(
                f"{day:%Y-%m-%d} is claimed by a locked image; "
                "unlock it to use that day."
            )

        with transaction.atomic():
            displaced = list(
                cls.objects.select_for_update()
                .filter(locked=False, day__gte=day)
                .order_by("day")
            )
            entry = cls.objects.create(
                image=image, day=day, locked=locked, note=note, user=user
            )
            cursor = day
            for moved in displaced:
                cursor = cls._next_free_day(cursor, locked_days)
                moved.day = cursor
                moved.save(update_fields=["day", "updated"])
        return entry

    @classmethod
    def move(cls, entry, new_day, note=None, user=None):
        """Relocate ``entry`` to ``new_day`` and pin it there (locked).

        The entry's current day is vacated — later unlocked entries slide back
        to close the gap — and ``new_day`` is then claimed as a locked anchor,
        rippling any unlocked entries already at or after it. Raises
        ``ValidationError`` if ``new_day`` is claimed by another locked entry.
        Returns the new entry (it is recreated, so its pk changes).
        """
        image = entry.image
        with transaction.atomic():
            # Unlock first so delete() will vacate the slot and slide others
            # back into it; the lock is reapplied when we re-place below.
            if entry.locked:
                cls.objects.filter(pk=entry.pk).update(locked=False)
                entry.locked = False
            entry.delete()
            return cls.place(image, day=new_day, locked=True, note=note, user=user)

    @classmethod
    def _compact(cls):
        """Pack upcoming unlocked entries into the earliest free days, in order.

        Days are assigned from today forward, skipping locked anchors, so any
        gap is closed and the queue stays dense. Past entries are left alone.
        """
        today = timezone.localdate()
        locked_days = set(
            cls.objects.filter(locked=True, day__gte=today).values_list(
                "day", flat=True
            )
        )
        upcoming = list(
            cls.objects.select_for_update()
            .filter(locked=False, day__gte=today)
            .order_by("day")
        )
        cursor = today - datetime.timedelta(days=1)
        for entry in upcoming:
            cursor = cls._next_free_day(cursor, locked_days)
            if entry.day != cursor:
                entry.day = cursor
                entry.save(update_fields=["day", "updated"])

    @classmethod
    def unlock(cls, entry, note=None, user=None):
        """Unlock ``entry`` and slide it to the first open day in the queue.

        Unlocking frees the image from its claimed date, so it rejoins the
        flow and drops into the earliest available day — moving to an earlier
        gap if one exists — with the rest of the upcoming queue compacting
        around it.
        """
        with transaction.atomic():
            entry.note = note
            entry.user = user
            entry.locked = False
            entry.save(update_fields=["note", "user", "locked", "updated"])
            cls._compact()

    def clean(self):
        """A locked entry's day is claimed and may not be changed."""
        super().clean()
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous and previous.locked and previous.day != self.day:
                raise ValidationError(
                    {
                        "day": (
                            "This image is locked to its day. Unlock it "
                            "before moving it to another day."
                        )
                    }
                )

    def delete(self, *args, **kwargs):
        """Remove from the queue, sliding later unlocked entries back.

        Locked entries must be unlocked first. Removing an unlocked entry
        frees its day; every later unlocked entry then slides back to the
        earliest free slot, closing the gap around any locked anchors.
        """
        if self.locked:
            raise ValidationError(
                "This image is locked to its day. Unlock it before "
                "removing it from the queue."
            )

        cls = type(self)
        day = self.day
        with transaction.atomic():
            locked_days = set(
                cls.objects.filter(locked=True).values_list("day", flat=True)
            )
            later = list(
                cls.objects.select_for_update()
                .filter(locked=False, day__gt=day)
                .order_by("day")
            )
            result = super().delete(*args, **kwargs)
            cursor = day - datetime.timedelta(days=1)
            for moved in later:
                cursor = cls._next_free_day(cursor, locked_days)
                if cursor >= moved.day:
                    # Already compact from here on; nothing left to pull back.
                    break
                moved.day = cursor
                moved.save(update_fields=["day", "updated"])
        return result
