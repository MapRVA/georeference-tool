from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, HttpResponseBadRequest
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import DeleteView, ListView
from oauth2_provider.compat import login_not_required
from oauth2_provider.exceptions import OAuthToolkitError
from oauth2_provider.models import (
    get_access_token_model,
    get_application_model,
    get_refresh_token_model,
)
from oauth2_provider.views import AuthorizationView, TokenView

from api.models import ApplicationConsent
from api.throttling import TokenExchangeThrottle


class S256OnlyAuthorizationView(AuthorizationView):
    """Authorization view that requires PKCE with code_challenge_method=S256.

    DOT/oauthlib accept the 'plain' method (and silently default to it if
    code_challenge_method is omitted), which negates PKCE's protection: an
    attacker who intercepts the authorization code can use the challenge
    directly as the verifier. Enforced on both GET (initial request) and
    POST (consent submission) since the latter carries the method back as
    a hidden form field that a malicious client could alter.

    Also remembers consent: DOT's own auto-approval (approval_prompt=auto)
    only lasts as long as an unexpired access token, so users would be
    re-prompted on every login. Instead, approving the consent form records
    an ApplicationConsent, and later authorization requests covered by that
    record are approved without showing the form — regardless of token
    expiry or revocation — until the user revokes the application from
    their settings. Clients can pass approval_prompt=force to re-prompt.
    """

    def dispatch(self, request, *args, **kwargs):
        if request.method == "POST":
            method = request.POST.get("code_challenge_method")
        else:
            method = request.GET.get("code_challenge_method")
        if method != "S256":
            return HttpResponseBadRequest("code_challenge_method=S256 is required.")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        scopes = context.get("scopes") or []
        descriptions = context.get("scopes_descriptions") or []
        context["scope_pairs"] = list(zip(scopes, descriptions))
        return context

    def render_to_response(self, context, **response_kwargs):
        """Skip the consent form when a remembered consent covers the request.

        AuthorizationView.get() only reaches render_to_response after its own
        auto-approval checks (skip_authorization, approval_prompt=auto)
        declined, so this is the last stop before the form would be shown.
        The guards exclude the other callers: error responses carry an
        "error" key, and POST paths (form_invalid) leave oauth2_data empty.
        """
        application = self.oauth2_data.get("application")
        scopes = self.oauth2_data.get("scopes", [])
        if (
            "error" not in context
            and application is not None
            and self.request.user.is_authenticated
            and self.request.GET.get("approval_prompt") != "force"
        ):
            consent = ApplicationConsent.objects.filter(
                user=self.request.user, application=application
            ).first()
            if consent is not None and consent.allow_scopes(scopes):
                credentials = {
                    "client_id": self.oauth2_data.get("client_id"),
                    "redirect_uri": self.oauth2_data.get("redirect_uri"),
                    "response_type": self.oauth2_data.get("response_type"),
                    "state": self.oauth2_data.get("state"),
                }
                for key in ("code_challenge", "code_challenge_method", "nonce"):
                    if key in self.oauth2_data:
                        credentials[key] = self.oauth2_data[key]
                try:
                    uri, headers, body, status = self.create_authorization_response(
                        request=self.request,
                        scopes=" ".join(scopes),
                        credentials=credentials,
                        allow=True,
                    )
                except OAuthToolkitError as error:
                    return self.error_response(error, application)
                return self.redirect(uri, application)
        return super().render_to_response(context, **response_kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        # DOT sets success_url only when the grant was actually issued;
        # denials and errors redirect without setting it.
        if form.cleaned_data.get("allow") and getattr(self, "success_url", None):
            application = get_application_model().objects.get(
                client_id=form.cleaned_data["client_id"]
            )
            consent, _ = ApplicationConsent.objects.get_or_create(
                user=self.request.user, application=application
            )
            consent.grant_scopes(form.cleaned_data.get("scope", "").split())
            consent.save()
        return response


class AuthorizedApplicationsView(LoginRequiredMixin, ListView):
    """Replaces DOT's AuthorizedTokensListView, listing remembered consents
    rather than access tokens so authorized applications stay visible (and
    revocable) after their short-lived tokens expire.
    """

    context_object_name = "consents"
    template_name = "oauth2_provider/authorized-tokens.html"
    model = ApplicationConsent

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("application")
            .filter(user=self.request.user)
            .order_by("application__name")
        )


class RevokeApplicationConsentView(LoginRequiredMixin, DeleteView):
    """Replaces DOT's AuthorizedTokenDeleteView. Deleting the consent record
    re-enables the consent screen for future authorization requests, and all
    of the application's tokens are revoked so it loses access immediately.
    """

    template_name = "oauth2_provider/authorized-token-delete.html"
    success_url = reverse_lazy("oauth2_provider:authorized-token-list")
    model = ApplicationConsent

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("application")
            .filter(user=self.request.user)
        )

    def form_valid(self, form):
        consent = self.object
        # RefreshToken.revoke() also deletes its paired access token; the
        # bulk delete afterwards catches access tokens with no refresh token.
        refresh_tokens = get_refresh_token_model().objects.filter(
            user=consent.user,
            application=consent.application,
            revoked__isnull=True,
        )
        for refresh_token in refresh_tokens:
            refresh_token.revoke()
        get_access_token_model().objects.filter(
            user=consent.user, application=consent.application
        ).delete()
        return super().form_valid(form)


@method_decorator(csrf_exempt, name="dispatch")
@method_decorator(login_not_required, name="dispatch")
class ThrottledTokenView(TokenView):
    """TokenView with IP-based rate limiting for DoS protection.

    The csrf_exempt and login_not_required decorators must be re-applied
    here: DOT applies them to TokenView.dispatch via @method_decorator on
    the class, but overriding dispatch in this subclass replaces the
    decorated method with an undecorated one.
    """

    def dispatch(self, request, *args, **kwargs):
        throttle = TokenExchangeThrottle()
        if not throttle.allow_request(request, self):
            response = HttpResponse(
                "Too many token requests. Please try again later.",
                status=429,
                content_type="text/plain",
            )
            response["Retry-After"] = str(int(throttle.wait() or 60))
            return response
        return super().dispatch(request, *args, **kwargs)
