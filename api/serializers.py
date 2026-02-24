import json

from django.contrib.auth.models import User

from rest_framework import serializers
from rest_framework_gis.serializers import GeoFeatureModelSerializer

from images.models import (
    AerialGeoreference,
    AerialGeoreferenceValidation,
    Collection,
    Comment,
    Georeference,
    GeoreferenceValidation,
    Image,
    License,
    Source,
)
from subjects.models import OsmElement, Subject, WikidataItem


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def _get_osm_id(user):
    if user.username.startswith("osm_"):
        return int(user.username[4:])
    return 0


class UserSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    username = serializers.CharField(source="get_display_name", read_only=True)
    point_georeferences = serializers.IntegerField(read_only=True)
    from_above_georeferences = serializers.IntegerField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "point_georeferences",
            "from_above_georeferences",
        ]

    def get_id(self, obj):
        return _get_osm_id(obj)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


class SourceSerializer(serializers.ModelSerializer):
    collections_url = serializers.SerializerMethodField()
    collection_count = serializers.IntegerField(read_only=True)
    image_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Source
        fields = [
            "id",
            "name",
            "slug",
            "url",
            "description",
            "collection_count",
            "image_count",
            "collections_url",
        ]

    def get_collections_url(self, obj):
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(f"/api/v2/sources/{obj.id}/collections/")
        return None


class SourceSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Source
        fields = ["id", "name", "slug"]


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


class CollectionSerializer(serializers.ModelSerializer):
    source = SourceSummarySerializer(read_only=True)
    image_count = serializers.IntegerField(read_only=True)
    images_url = serializers.SerializerMethodField()

    class Meta:
        model = Collection
        fields = [
            "id",
            "name",
            "slug",
            "url",
            "description",
            "source",
            "image_count",
            "images_url",
        ]

    def get_images_url(self, obj):
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(
                f"/api/v2/images/?collection={obj.id}"
            )
        return None


class CollectionSummarySerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source="source.name", read_only=True)

    class Meta:
        model = Collection
        fields = ["id", "name", "slug", "source_name"]


# ---------------------------------------------------------------------------
# Licenses, Wikidata, Subjects
# ---------------------------------------------------------------------------


class LicenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = License
        fields = ["display_name", "permalink"]


class WikidataItemSerializer(serializers.ModelSerializer):
    uri = serializers.SerializerMethodField()

    class Meta:
        model = WikidataItem
        fields = ["wikidata_id", "uri", "title", "description"]

    def get_uri(self, obj):
        return f"https://www.wikidata.org/entity/{obj.wikidata_id}"


class SubjectSummarySerializer(serializers.ModelSerializer):
    wikidata = WikidataItemSerializer(source="wikidata_item", read_only=True)

    class Meta:
        model = Subject
        fields = ["id", "title", "slug", "wikidata"]


class SubjectSerializer(serializers.ModelSerializer):
    wikidata = WikidataItemSerializer(source="wikidata_item", read_only=True)
    image_count = serializers.IntegerField(read_only=True)
    images_url = serializers.SerializerMethodField()

    class Meta:
        model = Subject
        fields = [
            "id",
            "title",
            "slug",
            "description",
            "wikidata",
            "image_count",
            "images_url",
        ]

    def get_images_url(self, obj):
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(f"/api/v2/images/?subject={obj.id}")
        return None


class OsmElementGeoSerializer(GeoFeatureModelSerializer):
    """OSM geometry for a subject as a GeoJSON Feature."""

    class Meta:
        model = OsmElement
        geo_field = "geometry"
        fields = ["osm_id"]


# ---------------------------------------------------------------------------
# Validations
# ---------------------------------------------------------------------------


class ValidationSerializer(serializers.ModelSerializer):
    validated_by = serializers.CharField(
        source="validated_by.get_display_name", read_only=True
    )

    class Meta:
        model = GeoreferenceValidation
        fields = ["validation", "validated_by", "notes", "validated_at"]


class FromAboveValidationSerializer(serializers.ModelSerializer):
    validated_by = serializers.CharField(
        source="validated_by.get_display_name", read_only=True
    )

    class Meta:
        model = AerialGeoreferenceValidation
        fields = ["validation", "validated_by", "notes", "validated_at"]


# ---------------------------------------------------------------------------
# Comments — nested in image detail
# ---------------------------------------------------------------------------


class CommentSerializer(serializers.ModelSerializer):
    commented_by = serializers.CharField(
        source="commented_by.get_display_name", read_only=True
    )

    class Meta:
        model = Comment
        fields = ["id", "text", "commented_by", "created_at"]


# ---------------------------------------------------------------------------
# Georeferences (point) — nested in image detail
# ---------------------------------------------------------------------------


class GeoreferenceInlineSerializer(serializers.ModelSerializer):
    """Point georeference as shown within an image detail response."""

    georeferenced_by = serializers.CharField(
        source="georeferenced_by.get_display_name",
        default="Anonymous",
        read_only=True,
    )
    latitude = serializers.FloatField(source="point.y", read_only=True)
    longitude = serializers.FloatField(source="point.x", read_only=True)
    validations = ValidationSerializer(many=True, read_only=True)

    class Meta:
        model = Georeference
        fields = [
            "id",
            "latitude",
            "longitude",
            "direction",
            "confidence",
            "confidence_notes",
            "georeferenced_by",
            "georeferenced_at",
            "validations",
        ]


