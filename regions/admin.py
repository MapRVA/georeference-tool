import requests
from django import forms
from django.contrib import admin
from django.utils.html import format_html

from subjects.models import WikidataItem
from subjects.sparql_safety import UnsafeSparqlInput, validate_qid

from .models import Region
from .wikidata_check import ALLOWED_ROOT_CLASSES, check_region_class


class RegionAdminForm(forms.ModelForm):
    """Create/edit a Region from a Wikidata Q-ID.

    The admin types a Q-ID rather than picking an existing
    ``WikidataItem`` — the item usually doesn't exist yet. Validation
    runs a synchronous WDQS ASK (see ``regions.wikidata_check``) so the
    admin learns immediately whether the entity qualifies; the row is
    then created or reused on save.
    """

    wikidata_id = forms.CharField(
        label="Wikidata Q-ID",
        max_length=20,
        help_text="e.g. Q43421. Verified against Wikidata when you save.",
    )

    class Meta:
        model = Region
        fields = ["title", "slug"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Blank title falls back to the Wikidata item's label on save.
        self.fields["title"].required = False
        if self.instance.pk:
            self.fields["wikidata_id"].initial = self.instance.wikidata_item.wikidata_id

    def clean_wikidata_id(self):
        qid = self.cleaned_data["wikidata_id"].strip().upper()
        try:
            validate_qid(qid)
        except UnsafeSparqlInput:
            raise forms.ValidationError("Enter a Wikidata Q-ID like Q43421.")

        clash = Region.objects.filter(wikidata_item__wikidata_id=qid)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        existing = clash.first()
        if existing is not None:
            raise forms.ValidationError(
                f"{qid} is already linked to region “{existing.title}”."
            )

        # Editing without changing the Q-ID skips the WDQS round trip.
        if self.instance.pk and qid == self.instance.wikidata_item.wikidata_id:
            return qid

        try:
            eligible = check_region_class(qid)
        except requests.RequestException:
            raise forms.ValidationError(
                "Could not reach the Wikidata Query Service to verify this "
                "item. Nothing was saved — please try again in a moment."
            )
        if not eligible:
            item = WikidataItem.objects.filter(wikidata_id=qid).first()
            label = f" ({item.title})" if item else ""
            roots = ", ".join(ALLOWED_ROOT_CLASSES)
            raise forms.ValidationError(
                f"{qid}{label} is not a territory or human settlement on "
                f"Wikidata (no instance-of/subclass-of path to any of: "
                f"{roots})."
            )
        return qid

    def save(self, commit=True):
        region = super().save(commit=False)
        qid = self.cleaned_data["wikidata_id"]
        item = WikidataItem.objects.filter(wikidata_id=qid).first()
        if item is None:
            item = WikidataItem(wikidata_id=qid)
            # Synchronous entity-JSON fetch; queues closure hydration
            # post-commit, which will see the Region row saved below and
            # use the P131 query variant.
            item.save()
        region.wikidata_item = item
        if not region.title:
            region.title = item.title
        if commit:
            region.save()
        return region


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    form = RegionAdminForm
    prepopulated_fields = {"slug": ("title",)}
    list_display = (
        "title",
        "slug",
        "wikidata_item_link",
        "ancestor_count",
        "created_at",
    )
    search_fields = (
        "title",
        "slug",
        "wikidata_item__wikidata_id",
        "wikidata_item__title",
    )
    readonly_fields = ("created_at", "updated_at")

    def wikidata_item_link(self, obj):
        if obj.wikidata_item:
            return format_html(
                '<a href="{}" target="_blank">{}</a>',
                obj.wikidata_item.wikidata_url,
                obj.wikidata_item.wikidata_id,
            )
        return "None"

    wikidata_item_link.short_description = "Wikidata"

    def ancestor_count(self, obj):
        return obj.ancestors.count()

    ancestor_count.short_description = "Ancestors"
