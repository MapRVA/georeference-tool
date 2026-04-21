from django.http import HttpResponse, HttpResponseBadRequest
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from oauth2_provider.compat import login_not_required
from oauth2_provider.views import AuthorizationView, TokenView

from api.throttling import TokenExchangeThrottle


class S256OnlyAuthorizationView(AuthorizationView):
    """Authorization view that requires PKCE with code_challenge_method=S256.

    DOT/oauthlib accept the 'plain' method (and silently default to it if
    code_challenge_method is omitted), which negates PKCE's protection: an
    attacker who intercepts the authorization code can use the challenge
    directly as the verifier. Enforced on both GET (initial request) and
    POST (consent submission) since the latter carries the method back as
    a hidden form field that a malicious client could alter.
    """

    def dispatch(self, request, *args, **kwargs):
        if request.method == "POST":
            method = request.POST.get("code_challenge_method")
        else:
            method = request.GET.get("code_challenge_method")
        if method != "S256":
            return HttpResponseBadRequest(
                "code_challenge_method=S256 is required."
            )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        scopes = context.get("scopes") or []
        descriptions = context.get("scopes_descriptions") or []
        context["scope_pairs"] = list(zip(scopes, descriptions))
        return context


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
