import re

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils.translation import gettext_lazy as _

from tracker.forms import BootstrapMixin

from .models import User

ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


class SignupForm(BootstrapMixin, UserCreationForm):
    class Meta:
        model = User
        fields = ["email", "full_name", "affiliation", "country"]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_("An account with this email already exists."))
        return email


class ProfileForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["full_name", "full_name_ar", "title", "affiliation", "department", "country", "orcid",
                  "scholar_url", "phone", "is_external", "preferred_language", "email_reminders", "weekly_digest"]

    def clean_orcid(self):
        v = self.cleaned_data["orcid"].strip().replace("https://orcid.org/", "")
        if v and not ORCID_RE.match(v):
            raise forms.ValidationError(_("ORCID must look like 0000-0002-1825-0097"))
        return v
