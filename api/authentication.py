from oauth2_provider.contrib.rest_framework import OAuth2Authentication


class HeaderOnlyOAuth2Authentication(OAuth2Authentication):
    """OAuth2Authentication that honors only RFC 6750 §2.1 transport.

    oauthlib accepts bearer tokens in the Authorization header, the form
    body (§2.2), or a URI query parameter (§2.3). The body/query fallbacks
    only fire when no Authorization header is present (see
    ``get_token_from_header`` in oauthlib.oauth2.rfc6749.tokens), so
    short-circuiting here is sufficient to disable them.

    Rationale for header-only: query-string tokens leak into access logs,
    referer headers, proxy caches, and browser history; body tokens confuse
    intermediaries and are impossible to combine with non-form bodies.
    """

    def authenticate(self, request):
        auth = request.META.get("HTTP_AUTHORIZATION", "")
        if auth.split(" ", 1)[0].lower() != "bearer":
            return None
        return super().authenticate(request)
