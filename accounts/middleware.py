from django.utils import translation


class UserLanguageMiddleware:
    """Activate the logged-in user's preferred language (overrides browser default).

    A language explicitly chosen in the session/cookie via the switcher still wins
    because the switcher also updates the user's preference.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.preferred_language:
            translation.activate(user.preferred_language)
            request.LANGUAGE_CODE = user.preferred_language
        return self.get_response(request)
