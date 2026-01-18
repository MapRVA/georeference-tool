import json
from datetime import datetime

from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone

from images.models import Comment

from .models import GeoreferenceGroup, GeoreferenceGroupMember, UserMilestone

ITEMS_PER_PAGE = 20
FETCH_LIMIT = 50  # Fetch this many of each type to ensure we have enough
ALL_EVENT_TYPES = {"group", "comment", "milestone"}


def activity_feed(request):
    """Display the activity feed showing recent site activity."""
    before_param = request.GET.get("before")
    types_param = request.GET.get("types", "")
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    # Parse event types filter
    if types_param:
        selected_types = set(types_param.split(",")) & ALL_EVENT_TYPES
        # Fall back to all types if no valid types provided
        if not selected_types:
            selected_types = ALL_EVENT_TYPES
    else:
        selected_types = ALL_EVENT_TYPES

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

    events = get_activity_events(
        before=before, limit=ITEMS_PER_PAGE, event_types=selected_types
    )

    if is_ajax:
        return render(
            request,
            "activity/partials/activity_items.html",
            {"events": events, "has_more": len(events) == ITEMS_PER_PAGE},
        )

    # Build filter states for JavaScript initialization
    filter_states = json.dumps({t: t in selected_types for t in ALL_EVENT_TYPES})

    return render(
        request,
        "activity/feed.html",
        {
            "events": events,
            "has_more": len(events) == ITEMS_PER_PAGE,
            "filter_states_json": filter_states,
        },
    )


def get_activity_events(before=None, limit=ITEMS_PER_PAGE, event_types=None):
    """
    Fetch activity events, optionally filtered to those before a timestamp.

    Args:
        before: Optional datetime to filter events before
        limit: Maximum number of events to return
        event_types: Set of event types to include (default: all types)

    Returns a list of (type, object, timestamp) tuples sorted by timestamp descending.
    """
    if event_types is None:
        event_types = ALL_EVENT_TYPES

    # Build filters
    group_filter = {}
    comment_filter = {}
    milestone_filter = {}

    if before:
        group_filter["ended_at__lt"] = before
        comment_filter["created_at__lt"] = before
        milestone_filter["reached_at__lt"] = before

    events = []

    # Fetch latest of each type (over-fetch to ensure enough after merge)
    if "group" in event_types:
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
        events.extend(("group", g, g.ended_at) for g in groups)

    if "comment" in event_types:
        comments = (
            Comment.objects.filter(**comment_filter)
            .select_related("commented_by", "image")
            .order_by("-created_at")[:FETCH_LIMIT]
        )
        events.extend(("comment", c, c.created_at) for c in comments)

    if "milestone" in event_types:
        milestones = (
            UserMilestone.objects.filter(**milestone_filter)
            .select_related("user")
            .order_by("-reached_at")[:FETCH_LIMIT]
        )
        events.extend(("milestone", m, m.reached_at) for m in milestones)

    # Sort by timestamp descending and take the requested limit
    events.sort(key=lambda e: e[2], reverse=True)

    return events[:limit]
