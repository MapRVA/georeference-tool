from django import template
from django.utils import timezone
from django.utils.safestring import mark_safe

from images.utils import render_markdown_safe

register = template.Library()


@register.filter
def markdown(value):
    """
    Render markdown text to safe HTML.
    Supports #1234 image references which become links.
    """
    if not value:
        return ""
    return mark_safe(render_markdown_safe(value))


@register.filter
def timeago(value):
    """
    Return a human-friendly relative time string.

    Examples:
        Just now (< 1 minute)
        5 minutes ago
        2 hours ago
        3 days ago
    """
    if not value:
        return ""

    now = timezone.now()
    diff = now - value

    seconds = int(diff.total_seconds())
    minutes = seconds // 60
    hours = minutes // 60
    days = hours // 24

    if seconds < 60:
        return "Just now"
    elif minutes == 1:
        return "1 minute ago"
    elif minutes < 60:
        return f"{minutes} minutes ago"
    elif hours == 1:
        return "1 hour ago"
    elif hours < 24:
        return f"{hours} hours ago"
    elif days == 1:
        return "1 day ago"
    else:
        return f"{days} days ago"
