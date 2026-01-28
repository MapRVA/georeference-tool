import json

from django.contrib.gis.geos import Point
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.urls import reverse

from ..models import Image
from .core import get_min_scale_for_zoom


def geojson_endpoint(request):
    """Return GeoJSON FeatureCollection of georeferenced images"""

    # Start with all georeferenced images from public collections/sources
    images = (
        Image.objects.select_related("collection__source")
        .prefetch_related("georeferences", "subject_mappings__subject__wikidata_item")
        .filter(
            georeferences__isnull=False,  # Must be georeferenced
            collection__public=True,  # Collection must be public
            collection__source__public=True,  # Source must be public
        )
    )

    # Apply filters based on GET parameters
    image_id = request.GET.get("image")
    collection_id = request.GET.get("collection")
    source_id = request.GET.get("source")
    subject_id = request.GET.get("subject")

    if image_id:
        images = images.filter(id=image_id)
    if collection_id:
        images = images.filter(collection_id=collection_id)
    if source_id:
        images = images.filter(collection__source_id=source_id)
    if subject_id:
        images = images.filter(subject_mappings__subject_id=subject_id)

    # Build GeoJSON features
    features = []
    for image in images:
        georeference = image.get_georeference()
        if not georeference:  # Skip if no georeference found
            continue

        # Build the image entry URL (absolute URL to image detail page)
        img_entry = request.build_absolute_uri(
            reverse("images:image_detail", kwargs={"image_id": image.id})
        )

        # Build properties
        properties = {
            "img_url": image.permalink,
            "img_entry": img_entry,
            "original_date": str(image.original_date) if image.original_date else None,
            "edtf_date": str(image.edtf_date) if image.edtf_date else None,
            "start_decdate": image.start_decdate,
            "fuzzy_start_decdate": image.fuzzy_start_decdate,
            "end_decdate": image.end_decdate,
            "fuzzy_end_decdate": image.fuzzy_end_decdate,
        }

        # Only include direction if it's not None
        if georeference.direction is not None:
            properties["direction"] = georeference.direction

        # Only include scale if it's not None
        if image.scale is not None:
            properties["scale"] = image.scale

        # Add subjects as Wikidata IDs if they exist
        subject_wikidata_ids = [
            mapping.subject.wikidata_item.wikidata_id
            for mapping in image.subject_mappings.all()
            if mapping.subject.wikidata_item
        ]
        if subject_wikidata_ids:
            properties["subjects"] = subject_wikidata_ids

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [georeference.point.x, georeference.point.y],
            },
            "properties": properties,
        }
        features.append(feature)

    # Build final GeoJSON
    geojson = {"type": "FeatureCollection", "features": features}

    return JsonResponse(geojson)


def _build_aerial_georeference_feature(image, aerial_georeference, request):
    """
    Helper function to build a GeoJSON feature for an aerial georeference.

    Args:
        image: Image model instance
        aerial_georeference: AerialGeoreference model instance
        request: Django request object (for building absolute URLs)

    Returns:
        GeoJSON feature dict
    """
    # Build the image entry URL (absolute URL to image detail page)
    img_entry = request.build_absolute_uri(
        reverse("images:image_detail", kwargs={"image_id": image.id})
    )

    # Build properties
    properties = {
        "id": image.id,
        "img_url": image.permalink,
        "img_entry": img_entry,
        "original_date": str(image.original_date) if image.original_date else None,
        "edtf_date": str(image.edtf_date) if image.edtf_date else None,
        "start_decdate": image.start_decdate,
        "fuzzy_start_decdate": image.fuzzy_start_decdate,
        "end_decdate": image.end_decdate,
        "fuzzy_end_decdate": image.fuzzy_end_decdate,
        "confidence": aerial_georeference.confidence,
        "georeferenced_by": aerial_georeference.georeferenced_by.username
        if aerial_georeference.georeferenced_by
        else None,
    }

    # Only include scale if it's not None
    if image.scale is not None:
        properties["scale"] = image.scale

    # Add subjects as Wikidata IDs if they exist
    subject_wikidata_ids = [
        mapping.subject.wikidata_item.wikidata_id
        for mapping in image.subject_mappings.all()
        if mapping.subject.wikidata_item
    ]
    if subject_wikidata_ids:
        properties["subjects"] = subject_wikidata_ids

    return {
        "type": "Feature",
        "geometry": json.loads(aerial_georeference.polygon.geojson),
        "properties": properties,
    }


