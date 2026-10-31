from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    """Case-insensitive email login."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        email = (kwargs.get("email") or username or "").strip().lower()
        return super().authenticate(request, username=email, password=password, **kwargs)
