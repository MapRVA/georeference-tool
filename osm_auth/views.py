import json
from django.conf import settings
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login as auth_login
from django.contrib.admin.views.decorators import staff_member_required
from osm_login_python.core import Auth


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

    except Exception as e:
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

        messages.error(request, f"Authentication failed. Please try again.")
        return redirect("/")


def admin_login(request):
    """Custom admin login view with dev mode fallback"""
    from django.contrib.auth.views import LoginView

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
    if settings.DEBUG and getattr(settings, 'ALLOW_HARDCODED_ADMIN', False):
        # Use Django's built-in LoginView with admin template
        login_view = LoginView.as_view(
            template_name='admin/login.html',
            success_url='/admin/',
            extra_context={
                'title': 'Log in',
                'site_title': 'Georeference Tool Admin',
                'site_header': 'Development Mode - Use admin/admin',
                'site_url': '/',
            }
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
    """Log out user by clearing session"""
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
