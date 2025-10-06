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

from images.models import Georeference, GeoreferenceValidation, Image


def stats(request):
    """Stats page view"""
    # Hourly georeferences (cumulative, but displayed by day on chart)
    hourly_georeferences = (
        Georeference.objects.annotate(hour=TruncHour("georeferenced_at"))
        .values("hour")
        .annotate(count=Count("id"))
        .order_by("hour")
    )

    cumulative_data = []
    cumulative_count = 0
    for entry in hourly_georeferences:
        cumulative_count += entry["count"]
        cumulative_data.append(
            {"date": entry["hour"].isoformat(), "count": cumulative_count}
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

    context = {
        "page_title": "Stats",
        "daily_labels": json.dumps(daily_labels),
        "daily_counts": json.dumps(daily_counts),
        "status_labels": json.dumps(status_labels),
        "status_counts": json.dumps(status_counts),
        "contributors": sorted_contributors,
    }
    return render(request, "stats.html", context)
