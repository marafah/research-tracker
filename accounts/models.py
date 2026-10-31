import secrets

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra["is_staff"] = True
        extra["is_superuser"] = True
        return self._create_user(email, password, **extra)


def _token():
    return secrets.token_urlsafe(32)


class User(AbstractUser):
    """A researcher. Logs in with email. May be internal or external to the university."""

    username = None
    email = models.EmailField(_("email"), unique=True)
    full_name = models.CharField(_("full name (English)"), max_length=200, blank=True)
    full_name_ar = models.CharField(_("full name (Arabic)"), max_length=200, blank=True)
    title = models.CharField(_("academic title"), max_length=100, blank=True,
                             help_text=_("e.g. Assistant Professor, PhD Student"))
    affiliation = models.CharField(_("affiliation"), max_length=300, blank=True)
    department = models.CharField(_("department"), max_length=200, blank=True)
    country = models.CharField(_("country"), max_length=100, blank=True)
    orcid = models.CharField(_("ORCID iD"), max_length=19, blank=True,
                             help_text=_("Format: 0000-0000-0000-0000"))
    scholar_url = models.URLField(_("Google Scholar profile"), blank=True)
    phone = models.CharField(_("phone / WhatsApp"), max_length=30, blank=True)
    is_external = models.BooleanField(_("external collaborator"), default=False,
                                      help_text=_("From outside the home university"))
    preferred_language = models.CharField(_("language"), max_length=5, default="en",
                                          choices=[("en", "English"), ("ar", "العربية")])
    email_reminders = models.BooleanField(_("receive deadline reminders"), default=True)
    weekly_digest = models.BooleanField(_("receive weekly digest"), default=True)
    calendar_token = models.CharField(max_length=64, default=_token, unique=True, editable=False)
    last_digest_at = models.DateTimeField(null=True, blank=True, editable=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return self.full_name or self.get_full_name() or self.email

    @property
    def profile_complete(self):
        """Fields journals usually require from every co-author."""
        return all([self.full_name, self.affiliation, self.country, self.email])

    def missing_profile_fields(self):
        labels = {
            "full_name": _("full name"),
            "affiliation": _("affiliation"),
            "country": _("country"),
            "orcid": _("ORCID iD"),
        }
        return [str(label) for f, label in labels.items() if not getattr(self, f)]

    def reset_calendar_token(self):
        self.calendar_token = _token()
        self.save(update_fields=["calendar_token"])
