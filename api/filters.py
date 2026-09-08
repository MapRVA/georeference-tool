from django.db.models import Q
from django_filters import rest_framework as filters
from rest_framework.exceptions import ValidationError

from images.models import (
    AerialGeoreference,
    Collection,
    Georeference,
    Image,
    Source,
)
from subjects.models import Subject


class NumberInFilter(filters.BaseInFilter, filters.NumberFilter):
    pass


class CharInFilter(filters.BaseInFilter, filters.CharFilter):
    pass


def _filter_georeferenced_by(queryset, name, value):
    raw_values = str(value).split(",")

    usernames = []
    for v in raw_values:
        try:
            osm_id = int(v.strip())
        except (ValueError, TypeError):
            raise ValidationError(
                {"georeferenced_by": "Must be integers (OSM user IDs) separated by commas."}
            )

        if osm_id == 0:
            usernames.append("hardcoded_admin")
        else:
            usernames.append(f"osm_{osm_id}")

    return queryset.filter(georeferenced_by__username__in=usernames)


class SourceFilter(filters.FilterSet):
    slug = CharInFilter(field_name="slug", lookup_expr="in")

    class Meta:
        model = Source
        fields = ["slug"]


class CollectionFilter(filters.FilterSet):
    source = NumberInFilter(field_name="source_id", lookup_expr="in")
    slug = CharInFilter(field_name="slug", lookup_expr="in")

    class Meta:
        model = Collection
        fields = ["source", "slug"]


class SubjectFilter(filters.FilterSet):
    slug = CharInFilter(field_name="slug", lookup_expr="in")

    class Meta:
        model = Subject
        fields = ["slug"]


class ImageFilter(filters.FilterSet):
    source = NumberInFilter(field_name="collection__source_id", lookup_expr="in")
    collection = NumberInFilter(field_name="collection_id", lookup_expr="in")
    subject = NumberInFilter(method="filter_by_subject")
    creator = CharInFilter(field_name="creator", lookup_expr="in")

    # Temporal filters: year-based ranges against the decimal date fields
    year_min = filters.NumberFilter(
        field_name="fuzzy_end_decdate",
        lookup_expr="gte",
        help_text="Minimum year (includes images that may extend into this year)",
    )
    year_max = filters.NumberFilter(
        field_name="fuzzy_start_decdate",
        lookup_expr="lte",
        help_text="Maximum year (includes images that may start before this year)",
    )

    # Georeferencing status
    georeferenced = filters.BooleanFilter(method="filter_georeferenced")

    # From-above images (aerial/bird's-eye)
    from_above = filters.BooleanFilter(field_name="aerial")

    class Meta:
        model = Image
        fields = []

    def filter_by_subject(self, queryset, name, value):
        return queryset.filter(subject_mappings__subject_id__in=value)

    def filter_georeferenced(self, queryset, name, value):
        has_point = Q(aerial=False, georeferences__isnull=False)
        has_aerial = Q(aerial=True, aerial_georeferences__isnull=False)
        if value:
            return queryset.filter(has_point | has_aerial).distinct()
        return queryset.exclude(has_point | has_aerial)


class GeoreferenceFilter(filters.FilterSet):
    image = NumberInFilter(field_name="image_id", lookup_expr="in")
    source = NumberInFilter(field_name="image__collection__source_id", lookup_expr="in")
    collection = NumberInFilter(field_name="image__collection_id", lookup_expr="in")
    subject = NumberInFilter(field_name="image__subject_mappings__subject_id", lookup_expr="in")
    confidence = filters.ChoiceFilter(
        choices=Georeference.CONFIDENCE_CHOICES,
    )
    from_above = filters.BooleanFilter(field_name="image__aerial")
    georeferenced_by = filters.NumberFilter(method=_filter_georeferenced_by)
    year_min = filters.NumberFilter(
        field_name="image__fuzzy_end_decdate",
        lookup_expr="gte",
    )
    year_max = filters.NumberFilter(
        field_name="image__fuzzy_start_decdate",
        lookup_expr="lte",
    )

    class Meta:
        model = Georeference
        fields = []


class FromAboveGeoreferenceFilter(filters.FilterSet):
    image = NumberInFilter(field_name="image_id", lookup_expr="in")
    source = NumberInFilter(field_name="image__collection__source_id", lookup_expr="in")
    collection = NumberInFilter(field_name="image__collection_id", lookup_expr="in")
    subject = NumberInFilter(field_name="image__subject_mappings__subject_id", lookup_expr="in")
    confidence = filters.ChoiceFilter(
        choices=AerialGeoreference.CONFIDENCE_CHOICES,
    )
    georeferenced_by = filters.NumberFilter(method=_filter_georeferenced_by)
    year_min = filters.NumberFilter(
        field_name="image__fuzzy_end_decdate",
        lookup_expr="gte",
    )
    year_max = filters.NumberFilter(
        field_name="image__fuzzy_start_decdate",
        lookup_expr="lte",
    )

    class Meta:
        model = AerialGeoreference
        fields = []