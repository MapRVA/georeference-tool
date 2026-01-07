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

from maps.views import map_layers_view
from osm_auth import views as auth_views
from subjects import views as subject_views

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("stats/", views.stats, name="stats"),
    path("admin/login/", auth_views.admin_login, name="admin_login"),
    path("user/<str:username>/", auth_views.user_profile, name="user_profile"),
    path(
        "user/<str:username>/albums/",
        auth_views.user_albums_list,
        name="user_albums_list",
    ),
    path("subjects/", include("subjects.urls")),
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
    path("api/v1/map-layers/", map_layers_view, name="map_layers_api"),
    path("maps/", include("maps.urls")),
    path("admin/", admin.site.urls),
    path("auth/", include("osm_auth.urls")),
]

# Serve static files during development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
