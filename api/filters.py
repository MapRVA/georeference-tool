from django_filters import rest_framework as filters
from rest_framework.exceptions import ValidationError

from images.models import AerialGeoreference, Georeference, Image


def _filter_georeferenced_by(queryset, name, value):
    try:
        osm_id = int(value)
    except (ValueError, TypeError):
        raise ValidationError({"georeferenced_by": "Must be an integer (OSM user ID)."})
    if osm_id == 0:
        username = "hardcoded_admin"
    else:
        username = f"osm_{osm_id}"
    return queryset.filter(georeferenced_by__username=username)


class ImageFilter(filters.FilterSet):
    source = filters.NumberFilter(field_name="collection__source_id")
    collection = filters.NumberFilter(field_name="collection_id")
    subject = filters.NumberFilter(method="filter_by_subject")
    creator = filters.CharFilter(lookup_expr="icontains")

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
        return queryset.filter(subject_mappings__subject_id=value)

    def filter_georeferenced(self, queryset, name, value):
        if value:
            return queryset.filter(georeferences__isnull=False).distinct()
        return queryset.filter(georeferences__isnull=True)


class GeoreferenceFilter(filters.FilterSet):
    image = filters.NumberFilter(field_name="image_id")
    source = filters.NumberFilter(field_name="image__collection__source_id")
    collection = filters.NumberFilter(field_name="image__collection_id")
    subject = filters.NumberFilter(field_name="image__subject_mappings__subject_id")
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
    image = filters.NumberFilter(field_name="image_id")
    source = filters.NumberFilter(field_name="image__collection__source_id")
    collection = filters.NumberFilter(field_name="image__collection_id")
    subject = filters.NumberFilter(field_name="image__subject_mappings__subject_id")
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
