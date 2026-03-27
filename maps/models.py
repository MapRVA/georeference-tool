from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class LayerCollection(models.Model):
    """Collection of map layers that can be toggled together"""

    name = models.CharField(
        max_length=200, help_text="Display name for this collection"
    )
    slug = models.SlugField(unique=True)

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

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("maps:browse_maps")

    class Meta:
        ordering = ["order", "name"]


class MapLayer(models.Model):
    """Individual map layer with pmtiles URL and metadata"""

    TYPE_CHOICES = [
        ("pmtiles", "PMTiles"),
        ("xyz", "XYZ Tiles"),
    ]

    name = models.CharField(max_length=200, help_text="Display name for this layer")
    slug = models.SlugField(help_text="URL-friendly identifier for this layer")

    type = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
        default="pmtiles",
        help_text="Type of map layer (PMTiles or XYZ)",
    )
    url = models.URLField(
        help_text="URL to the tile source (PMTiles file or XYZ endpoint)"
    )
    source_link = models.URLField(
        blank=True, help_text="Optional URL to the source of this map layer"
    )
    iiif_link = models.URLField(
        blank=True, help_text="Optional URL to the IIIF manifest"
    )
    oim_link = models.URLField(
        blank=True, help_text="Optional URL to the OIM (OldInsuranceMaps.net) entry"
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

    def get_absolute_url(self):
        return reverse(
            "maps:layer_detail",
            kwargs={"collection_slug": self.collection.slug, "layer_slug": self.slug},
        )

    class Meta:
        ordering = ["collection__order", "collection__name", "order", "name"]
        unique_together = ["collection", "slug"]
