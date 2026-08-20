from .models import Region

# Cookie persisting the navbar region selection (value: a Region slug).
# Written client-side by assets/js/components/region_selector.ts; the name
# reaches that component via a data attribute on the selector partial.
REGION_COOKIE_NAME = "region"


def get_current_region(request):
    """The Region picked in the navbar selector, or None.

    Unknown or stale slugs resolve to None rather than erroring. Views
    that branch on the selection (e.g. the homepage) share this with the
    context processor below.
    """
    slug = request.COOKIES.get(REGION_COOKIE_NAME, "")
    return Region.objects.filter(slug=slug).first() if slug else None


def current_region(request):
    """Resolve the region cookie and its frontend map configuration."""
    region = get_current_region(request)
    center = None
    map_bounds = None
    search_bounds = None
    if region is not None:
        point = region.coordinate_location
        center = [point.x, point.y]
        map_bounds = region.map_bbox
        search_bounds = region.search_bbox
    return {
        "current_region": region,
        "region_cookie_name": REGION_COOKIE_NAME,
        "region_map_center": center,
        "region_map_bounds": map_bounds,
        "region_search_bbox": search_bounds,
    }
