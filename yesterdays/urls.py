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

from osm_auth import views as auth_views
from subjects import views as subject_views

from . import views

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
    # Backwards-compat redirect: old album URLs to new /album/<id>/ path
    path(
        "user/<str:username>/albums/<uuid:album_id>/",
        lambda request, username, album_id: RedirectView.as_view(
            url=f"/album/{album_id}/", permanent=True
        )(request),
    ),
    *(
        [path("", include("directories.urls"))]
        if settings.DIRECTORIES_ENABLED
        else []
    ),
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
    path("maps/", include("maps.urls")),
    path("admin/", admin.site.urls),
    path("auth/", include("osm_auth.urls")),
]

# Serve static files during development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
