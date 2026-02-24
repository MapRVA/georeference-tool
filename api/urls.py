from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("users", views.UserViewSet, basename="user")
router.register("sources", views.SourceViewSet, basename="source")
router.register("collections", views.CollectionViewSet, basename="collection")
router.register("images", views.ImageViewSet, basename="image")
router.register("subjects", views.SubjectViewSet, basename="subject")
router.register("georeferences", views.GeoreferenceViewSet, basename="georeference")
router.register(
    "from-above-georeferences",
    views.FromAboveGeoreferenceViewSet,
    basename="from-above-georeference",
)

urlpatterns = [
    # Nested route: collections scoped to a specific source
    path(
        "sources/<int:source_pk>/collections/",
        views.CollectionViewSet.as_view({"get": "list"}),
        name="source-collections",
    ),
    path("stats/", views.stats_view, name="api-stats"),
    path("activity/", views.activity_view, name="api-activity"),
    path("search/semantic/", views.semantic_search_view, name="api-semantic-search"),
    path("search/text/", views.text_search_view, name="api-text-search"),
] + router.urls
