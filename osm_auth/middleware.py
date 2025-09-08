class OSMAuthenticationMiddleware:
    """
    Middleware to add OSM authentication context to requests
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Add OSM authentication context to request
        self.process_request(request)

        response = self.get_response(request)
        return response

    def process_request(self, request):
        """
        Add OSM authentication information to request object
        """
        # Check if user is authenticated via OSM
        request.osm_authenticated = request.session.get("is_authenticated", False)

        # Add user information
        request.osm_user_id = request.session.get("osm_user_id")
        request.osm_username = request.session.get("osm_username")
        request.osm_user_data = request.session.get("osm_user_data")
        request.osm_oauth_token = request.session.get("osm_oauth_token")

        # Add helper method to check authentication
        request.is_osm_authenticated = lambda: request.osm_authenticated

        # Add method to get user display name
        request.get_osm_display_name = lambda: request.osm_username or "Anonymous"
