from django.urls import path
from . import views

app_name = "osm_auth"

urlpatterns = [
    path("login/", views.login, name="login"),
    path("logout/", views.logout, name="logout"),
    path("callback/", views.callback, name="callback"),
    path("profile/", views.profile, name="profile"),
    path("api/user/", views.user_data, name="user_data"),
    path("admin-login/", views.admin_login, name="admin_login"),
]
