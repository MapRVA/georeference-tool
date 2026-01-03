from django.urls import path

from . import views

app_name = "maps"

urlpatterns = [
    path("api/v1/map-layers/", views.map_layers_view, name="map_layers"),
]
