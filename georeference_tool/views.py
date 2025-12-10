import json

from django.db.models import Count, F
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from images.models import (
    Collection,
    Georeference,
    GeoreferenceValidation,
    Image,
    Source,
    TopRatedImageView,
)


def home(request):
    """Home page view"""
    # Get top-rated image from entire site for Open Graph metadata
    top_rated_entry = (
        TopRatedImageView.objects.all()
        .order_by("-sort_value", "-avg_rating", "-vote_count", "image_id")
        .first()
    )
    top_rated_image = None
    if top_rated_entry:
        top_rated_image = Image.objects.select_related("collection__source").get(
            id=top_rated_entry.image_id
        )

    context = {
        "page_title": "Home",
        "top_rated_image": top_rated_image,
    }
    return render(request, "home.html", context)


def stats(request):
    """Stats page view"""
    # Daily georeferences (cumulative)
    daily_georeferences = (
        Georeference.objects.annotate(day=TruncDate("georeferenced_at"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )

    cumulative_data = []
    cumulative_count = 0
    for entry in daily_georeferences:
        cumulative_count += entry["count"]
        cumulative_data.append(
            {"date": entry["day"].isoformat(), "count": cumulative_count}
        )

    daily_labels = [entry["date"] for entry in cumulative_data]
    daily_counts = [entry["count"] for entry in cumulative_data]

    # Image status pie chart - optimized with single database query
    from django.db import connection

    query = """
    WITH point_georefs AS (
        SELECT
            g.image_id,
            g.confidence,
            ROW_NUMBER() OVER (PARTITION BY g.image_id ORDER BY g.georeferenced_at DESC) as rn
        FROM images_georeference g
    ),
    aerial_georefs AS (
        SELECT
            ag.image_id,
            ag.confidence,
            ROW_NUMBER() OVER (PARTITION BY ag.image_id ORDER BY ag.georeferenced_at DESC) as rn
        FROM images_aerialgeoreference ag
    )
    SELECT
        COALESCE(
            CASE
                WHEN img.aerial = TRUE AND ag.confidence IS NOT NULL THEN ag.confidence
                WHEN img.aerial = FALSE AND pg.confidence IS NOT NULL THEN pg.confidence
                ELSE 'not_georeferenced'
            END
        ) as confidence_level,
        COUNT(DISTINCT img.id) as count
    FROM images_image img
    LEFT JOIN aerial_georefs ag ON img.id = ag.image_id AND ag.rn = 1
    LEFT JOIN point_georefs pg ON img.id = pg.image_id AND pg.rn = 1
    WHERE img.duplicate_of_id IS NULL
      AND img.will_not_georef = FALSE
    GROUP BY confidence_level
    """

    with connection.cursor() as cursor:
        cursor.execute(query)
        confidence_results = cursor.fetchall()

    # Parse query results into counts
    total_images = 0
    not_georeferenced_count = 0
    low_confidence_count = 0
    medium_confidence_count = 0
    high_confidence_count = 0

    for confidence_level, count in confidence_results:
        total_images += count
        if confidence_level == "not_georeferenced":
            not_georeferenced_count = count
        elif confidence_level == "low":
            low_confidence_count = count
        elif confidence_level == "medium":
            medium_confidence_count = count
        elif confidence_level == "high":
            high_confidence_count = count

    status_labels = [
        "Not Georeferenced",
        "Low Confidence",
        "Medium Confidence",
        "High Confidence",
    ]
    status_counts = [
        not_georeferenced_count,
        low_confidence_count,
        medium_confidence_count,
        high_confidence_count,
    ]

    # Top contributors - aggregate georeferences and validations by username
    georeference_contributors = (
        Georeference.objects.values(username=F("georeferenced_by__first_name"))
        .annotate(georeference_count=Count("id"))
        .order_by("-georeference_count")
    )

    validation_contributors = (
        GeoreferenceValidation.objects.values(username=F("validated_by__first_name"))
        .annotate(validation_count=Count("id"))
        .order_by("-validation_count")
    )

    # Merge results with proper handling of anonymous users
    contributors = {}
    for entry in georeference_contributors:
        username = entry["username"] if entry["username"] else "Anonymous"
        contributors[username] = {
            "georeferences": entry["georeference_count"],
            "validations": 0,
        }

    for entry in validation_contributors:
        username = entry["username"] if entry["username"] else "Anonymous"
        if username in contributors:
            contributors[username]["validations"] = entry["validation_count"]
        else:
            contributors[username] = {
                "georeferences": 0,
                "validations": entry["validation_count"],
            }

    sorted_contributors = sorted(
        contributors.items(), key=lambda item: item[1]["georeferences"], reverse=True
    )

    # Overall statistics
    total_sources = Source.objects.filter(public=True).count()
    total_collections = Collection.objects.filter(
        public=True, source__public=True
    ).count()
    # Georeferenced count is the sum of all confidence levels (excluding not georeferenced)
    georeferenced_count = (
        low_confidence_count + medium_confidence_count + high_confidence_count
    )
    georeferenced_percentage = (
        round((georeferenced_count / total_images * 100), 1) if total_images > 0 else 0
    )

    overall_stats = {
        "total_sources": total_sources,
        "total_collections": total_collections,
        "total_images": total_images,
        "total_georeferenced": georeferenced_count,
        "georeferenced_percentage": georeferenced_percentage,
    }

    context = {
        "page_title": "Stats",
        "daily_labels": json.dumps(daily_labels),
        "daily_counts": json.dumps(daily_counts),
        "status_labels": json.dumps(status_labels),
        "status_counts": json.dumps(status_counts),
        "contributors": sorted_contributors,
        "overall_stats": overall_stats,
    }
    return render(request, "stats.html", context)


@require_GET
def robots_txt(request):
    """Serve robots.txt"""
    lines = [
        "User-agent: *",
        "Disallow: /search/",
        "Disallow: */similar/",
        "Disallow: /api/",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")
