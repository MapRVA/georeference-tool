from django.shortcuts import render


def home(request):
    """Home page view"""
    context = {
        "page_title": "Home",
    }
    return render(request, "home.html", context)


import json

from django.db.models import Count, F
from django.db.models.functions import TruncDate, TruncHour

from images.models import (
    Collection,
    Georeference,
    GeoreferenceValidation,
    Image,
    Source,
)


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
    total_images = Image.objects.count()
    georeferenced_images = Image.objects.filter(georeferences__isnull=False).distinct()
    not_georeferenced_count = total_images - georeferenced_images.count()

    low_confidence_count = georeferenced_images.filter(
        georeferences__confidence="low"
    ).count()
    medium_confidence_count = georeferenced_images.filter(
        georeferences__confidence="medium"
    ).count()
    high_confidence_count = georeferenced_images.filter(
        georeferences__confidence="high"
    ).count()

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
    georeferenced_count = georeferenced_images.count()
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