# ---------------------------------------------------------------------------
# From-above georeferences (polygon) — nested in image detail
# ---------------------------------------------------------------------------


class FromAboveGeoreferenceInlineSerializer(serializers.ModelSerializer):
    """From-above (polygon) georeference as shown within an image detail response."""

    georeferenced_by = serializers.CharField(
        source="georeferenced_by.get_display_name",
        default="Anonymous",
        read_only=True,
    )
    polygon = serializers.SerializerMethodField()
    validations = FromAboveValidationSerializer(many=True, read_only=True)

    class Meta:
        model = AerialGeoreference
        fields = [
            "id",
            "polygon",
            "confidence",
            "confidence_notes",
            "georeferenced_by",
            "georeferenced_at",
            "validations",
        ]

    def get_polygon(self, obj):
        """Return polygon as GeoJSON geometry dict."""
        return json.loads(obj.polygon.geojson)


# ---------------------------------------------------------------------------
# Georeferences — standalone GeoJSON endpoints
# ---------------------------------------------------------------------------


class GeoreferenceGeoSerializer(GeoFeatureModelSerializer):
    """Point georeference as a GeoJSON Feature (for /api/v2/georeferences/)."""

    image_id = serializers.IntegerField(source="image.id", read_only=True)
    image_title = serializers.CharField(source="image.title", read_only=True)
    image_thumbnail = serializers.URLField(
        source="image.thumbnail", read_only=True
    )
    georeferenced_by = serializers.CharField(
        source="georeferenced_by.get_display_name",
        default="Anonymous",
        read_only=True,
    )
    validation_count = serializers.IntegerField(
        source="_validation_count", default=0, read_only=True,
    )

    class Meta:
        model = Georeference
        geo_field = "point"
        fields = [
            "id",
            "image_id",
            "image_title",
            "image_thumbnail",
            "direction",
            "confidence",
            "georeferenced_by",
            "georeferenced_at",
            "validation_count",
        ]


class FromAboveGeoreferenceGeoSerializer(GeoFeatureModelSerializer):
    """From-above georeference as a GeoJSON Feature (for /api/v2/from-above-georeferences/)."""

    image_id = serializers.IntegerField(source="image.id", read_only=True)
    image_title = serializers.CharField(source="image.title", read_only=True)
    image_thumbnail = serializers.URLField(
        source="image.thumbnail", read_only=True
    )
    georeferenced_by = serializers.CharField(
        source="georeferenced_by.get_display_name",
        default="Anonymous",
        read_only=True,
    )
    validation_count = serializers.IntegerField(
        source="_validation_count", default=0, read_only=True,
    )

    class Meta:
        model = AerialGeoreference
        geo_field = "polygon"
        fields = [
            "id",
            "image_id",
            "image_title",
            "image_thumbnail",
            "confidence",
            "georeferenced_by",
            "georeferenced_at",
            "validation_count",
        ]


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

_GEOREF_STATUS_LABELS = {
    "pending": "available",
}


def _get_georeference_status(image):
    # Prefer the annotated value (set on list views) to avoid N+1 queries.
    # Falls back to the model property for detail views with prefetched data.
    status = getattr(image, "_georeference_status", None) or image.georeference_status
    return _GEOREF_STATUS_LABELS.get(status, status)


class ImageSerializer(serializers.ModelSerializer):
    collection = CollectionSummarySerializer(read_only=True)
    license = LicenseSerializer(read_only=True)
    subjects = SubjectSummarySerializer(many=True, read_only=True)
    from_above = serializers.BooleanField(source="aerial", read_only=True)
    georeference_status = serializers.SerializerMethodField()
    date_display = serializers.CharField(read_only=True)
    georeferences = GeoreferenceInlineSerializer(many=True, read_only=True)
    from_above_georeferences = FromAboveGeoreferenceInlineSerializer(
        source="aerial_georeferences", many=True, read_only=True
    )
    comments = CommentSerializer(many=True, read_only=True)
    detail_url = serializers.SerializerMethodField()

    class Meta:
        model = Image
        fields = [
            "id",
            "title",
            "permalink",
            "thumbnail",
            "original_url",
            "description",
            "creator",
            "license",
            "original_date",
            "edtf_date",
            "date_display",
            "collection",
            "subjects",
            "from_above",
            "scale",
            "georeference_status",
            "georeferences",
            "from_above_georeferences",
            "comments",
            "detail_url",
        ]

    def get_georeference_status(self, obj):
        return _get_georeference_status(obj)

    def get_detail_url(self, obj):
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(f"/api/v2/images/{obj.id}/")
        return None


class ImageListSerializer(serializers.ModelSerializer):
    """Lighter serializer for list views — omits nested subjects and description."""

    collection = CollectionSummarySerializer(read_only=True)
    from_above = serializers.BooleanField(source="aerial", read_only=True)
    date_display = serializers.CharField(read_only=True)
    georeference_status = serializers.SerializerMethodField()
    detail_url = serializers.SerializerMethodField()

    class Meta:
        model = Image
        fields = [
            "id",
            "title",
            "thumbnail",
            "creator",
            "original_date",
            "date_display",
            "from_above",
            "collection",
            "georeference_status",
            "detail_url",
        ]

    def get_georeference_status(self, obj):
        return _get_georeference_status(obj)

    def get_detail_url(self, obj):
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(f"/api/v2/images/{obj.id}/")
        return None
