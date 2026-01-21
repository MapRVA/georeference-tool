from django import template

from ..utils import render_markdown_safe

register = template.Library()


@register.simple_tag
def georeference_url_for_image(base_url, image_id):
    """
    Build a georeference URL for a specific image, using the correct query separator.

    Usage:
        {% georeference_url_for_image georeference_url image.id %}

    Examples:
        {% georeference_url_for_image "/georeference/" 123 %} -> "/georeference/?image=123"
        {% georeference_url_for_image "/georeference/?source=foo" 123 %} -> "/georeference/?source=foo&image=123"
    """
    if not base_url:
        base_url = "/georeference/"
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}image={image_id}"


@register.simple_tag
def get_timeline_items(image):
    """
    Build timeline items for an image, combining georeferences, aerial georeferences,
    and comments in chronological order.

    Usage:
        {% load image_tags %}
        {% get_timeline_items image as timeline_items %}
    """
    timeline_items = []

    # Add georeferences
    for geo in image.georeferences.all():
        rendered_geo_notes = None
        if geo.confidence_notes:
            rendered_geo_notes = render_markdown_safe(geo.confidence_notes)
        timeline_items.append(
            {
                "type": "georeference",
                "timestamp": geo.georeferenced_at,
                "georeference": geo,
                "rendered_notes": rendered_geo_notes,
            }
        )

    # Add aerial georeferences
    for aerial_geo in image.aerial_georeferences.all():
        rendered_aerial_notes = None
        if aerial_geo.confidence_notes:
            rendered_aerial_notes = render_markdown_safe(aerial_geo.confidence_notes)
        timeline_items.append(
            {
                "type": "aerial_georeference",
                "timestamp": aerial_geo.georeferenced_at,
                "aerial_georeference": aerial_geo,
                "rendered_notes": rendered_aerial_notes,
            }
        )

    # Add comments
    for comment in image.comments.all():
        rendered_comment_text = None
        if comment.text:
            rendered_comment_text = render_markdown_safe(comment.text)
        timeline_items.append(
            {
                "type": "comment",
                "timestamp": comment.created_at,
                "comment": comment,
                "rendered_text": rendered_comment_text,
            }
        )

    # Sort by timestamp (oldest first, newest at bottom)
    timeline_items.sort(key=lambda x: x["timestamp"], reverse=False)

    return timeline_items
