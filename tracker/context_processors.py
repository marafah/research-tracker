from django.conf import settings
from django.db.models import Q
from django.utils import timezone


def site(request):
    from django.utils.translation import get_language
    ar = (get_language() or "").startswith("ar")
    ctx = {"SITE_NAME": settings.SITE_NAME, "ALLOW_SIGNUP": settings.ALLOW_SIGNUP,
           "INSTITUTION": (settings.INSTITUTION_NAME_AR if ar else settings.INSTITUTION_NAME) or settings.INSTITUTION_NAME,
           "INSTITUTION_UNIT": (settings.INSTITUTION_UNIT_AR if ar else settings.INSTITUTION_UNIT) or settings.INSTITUTION_UNIT}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        from .models import Deadline
        from .permissions import visible_papers
        mine = (Deadline.objects.filter(paper__in=visible_papers(user), completed_at__isnull=True)
                .filter(Q(assignees=user) | Q(paper__lead=user)).distinct())
        ctx["nav_overdue"] = mine.filter(due_at__lt=timezone.now()).count()
        ctx["nav_open_deadlines"] = mine.count()
    return ctx
