from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.shortcuts import render

from images.models import Comment

from .models import GeoreferenceGroup, GeoreferenceGroupMember, UserMilestone


def activity_feed(request):
    """Display the activity feed showing recent site activity."""
    limit = 50  # Over-fetch to ensure enough after merge

    # Fetch latest georeference groups with their members
    groups = (
        GeoreferenceGroup.objects.select_related("user")
        .prefetch_related(
            Prefetch(
                "members",
                queryset=GeoreferenceGroupMember.objects.select_related(
                    "georeference__image", "aerial_georeference__image"
                ).order_by("-added_at"),
            )
        )
        .order_by("-ended_at")[:limit]
    )

    # Fetch latest comments
    comments = Comment.objects.select_related("commented_by", "image").order_by(
        "-created_at"
    )[:limit]

    # Fetch latest milestones
    milestones = UserMilestone.objects.select_related("user").order_by("-reached_at")[
        :limit
    ]

    # Normalize to (type, object, timestamp) tuples
    events = []
    events.extend(("group", g, g.ended_at) for g in groups)
    events.extend(("comment", c, c.created_at) for c in comments)
    events.extend(("milestone", m, m.reached_at) for m in milestones)

    # Sort by timestamp descending
    events.sort(key=lambda e: e[2], reverse=True)

    # Paginate
    paginator = Paginator(events, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "activity/feed.html", {"page_obj": page_obj})
