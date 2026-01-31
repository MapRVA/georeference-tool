from django import template

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
        timeline_items.append(
            {
                "type": "georeference",
                "timestamp": geo.georeferenced_at,
                "georeference": geo,
            }
        )

    # Add aerial georeferences
    for aerial_geo in image.aerial_georeferences.all():
        timeline_items.append(
            {
                "type": "aerial_georeference",
                "timestamp": aerial_geo.georeferenced_at,
                "aerial_georeference": aerial_geo,
            }
        )

    # Add comments
    for comment in image.comments.all():
        timeline_items.append(
            {
                "type": "comment",
                "timestamp": comment.created_at,
                "comment": comment,
            }
        )

    # Sort by timestamp (oldest first, newest at bottom)
    timeline_items.sort(key=lambda x: x["timestamp"], reverse=False)

    return timeline_items
