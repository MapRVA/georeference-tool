from rest_framework.throttling import SimpleRateThrottle


class AppRegistrationThrottle(SimpleRateThrottle):
    """Rate-limit OAuth app registration by client IP, regardless of auth state."""

    scope = "register"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class TokenExchangeThrottle(SimpleRateThrottle):
    """Rate-limit OAuth token exchange / refresh by client IP.

    Brute-force is impractical against random secrets/refresh tokens, so this
    is primarily DoS protection on the token endpoint. The chosen rate is
    permissive enough for many simultaneous flows behind a single NAT.
    """

    scope = "token"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }
