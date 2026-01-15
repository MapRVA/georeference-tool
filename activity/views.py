from datetime import datetime

from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone

from images.models import Comment

from .models import GeoreferenceGroup, GeoreferenceGroupMember, UserMilestone

ITEMS_PER_PAGE = 20
FETCH_LIMIT = 50  # Fetch this many of each type to ensure we have enough


def activity_feed(request):
    """Display the activity feed showing recent site activity."""
    before_param = request.GET.get("before")
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    # Parse 'before' timestamp if provided
    before = None
    if before_param:
        try:
            before = datetime.fromisoformat(before_param)
            if timezone.is_naive(before):
                before = timezone.make_aware(before)
        except (ValueError, TypeError):
            if is_ajax:
                raise Http404("Invalid timestamp")
            # For non-AJAX, just ignore invalid timestamp

    events = get_activity_events(before=before, limit=ITEMS_PER_PAGE)

    if is_ajax:
        return render(
            request,
            "activity/partials/activity_items.html",
            {"events": events, "has_more": len(events) == ITEMS_PER_PAGE},
        )

    return render(
        request,
        "activity/feed.html",
        {"events": events, "has_more": len(events) == ITEMS_PER_PAGE},
    )


def get_activity_events(before=None, limit=ITEMS_PER_PAGE):
    """
    Fetch activity events, optionally filtered to those before a timestamp.

    Returns a list of (type, object, timestamp) tuples sorted by timestamp descending.
    """
    # Build filters
    group_filter = {}
    comment_filter = {}
    milestone_filter = {}

    if before:
        group_filter["ended_at__lt"] = before
        comment_filter["created_at__lt"] = before
        milestone_filter["reached_at__lt"] = before

    # Fetch latest of each type (over-fetch to ensure enough after merge)
    groups = (
        GeoreferenceGroup.objects.filter(**group_filter)
        .select_related("user")
        .prefetch_related(
            Prefetch(
                "members",
                queryset=GeoreferenceGroupMember.objects.select_related(
                    "georeference__image", "aerial_georeference__image"
                ).order_by("-added_at"),
            )
        )
        .order_by("-ended_at")[:FETCH_LIMIT]
    )

    comments = (
        Comment.objects.filter(**comment_filter)
        .select_related("commented_by", "image")
        .order_by("-created_at")[:FETCH_LIMIT]
    )

    milestones = (
        UserMilestone.objects.filter(**milestone_filter)
        .select_related("user")
        .order_by("-reached_at")[:FETCH_LIMIT]
    )

    # Normalize to (type, object, timestamp) tuples
    events = []
    events.extend(("group", g, g.ended_at) for g in groups)
    events.extend(("comment", c, c.created_at) for c in comments)
    events.extend(("milestone", m, m.reached_at) for m in milestones)

    # Sort by timestamp descending and take the requested limit
    events.sort(key=lambda e: e[2], reverse=True)

    return events[:limit]
