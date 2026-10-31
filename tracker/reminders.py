"""Email reminder engine.

Safe to run as often as you like (every hour is ideal): every email sent is
recorded in ReminderLog, so nobody is ever emailed twice for the same reminder.

Rules
-----
* Before the deadline: one email at each configured offset (default 14,7,3,1,0
  days before). If the scheduler missed a day, the reminder is caught up the next day.
* After the deadline: a daily "overdue" email for 7 days, then weekly.
  On the first overdue day the group owners/admins are also alerted (escalation).
* Weekly digest: each user's next 14 days, overdue items and open reviewer comments.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import Deadline, GroupMembership, Paper, ReminderLog, ReviewComment
from .services import send_templated_email


def _claim(deadline, user, key):
    """Atomically mark a reminder as sent; returns False if it was already sent."""
    try:
        ReminderLog.objects.create(deadline=deadline, user=user, key=key)
        return True
    except IntegrityError:
        return False


def reminder_key(deadline, today=None):
    today = today or timezone.localdate()
    days_left = (timezone.localtime(deadline.due_at).date() - today).days
    if days_left < 0:
        overdue = -days_left
        if overdue <= 7 or overdue % 7 == 0:
            return f"overdue-{today.isoformat()}", days_left
        return None, days_left
    candidates = [o for o in deadline.reminder_offsets() if o >= days_left]
    if not candidates:
        return None, days_left
    offset = min(candidates)
    if offset - days_left > 1:  # too far past this offset — don't send a stale reminder
        return None, days_left
    return f"d{offset}", days_left


def run_reminders(stdout=None):
    sent = 0
    open_deadlines = (Deadline.objects.filter(completed_at__isnull=True)
                      .exclude(paper__status__in=Paper.CLOSED)
                      .select_related("paper", "paper__group", "paper__lead")
                      .prefetch_related("assignees"))
    for dl in open_deadlines:
        key, days_left = reminder_key(dl)
        if not key:
            continue
        recipients = set(dl.recipients())
        escalate = key.startswith("overdue") and days_left == -1
        if escalate:
            managers = [m.user for m in dl.paper.group.memberships.select_related("user")
                        if m.role in (GroupMembership.Role.OWNER, GroupMembership.Role.ADMIN)
                        and m.user.is_active and m.user.email_reminders]
            recipients.update(managers)
        for user in recipients:
            if not _claim(dl, user, key):
                continue
            if days_left < 0:
                subject = _("OVERDUE: %(title)s") % {"title": dl.title}
            elif days_left == 0:
                subject = _("Due TODAY: %(title)s") % {"title": dl.title}
            else:
                subject = _("%(days)s days left: %(title)s") % {"days": days_left, "title": dl.title}
            sent += send_templated_email(
                user.email, subject, "deadline_reminder",
                {"deadline": dl, "user": user, "paper": dl.paper, "days_left": days_left,
                 "overdue_days": -days_left},
                user.preferred_language,
            )
    if stdout:
        stdout.write(f"Reminders sent: {sent}")
    return sent


def run_digest(force=False, stdout=None):
    User = get_user_model()
    now = timezone.now()
    horizon = now + timedelta(days=14)
    sent = 0
    for user in User.objects.filter(is_active=True, weekly_digest=True):
        if not force and user.last_digest_at and now - user.last_digest_at < timedelta(days=6):
            continue
        dls = (Deadline.objects.filter(completed_at__isnull=True, due_at__lte=horizon)
               .filter(Q(assignees=user) | Q(paper__lead=user)).distinct()
               .select_related("paper").order_by("due_at"))
        comments = ReviewComment.objects.filter(
            assigned_to=user, state__in=[ReviewComment.State.OPEN, ReviewComment.State.IN_PROGRESS]
        ).select_related("submission__paper")
        action = Paper.objects.filter(
            Q(lead=user) | Q(authors__user=user), status__in=Paper.ACTION_NEEDED
        ).distinct()
        if not dls and not comments and not action:
            continue
        sent += send_templated_email(
            user.email, _("Your weekly research summary"), "weekly_digest",
            {"user": user, "deadlines": dls, "comments": comments, "action_papers": action},
            user.preferred_language,
        )
        user.last_digest_at = now
        user.save(update_fields=["last_digest_at"])
    if stdout:
        stdout.write(f"Digests sent: {sent}")
    return sent
