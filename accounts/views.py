from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.i18n import set_language as django_set_language

from .forms import ProfileForm, SignupForm


def signup(request):
    if not settings.ALLOW_SIGNUP:
        raise Http404
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        lang = (request.LANGUAGE_CODE or "en")[:2]
        user.preferred_language = lang if lang in ("ar", "en") else "en"
        user.save()
        login(request, user, backend="accounts.backends.EmailBackend")
        messages.success(request, _("Account created. Welcome!"))
        return redirect("dashboard")
    return render(request, "registration/signup.html", {"form": form})


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST":
        if "reset_calendar" in request.POST:
            request.user.reset_calendar_token()
            messages.success(request, _("Calendar link regenerated. The old link no longer works."))
            return redirect("profile")
        if form.is_valid():
            form.save()
            messages.success(request, _("Profile saved."))
            return redirect("profile")
    from django.urls import reverse
    cal_url = settings.SITE_URL + reverse("calendar_feed", args=[request.user.calendar_token])
    return render(request, "accounts/profile.html", {"form": form, "calendar_url": cal_url})


@require_POST
def set_language(request):
    lang = request.POST.get("language", "en")
    if request.user.is_authenticated and lang in ("ar", "en"):
        request.user.preferred_language = lang
        request.user.save(update_fields=["preferred_language"])
    nxt = request.POST.get("next", "/")
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        request.POST = request.POST.copy()
        request.POST["next"] = "/"
    return django_set_language(request)