def aerial_geojson_endpoint(request):
    """Return GeoJSON FeatureCollection of aerial georeferences (most recent per image)"""
    # Start with all aerial images that have aerial georeferences from public collections/sources
    images = (
        Image.objects.select_related("collection__source")
        .prefetch_related("aerial_georeferences")
        .filter(
            aerial=True,  # Must be marked as aerial
            aerial_georeferences__isnull=False,  # Must have aerial georeferences
            collection__public=True,  # Collection must be public
            collection__source__public=True,  # Source must be public
            duplicate_of__isnull=True,  # Exclude duplicate images
        )
        .distinct()
    )

    # Apply filters based on GET parameters
    image_id = request.GET.get("image")
    collection_id = request.GET.get("collection")
    source_id = request.GET.get("source")
    subject_id = request.GET.get("subject")

    if image_id:
        images = images.filter(id=image_id)
    if collection_id:
        images = images.filter(collection_id=collection_id)
    if source_id:
        images = images.filter(collection__source_id=source_id)
    if subject_id:
        images = images.filter(subject_mappings__subject_id=subject_id)

    # Build GeoJSON features
    features = []
    for image in images:
        # Get the most recent aerial georeference (like get_georeference for regular ones)
        aerial_georeference = image.get_aerial_georeference()
        if not aerial_georeference:  # Skip if no aerial georeference found
            continue

        feature = _build_aerial_georeference_feature(
            image, aerial_georeference, request
        )
        features.append(feature)

    # Build final GeoJSON
    geojson = {"type": "FeatureCollection", "features": features}
    return JsonResponse(geojson)


def polygonal_georeferences_at_point(request):
    """
    API endpoint that returns all aerial georeferences that overlap a given point.

    Query parameters:
    - lat: Latitude (required)
    - lon: Longitude (required)

    Returns: GeoJSON FeatureCollection of aerial georeferences containing the point
    """

    # Get lat/lon from query parameters
    try:
        lat = float(request.GET.get("lat"))
        lon = float(request.GET.get("lon"))
    except (TypeError, ValueError):
        return JsonResponse(
            {"error": "Invalid or missing lat/lon parameters"}, status=400
        )

    # Validate coordinates are within reasonable bounds
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return JsonResponse({"error": "Coordinates out of valid range"}, status=400)

    # Create a Point from the coordinates (note: Point uses lon, lat order)
    point = Point(lon, lat)

    # Query for aerial georeferences that contain this point
    # We need to use the polygon field's contains lookup

    # Get all aerial images with public collections/sources

    images = (
        Image.objects.filter(
            aerial=True,  # Must be marked as aerial
            aerial_georeferences__isnull=False,  # Must have aerial georeferences
            collection__public=True,  # Collection must be public
            collection__source__public=True,  # Source must be public
            duplicate_of__isnull=True,  # Exclude duplicate images
        )
        .select_related("collection__source")
        .prefetch_related("aerial_georeferences")
        .distinct()
    )

    # Build GeoJSON features - only include if most recent georeference contains the point
    features = []
    for image in images:
        # Get the most recent aerial georeference for this image
        aerial_georeference = image.get_aerial_georeference()
        if not aerial_georeference:
            continue

        # Check if this georeference's polygon contains the point
        try:
            if not aerial_georeference.polygon.contains(point):
                continue
        except Exception:
            continue

        # Build feature using helper
        feature = _build_aerial_georeference_feature(
            image, aerial_georeference, request
        )
        # Add validation count (specific to this endpoint)
        feature["properties"]["validation_count"] = aerial_georeference.validation_count
        features.append(feature)

    # Build final GeoJSON
    geojson = {
        "type": "FeatureCollection",
        "features": features,
        "query": {
            "lat": lat,
            "lon": lon,
        },
        "count": len(features),
    }
    return JsonResponse(geojson)


