from urllib.parse import parse_qs, urlencode, urlparse

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from osm_login_python.core import Auth

from images.models import AerialGeoreference, Album, Georeference


def get_osm_auth():
    """Initialize and return robust OSM Auth instance with settings"""
    return Auth(
        osm_url=settings.OSM_URL,
        client_id=settings.OSM_CLIENT_ID,
        client_secret=settings.OSM_CLIENT_SECRET,
        secret_key=settings.OSM_SECRET_KEY,
        login_redirect_uri=settings.OSM_LOGIN_REDIRECT_URI,
        scope=settings.OSM_SCOPE,
    )


def login(request):
    """Initiate OSM OAuth login"""
    if not all(
        [settings.OSM_CLIENT_ID, settings.OSM_CLIENT_SECRET, settings.OSM_SECRET_KEY]
    ):
        messages.error(request, "OSM authentication is not properly configured.")
        # Try to redirect back to where they came from
        referrer = request.META.get("HTTP_REFERER")
        if referrer:
            return redirect(referrer)
        return redirect("/")
    # Clear any existing authentication session data before starting new login
    session_keys_to_clear = [
        "osm_user_id",
        "osm_username",
        "osm_user_data",
        "osm_oauth_token",
        "is_authenticated",
    ]
    for key in session_keys_to_clear:
        request.session.pop(key, None)

    # Build the post-login redirect URL
    # If logging in from a georeference page with queue context (source, collection, etc.),
    # preserve those parameters and use current_image instead of image
    referrer = request.META.get("HTTP_REFERER")
    image_id = request.GET.get("image")
    georeference_path = reverse("images:georeference_interface")

    if referrer and image_id:
        parsed = urlparse(referrer)
        # Check if referrer is the georeference interface
        if parsed.path == georeference_path:
            query_params = parse_qs(parsed.query)
            # Check if there are queue context params
            queue_params = {"source", "collection", "album", "subject", "difficulty"}
            has_queue_context = any(p in query_params for p in queue_params)

            if has_queue_context:
                # Use current_image to preserve queue context
                query_params.pop("current_image", None)
                query_params.pop("image", None)
                query_params["current_image"] = [image_id]
                new_query = urlencode(query_params, doseq=True)
                redirect_url = f"{georeference_path}?{new_query}"
            else:
                # No queue context, use standard image= parameter
                redirect_url = f"{georeference_path}?image={image_id}"

            request.session["login_redirect_url"] = request.build_absolute_uri(
                redirect_url
            )
        else:
            # Referrer is not georeference page, just go back there
            request.session["login_redirect_url"] = referrer
    elif image_id:
        # No referrer but have image_id (direct link to login with image param)
        redirect_url = f"{georeference_path}?image={image_id}"
        request.session["login_redirect_url"] = request.build_absolute_uri(redirect_url)
    elif referrer:
        # No image_id, just use referrer
        request.session["login_redirect_url"] = referrer

    try:
        osm_auth = get_osm_auth()
        login_data = osm_auth.login()
        return HttpResponseRedirect(login_data["login_url"])
    except Exception as e:
        messages.error(request, f"Error initiating OSM login: {str(e)}")
        return redirect("/")


def callback(request):
    """Handle OSM OAuth callback"""
    try:
        osm_auth = get_osm_auth()
        current_url = request.build_absolute_uri()
        # Get token and user data from OSM
        token_data = osm_auth.callback(current_url)
        # Deserialize the user data
        user_data = osm_auth.deserialize_data(token_data["user_data"])
        # Validate that we have the essential user data
        if not user_data or not user_data.get("id") or not user_data.get("username"):
            raise ValueError("Invalid user data received from OSM")
        # Store user info in session
        request.session["osm_user_id"] = user_data.get("id")
        request.session["osm_username"] = user_data.get("username")
        request.session["osm_user_data"] = user_data
        request.session["osm_oauth_token"] = token_data.get("oauth_token")
        request.session["is_authenticated"] = True
        # Always authenticate with Django's auth system to create/update user
        django_user = authenticate(request=request)
        if django_user:
            auth_login(request, django_user)
        messages.success(
            request, f"Successfully logged in as {user_data.get('username')}!"
        )
        # Check if there's a login redirect URL stored
        login_redirect_url = request.session.pop("login_redirect_url", None)
        if login_redirect_url:
            return redirect(login_redirect_url)
        # Check if this was an admin login attempt
        admin_redirect = request.session.pop("admin_login_redirect", None)
        if admin_redirect:
            if django_user and django_user.is_staff:
                return redirect(admin_redirect)
            else:
                messages.error(
                    request, "You don't have permission to access the admin area."
                )
        return redirect("/")
    except Exception:
        # Clear any partial session data on error
        session_keys_to_clear = [
            "osm_user_id",
            "osm_username",
            "osm_user_data",
            "osm_oauth_token",
            "is_authenticated",
        ]
        for key in session_keys_to_clear:
            request.session.pop(key, None)
        messages.error(request, "Authentication failed. Please try again.")
        return redirect("/")


