from django.urls import path

from . import views

app_name = "activity"

urlpatterns = [
    path("", views.activity_feed, name="feed"),
]
