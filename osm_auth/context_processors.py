def osm_auth(request):
    """
    Context processor to make OSM authentication data available in all templates
    """
    return {
        "osm_authenticated": request.session.get("is_authenticated", False),
        "osm_user_id": request.session.get("osm_user_id"),
        "osm_username": request.session.get("osm_username"),
        "osm_user_data": request.session.get("osm_user_data"),
        "osm_display_name": request.session.get("osm_username", "Anonymous"),
    }
