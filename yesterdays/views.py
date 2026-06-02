import json

from django.core.cache import cache
from django.db import connection
from django.db.models import Count, F, Max
from django.db.models.functions import TruncDate
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from activity.views import get_activity_events
from images.models import (
    AerialGeoreference,
    Georeference,
    GeoreferenceValidation,
    Image,
    ImageOfTheDay,
    SiteSettings,
    TopRatedImageView,
)
from images.utils import get_confidence_breakdown, get_overall_stats


def get_top_rated_image():
    """Get the top-rated image for Open Graph metadata, with caching."""
    cached = cache.get("top_rated_image")
    if cached is not None:
        return cached

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

    cache.set("top_rated_image", top_rated_image, timeout=900)  # 15 minutes
    return top_rated_image


def home(request):
    """Home page view"""
    site_settings = SiteSettings.load()
    featured_entry = ImageOfTheDay.current_or_most_recent()
    context = {
        "page_title": "Home",
        "top_rated_image": get_top_rated_image(),
        "featured_entry": featured_entry,
        "featured_is_today": (
            featured_entry is not None and featured_entry.day == timezone.localdate()
        ),
        "activity_events": get_activity_events(
            limit=site_settings.home_feed_item_count,
            event_types=site_settings.home_feed_event_types,
        ),
    }
    return render(request, "home.html", context)


def map(request):
    """Map page view"""
    context = {
        "page_title": "Map",
        "top_rated_image": get_top_rated_image(),
    }
    return render(request, "map.html", context)


def stats(request):
    """Stats page view"""
    # Daily georeferences (cumulative) - include both point and aerial georeferences
    point_daily = (
        Georeference.objects.annotate(day=TruncDate("georeferenced_at"))
        .values("day")
        .annotate(count=Count("id"))
    )

    aerial_daily = (
        AerialGeoreference.objects.annotate(day=TruncDate("georeferenced_at"))
        .values("day")
        .annotate(count=Count("id"))
    )

    # Merge daily counts from both types
    daily_counts_by_date = {}
    for entry in point_daily:
        daily_counts_by_date[entry["day"]] = entry["count"]
    for entry in aerial_daily:
        if entry["day"] in daily_counts_by_date:
            daily_counts_by_date[entry["day"]] += entry["count"]
        else:
            daily_counts_by_date[entry["day"]] = entry["count"]

    cumulative_data = []
    cumulative_count = 0
    for day in sorted(daily_counts_by_date.keys()):
        cumulative_count += daily_counts_by_date[day]
        cumulative_data.append({"date": day.isoformat(), "count": cumulative_count})

    daily_labels = [entry["date"] for entry in cumulative_data]
    daily_counts = [entry["count"] for entry in cumulative_data]

    # Image status pie chart
    breakdown = get_confidence_breakdown()

    status_labels = [
        "Not Georeferenced",
        "Low Confidence",
        "Medium Confidence",
        "High Confidence",
    ]
    status_counts = [
        breakdown["not_georeferenced"],
        breakdown["low"],
        breakdown["medium"],
        breakdown["high"],
    ]

    # Top contributors - aggregate georeferences and validations by username
    # Include both point georeferences and aerial georeferences
    point_georeference_contributors = (
        Georeference.objects.values(username=F("georeferenced_by__first_name"))
        .annotate(
            georeference_count=Count("id"), last_georeference=Max("georeferenced_at")
        )
        .order_by("-georeference_count", "last_georeference")
    )

    aerial_georeference_contributors = (
        AerialGeoreference.objects.values(username=F("georeferenced_by__first_name"))
        .annotate(
            georeference_count=Count("id"), last_georeference=Max("georeferenced_at")
        )
        .order_by("-georeference_count", "last_georeference")
    )

    validation_contributors = (
        GeoreferenceValidation.objects.values(username=F("validated_by__first_name"))
        .annotate(validation_count=Count("id"))
        .order_by("-validation_count")
    )

    # Merge results with proper handling of anonymous users
    contributors = {}
    for entry in point_georeference_contributors:
        username = entry["username"] if entry["username"] else "Anonymous"
        contributors[username] = {
            "georeferences": entry["georeference_count"],
            "validations": 0,
            "last_georeference": entry["last_georeference"],
        }

    for entry in aerial_georeference_contributors:
        username = entry["username"] if entry["username"] else "Anonymous"
        if username in contributors:
            contributors[username]["georeferences"] += entry["georeference_count"]
            # Update last_georeference if aerial is more recent
            if entry["last_georeference"]:
                existing = contributors[username]["last_georeference"]
                if not existing or entry["last_georeference"] > existing:
                    contributors[username]["last_georeference"] = entry[
                        "last_georeference"
                    ]
        else:
            contributors[username] = {
                "georeferences": entry["georeference_count"],
                "validations": 0,
                "last_georeference": entry["last_georeference"],
            }

    for entry in validation_contributors:
        username = entry["username"] if entry["username"] else "Anonymous"
        if username in contributors:
            contributors[username]["validations"] = entry["validation_count"]
        else:
            contributors[username] = {
                "georeferences": 0,
                "validations": entry["validation_count"],
                "last_georeference": None,
            }

    sorted_contributors = sorted(
        contributors.items(),
        key=lambda item: (
            -item[1]["georeferences"],  # Primary: georeferences descending
            item[1]["last_georeference"]
            or "",  # Secondary: oldest first (None becomes empty string, sorts first)
        ),
    )

    # Get overall statistics using shared utility function
    overall_stats = get_overall_stats()

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
        "Disallow: */georeference/*",
        "Disallow: */polygonal-georeference/*",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


@require_GET
def health_ready(request):
    """
    Kubernetes readiness probe endpoint.
    Returns 200 if the app is ready to serve traffic.
    """
    checks = {
        "database": False,
    }

    # Check database connectivity
    try:
        connection.ensure_connection()
        checks["database"] = True
    except Exception:
        pass

    all_ready = all(checks.values())
    status = 200 if all_ready else 503

    return JsonResponse({"ready": all_ready, "checks": checks}, status=status)
