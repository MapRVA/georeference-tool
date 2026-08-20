from django.urls import path

from . import views

app_name = "regions"

urlpatterns = [
    path("", views.region_index, name="region_index"),
    path(
        "api/autocomplete/",
        views.region_autocomplete,
        name="region_autocomplete",
    ),
]