def vector_tiles_endpoint(request, z, x, y):
    """Return MVT vector tiles of georeferenced images (using materialized view for performance)"""

    enable_scale_filter = (
        request.GET.get("enable_scale_filter", "false").lower() == "true"
    )

    # Apply the same filters as GeoJSON endpoint
    image_id = request.GET.get("image")
    collection_id = request.GET.get("collection")
    source_id = request.GET.get("source")
    subject_id = request.GET.get("subject")
    album_id = request.GET.get("album")

    # Build WHERE conditions for filtering on pre-filtered materialized view
    where_conditions = []
    where_params = []

    if enable_scale_filter:
        min_scale = get_min_scale_for_zoom(z)
        if min_scale is not None:
            where_conditions.append("(scale >= %s OR scale = 0)")
            where_params.append(min_scale)

    if image_id:
        where_conditions.append("image_id = %s")
        where_params.append(image_id)
    if collection_id:
        where_conditions.append(
            "image_id IN (SELECT id FROM images_image WHERE collection_id = %s)"
        )
        where_params.append(collection_id)
    if source_id:
        where_conditions.append(
            "image_id IN (SELECT i.id FROM images_image i JOIN images_collection c ON i.collection_id = c.id WHERE c.source_id = %s)"
        )
        where_params.append(source_id)
    if subject_id:
        where_conditions.append(
            "image_id IN (SELECT image_id FROM images_subjectmapping WHERE subject_id = %s)"
        )
        where_params.append(subject_id)
    if album_id:
        where_conditions.append(
            "image_id IN (SELECT image_id FROM images_albumimage WHERE album_id = %s)"
        )
        where_params.append(album_id)

    where_clause = " AND ".join(where_conditions)

    # Build WHERE clause - add filter conditions if any exist
    if where_clause:
        where_clause_sql = f"WHERE {where_clause} AND ST_Intersects(point, ST_Transform(ST_TileEnvelope(%s, %s, %s), 4326))"
    else:
        where_clause_sql = "WHERE ST_Intersects(point, ST_Transform(ST_TileEnvelope(%s, %s, %s), 4326))"

    sql = f"""
        SELECT ST_AsMVT(mvtgeoms.*, 'image_points') as mvt FROM (
            SELECT
                ST_AsMVTGeom(point_3857, ST_TileEnvelope(%s, %s, %s)) AS geom,
                image_id as id,
                thumbnail,
                original_date,
                edtf_date,
                start_decdate,
                fuzzy_start_decdate,
                end_decdate,
                fuzzy_end_decdate,
                scale,
                direction,
                confidence
            FROM public_georeferences_mvt
            {where_clause_sql}
        ) mvtgeoms
    """

    # Parameters: Z, X, Y for tile envelope (twice), plus any filter parameters
    query_params = [z, x, y] + where_params + [z, x, y]

    with connection.cursor() as cursor:
        cursor.execute(sql, query_params)
        result = cursor.fetchone()

        if result and result[0]:
            mvt_data = bytes(result[0])
            response = HttpResponse(mvt_data, content_type="application/x-protobuf")
            return response
        else:
            return HttpResponse(b"", content_type="application/x-protobuf")


def osm_elements_vector_tiles_endpoint(request, z, x, y):
    """Return MVT vector tiles of OSM elements (mixed geometries: points, lines, polygons)"""

    sql = """
        SELECT ST_AsMVT(mvtgeoms.*, 'osm_elements') as mvt FROM (
            SELECT
                ST_AsMVTGeom(ST_Transform(oe.geometry, 3857), ST_TileEnvelope(%s, %s, %s)) AS geom,
                oe.osm_id as osm_id,
                ST_GeometryType(oe.geometry) as geom_type,
                s.title as subject_name,
                s.slug as subject_slug,
                COALESCE(
                    string_agg(CAST(sm.image_id AS text), ','),
                    ''
                ) as image_ids,
                oe.geometry_area as geometry_area
            FROM subjects_osmelement oe
            LEFT JOIN subjects_subject s ON s.id = oe.subject_id
            INNER JOIN images_subjectmapping sm ON s.id = sm.subject_id
            WHERE ST_Intersects(oe.geometry, ST_Transform(ST_TileEnvelope(%s, %s, %s), 4326))
            GROUP BY oe.id, s.id, oe.osm_id, oe.geometry, s.title, s.slug, oe.geometry_area
            ORDER BY
                CASE
                    WHEN ST_GeometryType(oe.geometry) IN ('ST_Polygon', 'ST_MultiPolygon') THEN oe.geometry_area
                    ELSE 0
                END ASC,
                oe.osm_id ASC
        ) mvtgeoms
    """

    query_params = [z, x, y, z, x, y]

    with connection.cursor() as cursor:
        cursor.execute(sql, query_params)
        result = cursor.fetchone()

        if result and result[0]:
            mvt_data = bytes(result[0])
            response = HttpResponse(mvt_data, content_type="application/x-protobuf")
            return response
        else:
            return HttpResponse(b"", content_type="application/x-protobuf")
