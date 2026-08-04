"""
URL configuration for yesterdays project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from oauth2_provider.urls import (
    base_urlpatterns,
    management_urlpatterns,
    metadata_urlpatterns,
)

from osm_auth import views as auth_views
from subjects import views as subject_views

from . import views
from .oauth_views import (
    AuthorizedApplicationsView,
    RevokeApplicationConsentView,
    S256OnlyAuthorizationView,
    ThrottledTokenView,
)


def _override_urlpatterns(patterns, overrides, excluded=frozenset()):
    """Rebuild a DOT urlpattern list, swapping in our views by URL name."""
    result = []
    for pattern in patterns:
        name = getattr(pattern, "name", None)
        if name in excluded:
            continue
        if name in overrides:
            route, view = overrides[name]
            result.append(path(route, view, name=name))
        else:
            result.append(pattern)
    return result


# Override a couple of DOT's default protocol endpoints:
#   - /authorize/ rejects code_challenge_method != "S256" and remembers consent
#   - /token/ adds IP-based rate limiting
# Drop endpoints we don't use:
#   - device flow (RFC 8628) — no device-grant clients
#   - introspect (RFC 7662) — we're both auth server and resource server,
#     so token validation happens via direct DB access, not introspection
_oauth_base_urlpatterns = _override_urlpatterns(
    base_urlpatterns,
    overrides={
        "authorize": ("authorize/", S256OnlyAuthorizationView.as_view()),
        "token": ("token/", ThrottledTokenView.as_view()),
    },
    excluded={
        "device-authorization",
        "device",
        "device-confirm",
        "device-grant-status",
        "introspect",
    },
)

# Replace DOT's token-based "authorized applications" management views with
# consent-based ones (same URL names, so existing {% url %} lookups keep
# working): apps are listed and revoked via ApplicationConsent records
# rather than access tokens.
_oauth_management_urlpatterns = _override_urlpatterns(
    management_urlpatterns,
    overrides={
        "authorized-token-list": (
            "authorized_tokens/",
            AuthorizedApplicationsView.as_view(),
        ),
        "authorized-token-delete": (
            "authorized_tokens/<int:pk>/delete/",
            RevokeApplicationConsentView.as_view(),
        ),
    },
)

# RFC 8414 authorization server metadata, served from the site root (the spec
# locates the document at the origin's /.well-known/, not under our /oauth/
# prefix).
_oauth_metadata_urlpatterns = _override_urlpatterns(
    metadata_urlpatterns,
    overrides={},
    excluded={"oauth-resource-metadata", "oauth-resource-metadata-path"},
)

urlpatterns = [
    path("", views.home, name="home"),
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("health/ready/", views.health_ready, name="health_ready"),
    path("map/", views.map, name="map"),
    path("stats/", views.stats, name="stats"),
    path("admin/login/", auth_views.admin_login, name="admin_login"),
    path("user/<str:username>/", auth_views.user_profile, name="user_profile"),
    path(
        "user/<str:username>/albums/",
        auth_views.user_albums_list,
        name="user_albums_list",
    ),
    path(
        "user/<str:username>/georeferences/",
        auth_views.user_georeferences,
        name="user_georeferences",
    ),
    # Backwards-compat redirect: old album URLs to new /album/<id>/ path
    path(
        "user/<str:username>/albums/<uuid:album_id>/",
        lambda request, username, album_id: RedirectView.as_view(
            url=f"/album/{album_id}/", permanent=True
        )(request),
    ),
    *([path("", include("directories.urls"))] if settings.DIRECTORIES_ENABLED else []),
    path("subjects/", include("subjects.urls")),
    path("activity/", include("activity.urls")),
    path("", include("images.urls")),
    # Subject API endpoints (kept at /api/v1/subjects/ for backwards compatibility)
    path(
        "api/v1/subjects/autocomplete/",
        subject_views.subject_autocomplete,
        name="subject_autocomplete",
    ),
    path(
        "api/v1/subjects/all/",
        subject_views.all_subjects_api,
        name="all_subjects_api",
    ),
    path(
        "api/v1/subjects/bulk-add/",
        subject_views.bulk_add_subject_to_images,
        name="bulk_add_subject_to_images",
    ),
    path(
        "api/v1/subjects/wikidata-lookup/",
        subject_views.wikidata_lookup,
        name="wikidata_lookup",
    ),
    path("api/v2/", include("api.urls")),
    # Protocol endpoints at /oauth/, user-facing app/token management at
    # /settings/oauth/, and the RFC 8414 metadata document at the site root
    # share a single "oauth2_provider" namespace so that reverse lookups like
    # {% url 'oauth2_provider:list' %} work across all three (the metadata view
    # itself reverses "oauth2_provider:authorize" and friends).
    # OIDC endpoints from the package are intentionally not mounted; we have
    # no use case for federated identity (we already delegate identity to OSM
    # upstream). Discovery works without them: RFC 8414 is OAuth-only and is
    # not gated behind OIDC_ENABLED.
    path(
        "",
        include(
            (
                [
                    path("oauth/", include(_oauth_base_urlpatterns)),
                    path("settings/oauth/", include(_oauth_management_urlpatterns)),
                    path("", include(_oauth_metadata_urlpatterns)),
                ],
                "oauth2_provider",
            )
        ),
    ),
    path("settings/", include("osm_auth.settings_urls")),
    path("layers/", include("maps.urls")),
    path("maps/", RedirectView.as_view(url="/layers/", permanent=True)),
    path(
        "maps/<path:rest>",
        RedirectView.as_view(url="/layers/%(rest)s", permanent=True),
    ),
    path("admin/", admin.site.urls),
    path("auth/", include("osm_auth.urls")),
]

# Serve static files during development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
