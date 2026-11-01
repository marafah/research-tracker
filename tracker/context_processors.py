from django.conf import settings
from django.db.models import Q
from django.utils import timezone


def site(request):
    ctx = {"SITE_NAME": settings.SITE_NAME, "ALLOW_SIGNUP": settings.ALLOW_SIGNUP}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        from .models import Deadline
        from .permissions import visible_papers
        mine = (Deadline.objects.filter(paper__in=visible_papers(user), completed_at__isnull=True)
                .filter(Q(assignees=user) | Q(paper__lead=user)).distinct())
        ctx["nav_overdue"] = mine.filter(due_at__lt=timezone.now()).count()
        ctx["nav_open_deadlines"] = mine.count()
    return ctx
