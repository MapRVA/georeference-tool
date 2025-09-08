from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import User
from django.conf import settings
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


class OSMAuthBackend(BaseBackend):
    """
    Authentication backend that uses OpenStreetMap OAuth session data.

    This backend checks if the user has a valid OSM session and creates/updates
    a corresponding Django User object. Admin access is granted based on the
    OSM_ADMIN_USERNAMES whitelist.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Authenticate using OSM session data.

        This method is called by Django's authentication system. Since we use
        session-based OSM authentication, we ignore the username/password
        parameters and check the session instead.
        """
        if not request or not hasattr(request, "session"):
            return None

        # Check if user has valid OSM session
        if not request.session.get("is_authenticated"):
            return None

        osm_username = request.session.get("osm_username")
        osm_user_id = request.session.get("osm_user_id")

        if not osm_username or not osm_user_id:
            logger.warning("OSM session missing username or user_id")
            return None

        try:
            # Get or create Django user based on OSM data
            user, created = User.objects.get_or_create(
                username=f"osm_{osm_user_id}",  # Prefix to avoid conflicts
                defaults={
                    "first_name": osm_username,
                    "email": f"{osm_username}@osm.local",  # Placeholder email
                    "is_active": True,
                },
            )

            # Update user info on each login
            user.first_name = osm_username

            # Check if user should have admin access
            is_admin = osm_username in settings.OSM_ADMIN_USERNAMES
            user.is_staff = is_admin
            user.is_superuser = is_admin

            # Update last login time
            user.last_login = timezone.now()
            user.save()

            if created:
                logger.info(
                    f"Created new Django user for OSM user: {osm_username} (ID: {osm_user_id})"
                )

            if is_admin:
                logger.info(f"Granted admin access to OSM user: {osm_username}")

            return user

        except Exception as e:
            logger.error(
                f"Error creating/updating user for OSM user {osm_username}: {e}"
            )
            return None

    def get_user(self, user_id):
        """Get user by ID."""
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


class HardcodedAdminBackend(BaseBackend):
    """
    Development-only authentication backend that allows admin/admin login.

    This backend only works when:
    - DEBUG mode is enabled
    - ALLOW_HARDCODED_ADMIN setting is True

    It's designed as a fallback for development when OSM OAuth isn't configured
    or when you need emergency admin access.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        """Authenticate using hardcoded admin credentials."""
        # Only work in DEBUG mode with explicit setting
        if not settings.DEBUG or not settings.ALLOW_HARDCODED_ADMIN:
            return None

        # Only allow the specific dev credentials
        if username != "admin" or password != "admin":
            return None

        try:
            # Get or create the hardcoded admin user
            user, created = User.objects.get_or_create(
                username="hardcoded_admin",
                defaults={
                    "email": "admin@localhost",
                    "is_active": True,
                    "is_staff": True,
                    "is_superuser": True,
                    "first_name": "Hardcoded Admin",
                },
            )

            # Ensure admin privileges (in case settings changed)
            if not user.is_staff or not user.is_superuser:
                user.is_staff = True
                user.is_superuser = True
                user.save()

            user.last_login = timezone.now()
            user.save()

            if created:
                logger.warning(
                    "Created hardcoded admin user - THIS IS FOR DEVELOPMENT ONLY!"
                )
            else:
                logger.info("Authenticated with hardcoded admin credentials")

            return user

        except Exception as e:
            logger.error(f"Error with hardcoded admin authentication: {e}")
            return None

    def get_user(self, user_id):
        """Get user by ID."""
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


def create_osm_user_from_session(request):
    """
    Helper function to create a Django User from OSM session data.

    This can be called after successful OSM OAuth login to ensure
    a Django User exists for the authenticated OSM user.
    """
    if not request.session.get("is_authenticated"):
        return None

    osm_username = request.session.get("osm_username")
    osm_user_id = request.session.get("osm_user_id")

    if not osm_username or not osm_user_id:
        return None

    backend = OSMAuthBackend()
    return backend.authenticate(request)
