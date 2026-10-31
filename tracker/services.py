"""Business rules kept out of views so they are easy to test and reuse."""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone, translation

from .models import Activity, Deadline, Paper, Submission, SubmissionEvent

log = logging.getLogger(__name__)


def log_activity(user, verb, paper=None, group=None):
    Activity.objects.create(user=user, verb=verb[:200], paper=paper, group=group or (paper.group if paper else None))


def send_templated_email(to, subject, template, context, language="en"):
    """Render `emails/<template>.txt` + `.html` in the recipient's language and send."""
    if not to:
        return 0
    with translation.override(language):
        ctx = {"SITE_URL": settings.SITE_URL, "SITE_NAME": settings.SITE_NAME, **context}
        text = render_to_string(f"emails/{template}.txt", ctx)
        html = render_to_string(f"emails/{template}.html", ctx)
        subject = f"[{settings.SITE_NAME}] {subject}"
    msg = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, to if isinstance(to, list) else [to])
    msg.attach_alternative(html, "text/html")
    try:
        return msg.send()
    except Exception:  # never crash a request because SMTP is down
        log.exception("Email to %s failed", to)
        return 0


def apply_submission_change(submission: Submission, user, previous_decision=None, note=""):
    """Keep paper status, timeline and deadlines consistent after a submission is saved."""
    paper = submission.paper
    now = timezone.now()
    changed = previous_decision != submission.decision

    if changed:
        SubmissionEvent.objects.create(
            submission=submission, decision=submission.decision, note=note, recorded_by=user,
            happened_at=submission.submitted_at if submission.decision == Submission.Decision.SUBMITTED
            and submission.submitted_at else now,
        )
        decided = (Submission.Decision.MAJOR, Submission.Decision.MINOR, Submission.Decision.ACCEPTED,
                   Submission.Decision.REJECTED, Submission.Decision.DESK_REJECTED, Submission.Decision.TRANSFER)
        update = []
        if submission.decision in decided:
            submission.last_decision_at = now
            update.append("last_decision_at")
            if not submission.first_decision_at:
                submission.first_decision_at = now
                update.append("first_decision_at")
        if submission.decision == Submission.Decision.ACCEPTED and not submission.accepted_at:
            submission.accepted_at = now
            update.append("accepted_at")
        if submission.decision == Submission.Decision.REVISION_SUBMITTED:
            submission.round += 1
            update.append("round")
            # The revision is in; close the open revision deadline.
            submission.deadlines.filter(kind=Deadline.Kind.REVISION, completed_at__isnull=True).update(
                completed_at=now, completed_by=user)
        if update:
            submission.save(update_fields=update)

        new_status = Submission.DECISION_TO_STATUS.get(submission.decision)
        if new_status and paper.status != new_status:
            paper.status = new_status
            paper.save(update_fields=["status", "updated_at"])
        log_activity(user, f"{submission.journal.name}: {submission.get_decision_display()}", paper)

    # Revision due date → a tracked deadline with reminders.
    if submission.revision_due_at:
        dl = submission.deadlines.filter(kind=Deadline.Kind.REVISION, completed_at__isnull=True).first()
        if dl is None and submission.decision in (Submission.Decision.MAJOR, Submission.Decision.MINOR):
            dl = Deadline.objects.create(
                paper=paper, submission=submission, kind=Deadline.Kind.REVISION,
                title=f"{submission.get_decision_display()} — {submission.journal.name}",
                due_at=submission.revision_due_at, created_by=user,
            )
            if paper.lead:
                dl.assignees.add(paper.lead)
            notify_new_deadline(dl)
        elif dl and dl.due_at != submission.revision_due_at:
            dl.due_at = submission.revision_due_at
            dl.save(update_fields=["due_at"])
            dl.reminder_logs.all().delete()  # date moved → reminders restart


def notify_new_deadline(deadline: Deadline):
    for user in deadline.recipients():
        send_templated_email(
            user.email, f"{deadline.title}", "deadline_created",
            {"deadline": deadline, "user": user, "paper": deadline.paper}, user.preferred_language,
        )


def status_counts(papers):
    """[(code, label, count), …] in pipeline order, zero rows skipped."""
    raw = {}
    for st in papers.values_list("status", flat=True):
        raw[st] = raw.get(st, 0) + 1
    total = sum(raw.values()) or 1
    return [{"code": c, "label": label, "count": raw[c], "pct": round(100 * raw[c] / total)}
            for c, label in Paper.Status.choices if raw.get(c)]
