from django.contrib.auth.models import User
from django.conf import settings
from django.db import models


def get_display_name(self):
    """
    Get the display name for the user.

    For OSM users, this returns the OSM username stored in first_name.
    For hardcoded admin users, it returns a friendly name.
    Falls back to the Django username if no first_name is set.
    """
    if self.first_name:
        return self.first_name
    elif self.username == "hardcoded_admin":
        return "Admin (Dev Mode)"
    else:
        # Fallback to username, but clean it up if it's an OSM ID
        if self.username.startswith("osm_"):
            return f"User {self.username[4:]}"  # Remove 'osm_' prefix
        return self.username


def get_profile_url(self):
    """
    Get the OSM profile URL for the user.

    For OSM users, this returns a link to their OSM profile page.
    Returns None for hardcoded admin users or users without OSM usernames.
    """
    # Don't return profile URLs for hardcoded admin users
    if self.username == "hardcoded_admin":
        return None

    # For OSM users, use the OSM username stored in first_name
    if self.first_name:
        osm_url = getattr(settings, "OSM_URL", "https://www.openstreetmap.org")
        return f"{osm_url}/user/{self.first_name}"

    return None


def get_profile_picture_url(self):
    """Return the mirrored R2 profile picture URL, or None if not yet stored."""
    profile = UserProfile.objects.filter(user=self).first()
    if profile and profile.profile_picture_url:
        return profile.profile_picture_url
    return None


# Add the methods to the User model
User.add_to_class("get_display_name", get_display_name)
User.add_to_class("get_profile_url", get_profile_url)
User.add_to_class("get_profile_picture_url", get_profile_picture_url)


class UserPreferences(models.Model):
    class ContextImagesDisplay(models.TextChoices):
        HIDDEN = "hidden", "Hidden"
        GHOST = "ghost", "Ghost"
        CLICKABLE = "clickable", "Clickable with popups"

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    georef_show_centerline = models.BooleanField(
        default=False,
        verbose_name="show centerline by default",
    )
    georef_context_images = models.CharField(
        max_length=16,
        choices=ContextImagesDisplay.choices,
        default=ContextImagesDisplay.GHOST,
        verbose_name="context image display",
    )

    def __str__(self):
        return f"Preferences for {self.user.get_display_name()}"


class UserProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    profile_picture_url = models.URLField(blank=True)

    def __str__(self):
        return f"Profile for {self.user.get_display_name()}"
