import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.urls import reverse

from subjects.models import Address, Business, Occupation, Person


class OCRModel(models.Model):
    """
    An LLM model, with an OpenRouter identifier, to be used in the OCR pipeline.
    """

    name = models.CharField(max_length=255)
    identifier = models.CharField(max_length=255, unique=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class Directory(models.Model):
    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    ocr_prompt = models.TextField(
        blank=True,
        help_text="Cached LLM prompt to alongside page images for OCR extraction",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]
        verbose_name_plural = "directories"

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("directories:directory_edit", kwargs={"slug": self.slug})


class Page(models.Model):
    class TileStatus(models.TextChoices):
        PENDING = "pending"
        PROCESSING = "processing"
        COMPLETE = "complete"
        FAILED = "failed"

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    directory = models.ForeignKey(
        Directory,
        on_delete=models.CASCADE,
        related_name="pages",
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Display order within the directory (lower numbers first)",
    )
    image_url = models.URLField(max_length=500, blank=True)
    original_filename = models.CharField(max_length=255, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    tile_status = models.CharField(
        max_length=20,
        choices=TileStatus.choices,
        blank=True,
        default="",
    )
    tile_error = models.TextField(blank=True)
    ocr_status = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Status of OCR processing",
    )
    ocr_error = models.TextField(blank=True)
    ocr_raw = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["directory", "order"]
        indexes = [
            models.Index(fields=["directory", "order"]),
        ]

    def __str__(self):
        return f"{self.directory.title} - page {self.order + 1}"


class Entry(models.Model):
    """A single entry in a directory"""

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    page = models.ForeignKey(
        Page,
        on_delete=models.CASCADE,
        related_name="entries",
    )
    original_text = models.TextField(blank=True)
    x = models.IntegerField(null=True, blank=True)
    y = models.IntegerField(null=True, blank=True)
    w = models.IntegerField(null=True, blank=True)
    h = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "entries"

    def __str__(self):
        return f"Entry {self.pk} in {self.page}"


class EntryHistory(models.Model):
    """Audit log for changes to an Entry."""

    class Action(models.TextChoices):
        OCR_CREATED = "ocr_created", "Created by OCR"
        APPROVED = "approved", "Approved"
        EDITED = "edited", "Edited"

    entry = models.ForeignKey(
        Entry,
        on_delete=models.CASCADE,
        related_name="history",
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    snapshot = models.JSONField(
        help_text="Snapshot of entry fields at the time of this action",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name_plural = "entry histories"

    def __str__(self):
        who = self.user.username if self.user else "system"
        return f"{self.get_action_display()} by {who} at {self.created_at}"


class EntryComment(models.Model):
    """User comment on an Entry."""

    entry = models.ForeignKey(
        Entry,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        who = self.user.username if self.user else "anonymous"
        return f"Comment by {who} on Entry {self.entry_id}"


class LinkMethod(models.TextChoices):
    OCR = "ocr", "Created by OCR"
    AUTO = "auto", "Auto-matched"
    USER = "user", "User-linked"


class EntryPersonLink(models.Model):
    entry = models.ForeignKey(
        Entry, on_delete=models.CASCADE, related_name="person_links"
    )
    person = models.ForeignKey(
        Person, on_delete=models.CASCADE, related_name="entry_links"
    )
    method = models.CharField(
        max_length=10, choices=LinkMethod.choices, default=LinkMethod.OCR
    )
    confidence = models.FloatField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("entry", "person")]

    def __str__(self):
        return f"Entry {self.entry_id} ↔ {self.person}"


class EntryAddressLink(models.Model):
    entry = models.ForeignKey(
        Entry, on_delete=models.CASCADE, related_name="address_links"
    )
    address = models.ForeignKey(
        Address, on_delete=models.CASCADE, related_name="entry_links"
    )
    method = models.CharField(
        max_length=10, choices=LinkMethod.choices, default=LinkMethod.OCR
    )
    confidence = models.FloatField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("entry", "address")]

    def __str__(self):
        return f"Entry {self.entry_id} ↔ {self.address}"


class EntryBusinessLink(models.Model):
    entry = models.ForeignKey(
        Entry, on_delete=models.CASCADE, related_name="business_links"
    )
    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="entry_links"
    )
    method = models.CharField(
        max_length=10, choices=LinkMethod.choices, default=LinkMethod.OCR
    )
    confidence = models.FloatField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("entry", "business")]

    def __str__(self):
        return f"Entry {self.entry_id} ↔ {self.business}"


class EntryOccupationLink(models.Model):
    entry = models.ForeignKey(
        Entry, on_delete=models.CASCADE, related_name="occupation_links"
    )
    occupation = models.ForeignKey(
        Occupation, on_delete=models.CASCADE, related_name="entry_links"
    )
    method = models.CharField(
        max_length=10, choices=LinkMethod.choices, default=LinkMethod.OCR
    )
    confidence = models.FloatField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("entry", "occupation")]

    def __str__(self):
        return f"Entry {self.entry_id} ↔ {self.occupation}"


class LinkValidation(models.Model):
    """Crowdsourced validation of any entry link."""

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    link = GenericForeignKey("content_type", "object_id")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    agrees = models.BooleanField(help_text="Whether the user agrees with this link")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("content_type", "object_id", "user")]
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self):
        vote = "agrees" if self.agrees else "disagrees"
        who = self.user.username if self.user else "anonymous"
        return f"{who} {vote} with {self.content_type.model} #{self.object_id}"
