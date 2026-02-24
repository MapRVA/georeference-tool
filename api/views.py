import logging
from datetime import datetime

from django.contrib.auth.models import User
from django.db import DatabaseError, connection
from django.db.models import (
    Case,
    CharField,
    Count,
    Exists,
    F,
    Max,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from psycopg import sql
from rest_framework import generics, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response
from rest_framework_gis.filters import InBBoxFilter

from activity.views import get_activity_events
from images.models import (
    AerialGeoreference,
    AerialGeoreferenceValidation,
    Collection,
    Georeference,
    GeoreferenceValidation,
    Image,
    Source,
)
from images.utils import get_confidence_breakdown, get_overall_stats
from images.views.search import CLIP_AVAILABLE, HAS_POSTGRES_SEARCH, _get_text_embedding
from subjects.models import OsmElement, Subject

from .filters import FromAboveGeoreferenceFilter, GeoreferenceFilter, ImageFilter
from .pagination import GeoJsonDefaultPagination
from .serializers import (
    CollectionSerializer,
    FromAboveGeoreferenceGeoSerializer,
    GeoreferenceGeoSerializer,
    ImageListSerializer,
    ImageSerializer,
    OsmElementGeoSerializer,
    SourceSerializer,
    SubjectSerializer,
    UserSerializer,
)


class RemappingOrderingFilter(OrderingFilter):
    """OrderingFilter that remaps API field names to queryset field names.

    Views can set ``ordering_field_map`` to a dict like
    ``{"username": "first_name"}`` and users can order by ``?ordering=username``
    while the actual ``order_by()`` uses ``first_name``.
    """

    def filter_queryset(self, request, queryset, view):
        ordering = self.get_ordering(request, queryset, view)
        field_map = getattr(view, "ordering_field_map", {})
        if ordering:
            def _remap(field):
                if field.startswith("-"):
                    return f"-{field_map.get(field[1:], field[1:])}"
                return field_map.get(field, field)

            ordering = [_remap(f) for f in ordering]
            return queryset.order_by(*ordering)
        return queryset


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    """Contributors who have georeferenced at least one image."""

    serializer_class = UserSerializer
    filter_backends = [RemappingOrderingFilter]
    ordering_fields = ["username", "point_georeferences", "from_above_georeferences"]
    ordering = ["first_name"]
    ordering_field_map = {
        "username": "first_name",
    }

    def get_queryset(self):
        return User.objects.annotate(
            point_georeferences=Count(
                "georeferenced_images",
                filter=Q(georeferenced_images__image__is_searchable=True),
            ),
            from_above_georeferences=Count(
                "aerial_georeferenced_images",
                filter=Q(aerial_georeferenced_images__image__is_searchable=True),
            ),
        ).filter(Q(point_georeferences__gt=0) | Q(from_above_georeferences__gt=0))

    def get_object(self):
        osm_id = self.kwargs[self.lookup_field]
        if str(osm_id) == "0":
            username = "hardcoded_admin"
        else:
            username = f"osm_{osm_id}"
        return generics.get_object_or_404(self.get_queryset(), username=username)


class SourceViewSet(viewsets.ReadOnlyModelViewSet):
    """Archive sources containing collections of historical images."""

    serializer_class = SourceSerializer
    filterset_fields = ["slug"]
    ordering_fields = ["name"]
    ordering = ["name"]

    def get_queryset(self):
        return Source.objects.filter(public=True).annotate(
            collection_count=Count("collections", filter=Q(collections__public=True)),
            image_count=Count(
                "collections__images",
                filter=Q(
                    collections__public=True,
                    collections__images__duplicate_of__isnull=True,
                ),
            ),
        )


class CollectionViewSet(viewsets.ReadOnlyModelViewSet):
    """Collections of historical images within an archive source."""

    serializer_class = CollectionSerializer
    filterset_fields = ["source", "slug"]
    ordering_fields = ["name", "source__name"]
    ordering = ["source__name", "name"]

    def get_queryset(self):
        qs = (
            Collection.objects.filter(public=True, source__public=True)
            .select_related("source")
            .annotate(
                image_count=Count(
                    "images", filter=Q(images__duplicate_of__isnull=True)
                ),
            )
        )

        # Support nested URL: /api/v2/sources/{source_pk}/collections/
        source_pk = self.kwargs.get("source_pk")
        if source_pk is not None:
            qs = qs.filter(source_id=source_pk)

        return qs


class ImageViewSet(viewsets.ReadOnlyModelViewSet):
    """Historical images available for georeferencing."""

    filterset_class = ImageFilter
    ordering_fields = [
        "order",
        "title",
        "original_date",
        "created_at",
        "last_georeferenced_at",
    ]
    ordering = ["-order"]

    def get_serializer_class(self):
        if self.action == "list":
            return ImageListSerializer
        return ImageSerializer

    def get_queryset(self):
        qs = (
            Image.objects.filter(
                is_searchable=True,
            )
            .annotate(
                order=F("id"),
                last_georeferenced_at=Max("georeferences__georeferenced_at"),
            )
            .select_related(
                "collection__source",
                "license",
            )
        )

        if self.action == "list":
            # Annotate georeference_status in SQL to avoid N+1 queries.
            # Mirrors the logic in Image.georeference_status property.
            has_georef = Exists(Georeference.objects.filter(image=OuterRef("pk")))
            has_aerial_georef = Exists(
                AerialGeoreference.objects.filter(image=OuterRef("pk"))
            )
            qs = qs.annotate(
                _georeference_status=Case(
                    When(duplicate_of__isnull=False, then=Value("duplicate")),
                    When(will_not_georef=True, then=Value("will_not_georef")),
                    # Aerial images: georeferenced only with a polygon georef
                    When(
                        Q(aerial=True) & has_aerial_georef, then=Value("georeferenced")
                    ),
                    # Non-aerial images: georeferenced with a point georef
                    When(Q(aerial=False) & has_georef, then=Value("georeferenced")),
                    default=Value("pending"),
                    output_field=CharField(),
                ),
            )
        else:
            # Detail view: prefetch related objects (property is fine here)
            qs = qs.prefetch_related(
                "subjects__wikidata_item",
                "georeferences__georeferenced_by",
                "georeferences__validations__validated_by",
                "aerial_georeferences__georeferenced_by",
                "aerial_georeferences__validations__validated_by",
                "comments__commented_by",
            )

        return qs


class SubjectViewSet(viewsets.ReadOnlyModelViewSet):
    """Subjects (buildings, people, monuments, etc.) that appear in images."""

    serializer_class = SubjectSerializer
    filterset_fields = ["slug"]
    ordering_fields = ["title", "image_count"]
    ordering = ["title"]

    def get_queryset(self):
        return (
            Subject.objects.select_related("wikidata_item")
            .annotate(
                image_count=Count(
                    "image_mappings",
                    filter=Q(image_mappings__image__is_searchable=True),
                ),
            )
            .filter(image_count__gt=0)
        )

    @action(detail=True, methods=["get"])
    def geometry(self, request, pk=None):
        """GeoJSON FeatureCollection of OSM geometries for this subject."""
        elements = OsmElement.objects.filter(subject_id=pk)
        serializer = OsmElementGeoSerializer(elements, many=True)
        return Response(serializer.data)


class GeoreferenceViewSet(viewsets.ReadOnlyModelViewSet):
    """Point georeferences as GeoJSON.

    Returns a GeoJSON FeatureCollection. Each feature represents the most
    recent point georeference for an image, with the photographer's location
    as its geometry.

    Supports bounding box filtering via the `in_bbox` parameter:
        ?in_bbox=west,south,east,north
    """

    serializer_class = GeoreferenceGeoSerializer
    pagination_class = GeoJsonDefaultPagination
    filterset_class = GeoreferenceFilter
    filter_backends = [DjangoFilterBackend, RemappingOrderingFilter, InBBoxFilter]
    bbox_filter_field = "point"
    ordering_fields = ["georeferenced_at", "confidence", "validation_count"]
    ordering = ["-georeferenced_at"]
    ordering_field_map = {
        "validation_count": "_validation_count",
    }

    def get_queryset(self):
        # Subquery: most recent georeference ID per image
        latest_ids = (
            Georeference.objects.filter(image__is_searchable=True)
            .order_by("image_id", "-georeferenced_at")
            .distinct("image_id")
            .values("id")
        )
        return (
            Georeference.objects.filter(id__in=latest_ids)
            .select_related("image", "georeferenced_by")
            .annotate(
                _validation_count=Coalesce(
                    Subquery(
                        GeoreferenceValidation.objects.filter(
                            georeference=OuterRef("pk"),
                        )
                        .values("georeference")
                        .annotate(c=Count("*"))
                        .values("c"),
                    ),
                    Value(0),
                ),
            )
        )


class FromAboveGeoreferenceViewSet(viewsets.ReadOnlyModelViewSet):
    """From-above (polygon) georeferences as GeoJSON.

    Returns a GeoJSON FeatureCollection. Each feature represents the most
    recent from-above georeference for an image, with the coverage polygon as
    its geometry.

    Supports bounding box filtering via the `in_bbox` parameter:
        ?in_bbox=west,south,east,north
    """

    serializer_class = FromAboveGeoreferenceGeoSerializer
    pagination_class = GeoJsonDefaultPagination
    filterset_class = FromAboveGeoreferenceFilter
    filter_backends = [DjangoFilterBackend, RemappingOrderingFilter, InBBoxFilter]
    bbox_filter_field = "polygon"
    ordering_fields = ["georeferenced_at", "confidence", "validation_count"]
    ordering = ["-georeferenced_at"]
    ordering_field_map = {
        "validation_count": "_validation_count",
    }

    def get_queryset(self):
        # Subquery: most recent from-above georeference ID per image
        latest_ids = (
            AerialGeoreference.objects.filter(
                image__is_searchable=True,
                image__aerial=True,
            )
            .order_by("image_id", "-georeferenced_at")
            .distinct("image_id")
            .values("id")
        )
        return (
            AerialGeoreference.objects.filter(id__in=latest_ids)
            .select_related("image", "georeferenced_by")
            .annotate(
                _validation_count=Coalesce(
                    Subquery(
                        AerialGeoreferenceValidation.objects.filter(
                            georeference=OuterRef("pk"),
                        )
                        .values("georeference")
                        .annotate(c=Count("*"))
                        .values("c"),
                    ),
                    Value(0),
                ),
            )
        )


# ---------------------------------------------------------------------------
# Site statistics
# ---------------------------------------------------------------------------


@api_view(["GET"])
def stats_view(request):
    """Site-wide statistics: source, collection, image, and georeferencing counts."""
    stats = get_overall_stats()
    breakdown = get_confidence_breakdown()
    total_georeferences = (
        Georeference.objects.filter(
            image__collection__public=True,
            image__collection__source__public=True,
        ).count()
        + AerialGeoreference.objects.filter(
            image__collection__public=True,
            image__collection__source__public=True,
        ).count()
    )
    return Response(
        {
            "total_sources": stats["total_sources"],
            "total_collections": stats["total_collections"],
            "total_images": stats["total_images"],
            "georeferenced_images": stats["total_georeferenced"],
            "total_georeferences": total_georeferences,
            "confidence_breakdown": {
                "low": breakdown["low"],
                "medium": breakdown["medium"],
                "high": breakdown["high"],
            },
        }
    )


# ---------------------------------------------------------------------------
# Activity feed
# ---------------------------------------------------------------------------


def _serialize_activity_event(event_type, obj, timestamp):
    """Convert one activity event tuple into a serializable dict."""
    if event_type == "group":
        images = []
        for member in obj.members.all():
            image = member.image
            if image:
                images.append(
                    {
                        "id": image.id,
                        "title": image.title,
                        "thumbnail": image.thumbnail,
                    }
                )
        return {
            "type": "georeference_group",
            "timestamp": timestamp,
            "data": {
                "user": obj.user.get_display_name() if obj.user else "Anonymous",
                "count": obj.count,
                "started_at": obj.started_at,
                "ended_at": obj.ended_at,
                "images": images,
            },
        }
    elif event_type == "comment":
        return {
            "type": "comment",
            "timestamp": timestamp,
            "data": {
                "user": obj.commented_by.get_display_name(),
                "text": obj.text,
                "image_id": obj.image_id,
                "image_title": obj.image.title,
            },
        }
    elif event_type == "milestone":
        return {
            "type": "user_milestone",
            "timestamp": timestamp,
            "data": {
                "user": obj.user.get_display_name(),
                "count": obj.count,
            },
        }
    elif event_type == "sitewide":
        return {
            "type": "sitewide_milestone",
            "timestamp": timestamp,
            "data": {
                "count": obj.count,
            },
        }


@api_view(["GET"])
def activity_view(request):
    """Recent activity feed: georeference groups, comments, and milestones.

    Query parameters:
        before: ISO 8601 timestamp -- return events before this time (for pagination)
        types: comma-separated event types to include
               (georeference_group, comment, user_milestone, sitewide_milestone).
               Defaults to all.
        limit: number of events to return (default 20, max 100)
    """
    # Map API type names (matching response) to internal event type names
    _TYPE_MAP = {
        "georeference_group": "group",
        "comment": "comment",
        "user_milestone": "milestone",
        "sitewide_milestone": "sitewide",
    }

    before = None
    before_param = request.query_params.get("before")
    if before_param:
        try:
            before = datetime.fromisoformat(before_param)
            if timezone.is_naive(before):
                before = timezone.make_aware(before)
        except (ValueError, TypeError):
            return Response({"error": "Invalid 'before' timestamp"}, status=400)

    types_param = request.query_params.get("types", "")
    if types_param:
        event_types = set()
        for t in types_param.split(","):
            if t in _TYPE_MAP:
                event_types.add(_TYPE_MAP[t])
        if not event_types:
            return Response([])
    else:
        event_types = set(_TYPE_MAP.values())

    try:
        limit = max(min(int(request.query_params.get("limit", 20)), 100), 1)
    except (ValueError, TypeError):
        return Response(
            {"error": "Invalid 'limit' parameter. Must be an integer."},
            status=400,
        )

    events = get_activity_events(before=before, limit=limit, event_types=event_types)

    result = []
    for event_type, obj, timestamp in events:
        serialized = _serialize_activity_event(event_type, obj, timestamp)
        if serialized:
            result.append(serialized)

    return Response(result)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


_ALLOWED_TABLE_REFS = {"images_image", "i"}


def _parse_search_filters(params, table_ref="images_image"):
    """Parse shared filter query parameters for search endpoints.

    Args:
        params: query parameter dict
        table_ref: SQL table name or alias to use for column references.
            Must be one of the values in ``_ALLOWED_TABLE_REFS``.

    Returns (where_conditions, where_params, error_response) where
    where_conditions is a list of ``psycopg.sql.Composable`` fragments and
    error_response is a Response if validation failed, else None.
    """
    if table_ref not in _ALLOWED_TABLE_REFS:
        raise ValueError(
            f"table_ref must be one of {_ALLOWED_TABLE_REFS}, got {table_ref!r}"
        )
    t = sql.Identifier(table_ref)
    where_conditions = []
    where_params = {}

    # Georeferenced filtering
    georeferenced = params.get("georeferenced")
    if georeferenced is not None:
        if georeferenced.lower() == "true":
            where_conditions.append(
                sql.SQL(
                    "EXISTS (SELECT 1 FROM images_georeference g"
                    " WHERE g.image_id = {t}.id)"
                ).format(t=t)
            )
        elif georeferenced.lower() == "false":
            where_conditions.append(
                sql.SQL(
                    "NOT EXISTS (SELECT 1 FROM images_georeference g"
                    " WHERE g.image_id = {t}.id)"
                ).format(t=t)
            )

    # Year filtering
    year_min = params.get("year_min")
    if year_min is not None:
        try:
            where_params["year_min"] = int(year_min)
            where_conditions.append(
                sql.SQL("({t}.fuzzy_end_decdate >= %(year_min)s)").format(t=t)
            )
        except ValueError:
            return (
                [],
                {},
                Response({"error": "year_min must be an integer."}, status=400),
            )

    year_max = params.get("year_max")
    if year_max is not None:
        try:
            where_params["year_max"] = int(year_max)
            where_conditions.append(
                sql.SQL("({t}.fuzzy_start_decdate <= %(year_max)s)").format(t=t)
            )
        except ValueError:
            return (
                [],
                {},
                Response({"error": "year_max must be an integer."}, status=400),
            )

    # Subject filtering
    subject = params.get("subject")
    if subject is not None:
        try:
            where_params["subject_id"] = int(subject)
            where_conditions.append(
                sql.SQL(
                    "EXISTS (SELECT 1 FROM images_subjectmapping sm"
                    " WHERE sm.image_id = {t}.id"
                    " AND sm.subject_id = %(subject_id)s)"
                ).format(t=t)
            )
        except ValueError:
            return (
                [],
                {},
                Response({"error": "subject must be an integer."}, status=400),
            )

    # Source filtering
    source = params.get("source")
    if source is not None:
        try:
            where_params["source_id"] = int(source)
            where_conditions.append(
                sql.SQL(
                    "{t}.collection_id IN (SELECT id FROM images_collection"
                    " WHERE source_id = %(source_id)s)"
                ).format(t=t)
            )
        except ValueError:
            return [], {}, Response({"error": "source must be an integer."}, status=400)

    # Collection filtering
    collection = params.get("collection")
    if collection is not None:
        try:
            where_params["collection_id"] = int(collection)
            where_conditions.append(
                sql.SQL("{t}.collection_id = %(collection_id)s").format(t=t)
            )
        except ValueError:
            return (
                [],
                {},
                Response({"error": "collection must be an integer."}, status=400),
            )

    return where_conditions, where_params, None


def _format_search_result(request, image, distance):
    """Format one image + distance into a search result dict."""
    similarity = 1.0 - float(distance)
    result = {
        "id": image.id,
        "title": image.title,
        "permalink": image.permalink,
        "thumbnail": image.thumbnail or image.permalink,
        "original_date": image.original_date,
        "date_display": image.date_display,
        "similarity": round(similarity, 4),
        "collection": {
            "id": image.collection.id,
            "name": image.collection.name,
            "slug": image.collection.slug,
            "source_name": image.collection.source.name,
        },
        "detail_url": request.build_absolute_uri(f"/api/v2/images/{image.id}/"),
    }
    return result


@api_view(["GET"])
def semantic_search_view(request):
    """Search images by meaning using CLIP embeddings.

    Encodes the query text into a vector and finds images whose visual
    content is most similar, even if the words don't appear in the title
    or description.

    Query parameters:
        q: search query (required, max 500 characters)
        page: page number (default 1)
        page_size: results per page (default 20, max 100)
        georeferenced: true/false -- filter by georeferencing status
        year_min: minimum year
        year_max: maximum year
        source: filter by source ID
        collection: filter by collection ID
        subject: filter by subject ID
    """
    if not CLIP_AVAILABLE:
        return Response(
            {"error": "Semantic search is not available."},
            status=503,
        )

    query = request.query_params.get("q", "").strip()
    if not query:
        return Response(
            {"error": "The 'q' query parameter is required."},
            status=400,
        )
    if len(query) > 500:
        return Response(
            {"error": "Query too long. Maximum 500 characters."},
            status=400,
        )

    try:
        page = max(int(request.query_params.get("page", 1)), 1)
        page_size = min(max(int(request.query_params.get("page_size", 20)), 1), 100)
    except ValueError:
        return Response({"error": "Invalid pagination parameters."}, status=400)
    offset = (page - 1) * page_size

    # Parse shared filters
    extra_conditions, extra_params, err = _parse_search_filters(request.query_params)
    if err:
        return err

    try:
        query_embedding = _get_text_embedding(query)
    except Exception:
        logger.warning("Failed to generate text embedding", exc_info=True)
        return Response({"error": "Could not process search query."}, status=400)

    where_conditions = [
        sql.SQL("embedding IS NOT NULL"),
        sql.SQL("is_searchable = true"),
    ]
    where_conditions.extend(extra_conditions)
    where_clause = sql.SQL(" AND ").join(where_conditions)

    try:
        with connection.cursor() as cursor:
            # Total count
            count_sql = sql.SQL(
                "SELECT COUNT(id) FROM images_image WHERE {where}"
            ).format(where=where_clause)
            cursor.execute(count_sql, extra_params)
            total_count = cursor.fetchone()[0]

            # Paginated results
            query_sql = sql.SQL(
                "SELECT id,"
                " (embedding::vector <=> %(embedding)s::vector) AS distance"
                " FROM images_image"
                " WHERE {where}"
                " ORDER BY embedding::vector <=> %(embedding)s::vector, id"
                " LIMIT %(limit)s OFFSET %(offset)s"
            ).format(where=where_clause)

            params = {
                **extra_params,
                "embedding": query_embedding,
                "limit": page_size,
                "offset": offset,
            }
            cursor.execute(query_sql, params)
            rows = cursor.fetchall()

        # Hydrate with ORM for consistent serialization
        image_ids = [row[0] for row in rows]
        distances = {row[0]: row[1] for row in rows}
        images_by_id = {
            img.id: img
            for img in Image.objects.filter(id__in=image_ids).select_related(
                "collection__source"
            )
        }

        results = []
        for image_id in image_ids:
            image = images_by_id.get(image_id)
            if image:
                results.append(
                    _format_search_result(request, image, distances[image_id])
                )

        return Response(
            {
                "count": total_count,
                "page": page,
                "page_size": page_size,
                "query": query,
                "results": results,
            }
        )

    except DatabaseError:
        logger.error("Database error in semantic search", exc_info=True)
        return Response({"error": "Search failed. Please try again."}, status=500)


@api_view(["GET"])
def text_search_view(request):
    """Search images by text using PostgreSQL trigram word similarity.

    Searches across image titles, descriptions, comments, and georeference
    notes.  Results are ranked by how closely the query matches.

    Query parameters:
        q: search query (required, max 500 characters)
        threshold: distance threshold 0-1 (default 0.7, lower is stricter)
        page: page number (default 1)
        page_size: results per page (default 20, max 100)
        georeferenced: true/false -- filter by georeferencing status
        year_min: minimum year
        year_max: maximum year
        source: filter by source ID
        collection: filter by collection ID
        subject: filter by subject ID
    """
    if not HAS_POSTGRES_SEARCH:
        return Response(
            {"error": "Text search is not available."},
            status=503,
        )

    query = request.query_params.get("q", "").strip()
    if not query:
        return Response(
            {"error": "The 'q' query parameter is required."},
            status=400,
        )
    if len(query) > 500:
        return Response(
            {"error": "Query too long. Maximum 500 characters."},
            status=400,
        )

    try:
        page = max(int(request.query_params.get("page", 1)), 1)
        page_size = min(max(int(request.query_params.get("page_size", 20)), 1), 100)
        threshold = max(0.0, min(float(request.query_params.get("threshold", 0.7)), 1.0))
    except ValueError:
        return Response({"error": "Invalid numeric parameters."}, status=400)
    offset = (page - 1) * page_size

    # Parse shared filters (text search aliases images_image as "i")
    extra_conditions, extra_params, err = _parse_search_filters(
        request.query_params, table_ref="i"
    )
    if err:
        return err

    filter_conditions = [sql.SQL("i.is_searchable = true")]
    filter_conditions.extend(extra_conditions)
    where_clause = sql.SQL(" AND ").join(filter_conditions)

    sql_params = {
        **extra_params,
        "query": query,
        "threshold": threshold,
        "limit": page_size,
        "offset": offset,
    }

    # The LATERAL joins search comments and georeference notes alongside
    # the image's own title and description.
    lateral_joins = """
        LEFT JOIN LATERAL (
            SELECT MIN(%(query)s <<-> c.text) AS best_comment_distance
            FROM images_comment c WHERE c.image_id = i.id
        ) comment_match ON true
        LEFT JOIN LATERAL (
            SELECT MIN(%(query)s <<-> g.confidence_notes) AS best_geo_distance
            FROM images_georeference g
            WHERE g.image_id = i.id AND g.confidence_notes != ''
        ) geo_match ON true
        LEFT JOIN LATERAL (
            SELECT MIN(%(query)s <<-> ag.confidence_notes) AS best_aerial_distance
            FROM images_aerialgeoreference ag
            WHERE ag.image_id = i.id AND ag.confidence_notes != ''
        ) aerial_match ON true
    """

    distance_expr = """
        LEAST(
            COALESCE(%(query)s <<-> i.title, 1.0),
            COALESCE(%(query)s <<-> i.description, 1.0),
            COALESCE(comment_match.best_comment_distance, 1.0),
            COALESCE(geo_match.best_geo_distance, 1.0),
            COALESCE(aerial_match.best_aerial_distance, 1.0)
        )
    """

    try:
        with connection.cursor() as cursor:
            # Total count
            count_sql = sql.SQL(
                "SELECT COUNT(i.id) FROM images_image i"
                " {laterals}"
                " WHERE {where} AND {distance} < %(threshold)s"
            ).format(
                laterals=sql.SQL(lateral_joins),
                where=where_clause,
                distance=sql.SQL(distance_expr),
            )
            cursor.execute(count_sql, sql_params)
            total_count = cursor.fetchone()[0]

            # Paginated results
            results_sql = sql.SQL(
                "SELECT i.id, {distance} AS distance"
                " FROM images_image i"
                " {laterals}"
                " WHERE {where} AND {distance} < %(threshold)s"
                " ORDER BY distance, i.id"
                " LIMIT %(limit)s OFFSET %(offset)s"
            ).format(
                laterals=sql.SQL(lateral_joins),
                where=where_clause,
                distance=sql.SQL(distance_expr),
            )
            cursor.execute(results_sql, sql_params)
            rows = cursor.fetchall()

        # Hydrate with ORM
        image_ids = [row[0] for row in rows]
        distances = {row[0]: row[1] for row in rows}
        images_by_id = {
            img.id: img
            for img in Image.objects.filter(id__in=image_ids).select_related(
                "collection__source"
            )
        }

        results = []
        for image_id in image_ids:
            image = images_by_id.get(image_id)
            if image:
                results.append(
                    _format_search_result(request, image, distances[image_id])
                )

        return Response(
            {
                "count": total_count,
                "page": page,
                "page_size": page_size,
                "query": query,
                "results": results,
            }
        )

    except DatabaseError:
        logger.error("Database error in text search", exc_info=True)
        return Response({"error": "Search failed. Please try again."}, status=500)
