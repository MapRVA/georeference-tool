from rest_framework.permissions import BasePermission


def is_importer(request):
    """Return True if the request is from a staff user with import capability.

    Mirrors ``IsImporter.has_permission``: session auth only needs staff;
    OAuth auth also needs the ``import`` scope on the token.
    """
    if not request.user or not request.user.is_authenticated:
        return False
    if not request.user.is_staff:
        return False
    if hasattr(request, "auth") and hasattr(request.auth, "scope"):
        return "import" in request.auth.scope.split()
    return True


class IsImporter(BasePermission):
    """Require the user to be staff (admin) with the 'import' OAuth scope.

    For session-authenticated requests (e.g. from the web UI), only the
    ``is_staff`` check applies.  For OAuth-authenticated requests, the token
    must also carry the ``import`` scope.
    """

    def has_permission(self, request, view):
        return is_importer(request)
