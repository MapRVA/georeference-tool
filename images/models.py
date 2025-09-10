from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils.text import slugify


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
            self.slug = slugify(self.name)
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
    license_permalink = models.URLField(null=True,
        help_text="Link to license information"
    )

    # Flexible date fields - allows partial dates
    year = models.IntegerField(
        null=True,
        validators=[MinValueValidator(1800), MaxValueValidator(2100)],
    )
    month = models.IntegerField(
        null=True, validators=[MinValueValidator(1), MaxValueValidator(12)]
    )
    day = models.IntegerField(
        null=True, validators=[MinValueValidator(1), MaxValueValidator(31)]
    )

    # Georeferencing metadata
    difficulty = models.CharField(
        max_length=10, choices=DIFFICULTY_CHOICES, null=True
    )
    will_not_georef = models.BooleanField(default=False)
    skip_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        if self.title:
            return self.title
        return f"Image {self.id} from {self.collection.name}"

    @property
    def date_display(self):
        """Human readable date representation"""
        parts = []
        if self.year:
            if self.month:
                if self.day:
                    return f"{self.year}-{self.month:02d}-{self.day:02d}"
                else:
                    return f"{self.year}-{self.month:02d}"
            else:
                return str(self.year)
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
        if self.will_not_georef:
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
            models.Index(fields=["year", "month", "day"]),
        ]


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
    latitude = models.FloatField(
        validators=[MinValueValidator(-90.0), MaxValueValidator(90.0)]
    )
    longitude = models.FloatField(
        validators=[MinValueValidator(-180.0), MaxValueValidator(180.0)]
    )
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

    class Meta:
        indexes = [
            models.Index(fields=["image", "georeferenced_by"]),
            models.Index(fields=["latitude", "longitude"]),
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


@receiver([post_save, post_delete], sender=ImageSkip)
def update_skip_count(sender, instance, **kwargs):
    """Update the skip_count on Image when ImageSkip is created/deleted"""
    instance.image.skip_count = instance.image.skips.count()
    instance.image.save(update_fields=["skip_count"])