def admin_login(request):
    """Custom admin login view with dev mode fallback"""

    # If user is already authenticated via OSM and has admin rights, redirect to admin
    if request.session.get("is_authenticated"):
        # Try to authenticate with Django's auth system using OSM backend
        user = authenticate(request=request)
        if user and user.is_staff:
            auth_login(request, user)
            next_url = request.GET.get("next", "/admin/")
            return redirect(next_url)
        elif user:
            messages.error(
                request, "You don't have permission to access the admin area."
            )
            return redirect("/")
    # In DEBUG mode with hardcoded admin enabled, use Django's built-in admin login
    if settings.DEBUG and getattr(settings, "ALLOW_HARDCODED_ADMIN", False):
        # Use Django's built-in LoginView with admin template
        login_view = LoginView.as_view(
            template_name="admin/login.html",
            success_url="/admin/",
            extra_context={
                "title": "Log in",
                "site_title": "Yesterdays Admin",
                "site_header": "Development Mode - Use admin/admin",
                "site_url": "/",
            },
        )
        return login_view(request)
    # Store the admin redirect in session so we can redirect back after OAuth
    request.session["admin_login_redirect"] = request.GET.get("next", "/admin/")
    # Redirect to OSM OAuth login
    messages.info(
        request,
        "Please log in with your OpenStreetMap account to access the admin area.",
    )
    return redirect("osm_auth:login")


def logout(request):
    """Log out user by clearing session and Django auth"""

    # Clear OSM-related session data
    session_keys_to_remove = [
        "osm_user_id",
        "osm_username",
        "osm_user_data",
        "osm_oauth_token",
        "is_authenticated",
    ]
    for key in session_keys_to_remove:
        if key in request.session:
            del request.session[key]
    # Also log out of Django's authentication system
    auth_logout(request)
    messages.success(request, "Successfully logged out!")
    return redirect("/")


def user_data(request):
    """API endpoint to get current user data"""
    if not request.session.get("is_authenticated"):
        return JsonResponse({"error": "Not authenticated"}, status=401)
    user_data = {
        "id": request.session.get("osm_user_id"),
        "username": request.session.get("osm_username"),
        "user_data": request.session.get("osm_user_data"),
        "is_authenticated": True,
    }
    return JsonResponse(user_data)


def profile(request):
    """Display user profile page"""
    if not request.session.get("is_authenticated"):
        messages.info(request, "Please log in to view your profile.")
        return redirect("/")
    context = {
        "user_data": request.session.get("osm_user_data"),
        "username": request.session.get("osm_username"),
    }
    return render(request, "auth/profile.html", context)


def user_profile(request, username):
    """Display public user profile page"""
    # Look up by first_name (OSM username) or by username for hardcoded_admin in DEBUG mode
    if settings.DEBUG and username == "hardcoded_admin":
        user = get_object_or_404(User, username="hardcoded_admin")
    else:
        user = get_object_or_404(User, first_name=username)
    # Get user's display name (from OSM first_name or username)
    display_name = (
        user.get_display_name() if hasattr(user, "get_display_name") else user.username
    )
    profile_url = user.get_profile_url() if hasattr(user, "get_profile_url") else None

    album_count = Album.objects.filter(owner=user).count()
    georeference_count = (
        Georeference.objects.filter(georeferenced_by=user).count()
        + AerialGeoreference.objects.filter(georeferenced_by=user).count()
    )

    context = {
        "profile_user": user,
        "display_name": display_name,
        "profile_url": profile_url,
        "album_count": album_count,
        "georeference_count": georeference_count,
    }
    return render(request, "auth/user_profile.html", context)


def user_albums_list(request, username):
    """Display list of user's albums"""

    # Look up by first_name (OSM username) or by username for hardcoded_admin in DEBUG mode
    if settings.DEBUG and username == "hardcoded_admin":
        user = get_object_or_404(User, username="hardcoded_admin")
    else:
        user = get_object_or_404(User, first_name=username)
    display_name = (
        user.get_display_name() if hasattr(user, "get_display_name") else user.username
    )
    # Get albums - show all if viewing own, only public if viewing others
    if request.user.is_authenticated and request.user == user:
        albums = Album.objects.filter(owner=user).order_by("-created_at")
        is_own_albums = True
    else:
        albums = Album.objects.filter(owner=user, public=True).order_by("-created_at")
        is_own_albums = False
    context = {
        "profile_user": user,
        "display_name": display_name,
        "albums": albums,
        "is_own_albums": is_own_albums,
    }
    return render(request, "auth/user_albums_list.html", context)
