from django.conf import settings
from django.db import models
from oauth2_provider.scopes import get_scopes_backend
from oauth2_provider.settings import oauth2_settings


class ApplicationConsent(models.Model):
    """Remembers that a user approved an OAuth application for a set of scopes.

    django-oauth-toolkit only skips the consent screen while the user still
    holds an unexpired access token, so clients would otherwise re-prompt on
    every login. S256OnlyAuthorizationView consults this record instead: the
    consent screen appears the first time an application requests
    authorization (or when it requests scopes beyond those already granted)
    and is skipped afterwards, until the user revokes the application from
    their settings.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="oauth_consents",
    )
    application = models.ForeignKey(
        oauth2_settings.APPLICATION_MODEL,
        on_delete=models.CASCADE,
        related_name="consents",
    )
    scope = models.TextField(
        blank=True,
        default="",
        help_text="Space-separated scopes the user has granted.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "application"],
                name="unique_consent_per_user_application",
            )
        ]

    def __str__(self):
        return f"{self.user} → {self.application}"

    def allow_scopes(self, scopes):
        """True if every requested scope was previously granted.

        Mirrors AbstractAccessToken.allow_scopes so consents and tokens can
        be checked interchangeably.
        """
        if not scopes:
            return True
        return set(scopes).issubset(set(self.scope.split()))

    def grant_scopes(self, scopes):
        """Merge newly approved scopes into the stored grant (unsaved)."""
        self.scope = " ".join(sorted(set(self.scope.split()) | set(scopes)))

    @property
    def scopes(self):
        """Granted scope names mapped to their descriptions.

        Mirrors AbstractAccessToken.scopes, which the authorized-applications
        template originally rendered.
        """
        all_scopes = get_scopes_backend().get_all_scopes()
        granted = self.scope.split()
        return {name: desc for name, desc in all_scopes.items() if name in granted}
