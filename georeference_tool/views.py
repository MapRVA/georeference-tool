import json

from django.db.models import Count, F
from django.db.models.functions import TruncDate
from django.shortcuts import render

from images.models import (
    Collection,
    Georeference,
    GeoreferenceValidation,
    Image,
    Source,
)


def home(request):
    """Home page view"""
    context = {
        "page_title": "Home",
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

    # Image status pie chart
    # Get all images excluding duplicates and those marked "do not georeference"
    eligible_images = Image.objects.filter(
        duplicate_of__isnull=True, will_not_georef=False
    )
    total_images = eligible_images.count()

    # Initialize status counts
    not_georeferenced_count = 0
    low_confidence_count = 0
    medium_confidence_count = 0
    high_confidence_count = 0

    # Iterate through all eligible images to determine their status
    for image in eligible_images:
        # Determine which type of georeference to check based on whether it's an aerial
        if image.aerial:
            # For aerial images, use the most recent aerial georeference
            most_recent_georef = image.aerial_georeferences.order_by(
                "-georeferenced_at"
            ).first()
        else:
            # For regular images, use the most recent point georeference
            most_recent_georef = image.georeferences.order_by(
                "-georeferenced_at"
            ).first()

        # Categorize based on the most recent georeference
        if most_recent_georef is None:
            not_georeferenced_count += 1
        elif most_recent_georef.confidence == "low":
            low_confidence_count += 1
        elif most_recent_georef.confidence == "medium":
            medium_confidence_count += 1
        elif most_recent_georef.confidence == "high":
            high_confidence_count += 1

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

    # Top contributors
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

    contributors = {}
    for entry in georeference_contributors:
        username = entry["username"] if entry["username"] else "Anonymous"
        contributors[username] = {
            "georeferences": entry["georeference_count"],
            "validations": 0,
        }

    for entry in validation_contributors:
        username = entry["username"]
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
