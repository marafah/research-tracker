"""
Core data model.

  ResearchGroup ─┬─ GroupMembership (role) ── User
                 ├─ Invitation
                 └─ Paper ─┬─ PaperAuthor (order, corresponding, CRediT, consent)
                           ├─ Submission (one per journal attempt) ─ ReviewComment
                           ├─ Deadline ─ ReminderLog
                           ├─ Attachment
                           └─ Activity (audit trail)

A *Paper* is the research work. A *Submission* is one attempt to publish it in
one venue. Rejected? Create a new Submission to another journal; the history
of the first one is kept.
"""
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

User = settings.AUTH_USER_MODEL


# ---------------------------------------------------------------------------
# Groups & access
# ---------------------------------------------------------------------------
class ResearchGroup(models.Model):
    name = models.CharField(_("name"), max_length=200)
    description = models.TextField(_("description"), blank=True)
    institution = models.CharField(_("institution"), max_length=200, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    members = models.ManyToManyField(User, through="GroupMembership", related_name="research_groups")

    class Meta:
        ordering = ["name"]
        verbose_name = _("research group")
        verbose_name_plural = _("research groups")

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("group_detail", args=[self.pk])

    def role_of(self, user):
        m = self.memberships.filter(user=user).first()
        return m.role if m else None


class GroupMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", _("Owner")
        ADMIN = "admin", _("Admin")
        MEMBER = "member", _("Member")
        EXTERNAL = "external", _("External collaborator")

    group = models.ForeignKey(ResearchGroup, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(_("role"), max_length=10, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("group", "user")]
        verbose_name = _("membership")

    def __str__(self):
        return f"{self.user} @ {self.group} ({self.role})"

    @property
    def is_manager(self):
        return self.role in (self.Role.OWNER, self.Role.ADMIN)


def _invite_token():
    return secrets.token_urlsafe(32)


def _invite_expiry():
    return timezone.now() + timedelta(days=14)


class Invitation(models.Model):
    group = models.ForeignKey(ResearchGroup, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField(_("email"))
    role = models.CharField(_("role"), max_length=10, choices=GroupMembership.Role.choices,
                            default=GroupMembership.Role.MEMBER)
    message = models.TextField(_("personal message"), blank=True)
    token = models.CharField(max_length=64, unique=True, default=_invite_token, editable=False)
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_invite_expiry)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email} → {self.group}"

    @property
    def is_valid(self):
        return self.accepted_at is None and self.expires_at > timezone.now()

    def get_accept_url(self):
        return settings.SITE_URL + reverse("invitation_accept", args=[self.token])


# ---------------------------------------------------------------------------
# Venues
# ---------------------------------------------------------------------------
class Journal(models.Model):
    class Kind(models.TextChoices):
        JOURNAL = "journal", _("Journal")
        CONFERENCE = "conference", _("Conference")
        BOOK = "book", _("Book / Book series")
        FUNDER = "funder", _("Funding agency")

    class Quartile(models.TextChoices):
        Q1 = "Q1", "Q1"
        Q2 = "Q2", "Q2"
        Q3 = "Q3", "Q3"
        Q4 = "Q4", "Q4"
        NA = "", _("N/A")

    name = models.CharField(_("name"), max_length=300)
    kind = models.CharField(_("type"), max_length=12, choices=Kind.choices, default=Kind.JOURNAL)
    publisher = models.CharField(_("publisher"), max_length=200, blank=True,
                                 help_text=_("e.g. Elsevier, IEEE, Springer, MDPI, ACM"))
    issn = models.CharField("ISSN", max_length=20, blank=True)
    eissn = models.CharField("e-ISSN", max_length=20, blank=True)
    website = models.URLField(_("website"), blank=True)
    submission_portal = models.URLField(_("submission portal"), blank=True)
    quartile = models.CharField(_("quartile"), max_length=2, choices=Quartile.choices, blank=True)
    impact_factor = models.DecimalField(_("impact factor"), max_digits=6, decimal_places=3, null=True, blank=True)
    indexed_scopus = models.BooleanField(_("Scopus"), default=False)
    indexed_wos = models.BooleanField(_("Web of Science"), default=False)
    open_access = models.BooleanField(_("open access"), default=False)
    apc_amount = models.DecimalField(_("APC amount"), max_digits=10, decimal_places=2, null=True, blank=True)
    apc_currency = models.CharField(_("currency"), max_length=3, default="USD", blank=True)
    flagged = models.BooleanField(_("flagged as questionable"), default=False,
                                  help_text=_("Mark journals suspected to be predatory"))
    notes = models.TextField(_("notes"), blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["name"]
        verbose_name = _("journal / venue")
        verbose_name_plural = _("journals / venues")

    def __str__(self):
        return f"{self.name} ({self.publisher})" if self.publisher else self.name

    def get_absolute_url(self):
        return reverse("journal_detail", args=[self.pk])

    @property
    def indexing(self):
        parts = []
        if self.indexed_scopus:
            parts.append("Scopus")
        if self.indexed_wos:
            parts.append("WoS")
        return " · ".join(parts)

    def stats(self):
        subs = self.submissions.exclude(submitted_at__isnull=True)
        decided = subs.filter(first_decision_at__isnull=False)
        days = [(s.first_decision_at - s.submitted_at).days for s in decided]
        accepted = subs.filter(decision=Submission.Decision.ACCEPTED).count()
        rejected = subs.filter(decision__in=[Submission.Decision.REJECTED, Submission.Decision.DESK_REJECTED]).count()
        return {
            "total": subs.count(),
            "accepted": accepted,
            "rejected": rejected,
            "avg_first_decision_days": round(sum(days) / len(days)) if days else None,
        }


# ---------------------------------------------------------------------------
# Papers
# ---------------------------------------------------------------------------
class Paper(models.Model):
    class Type(models.TextChoices):
        JOURNAL = "journal", _("Journal article")
        CONFERENCE = "conference", _("Conference paper")
        CHAPTER = "chapter", _("Book chapter")
        REVIEW = "review", _("Review / Survey")
        PROPOSAL = "proposal", _("Research / grant proposal")
        THESIS = "thesis", _("Thesis supervision")
        OTHER = "other", _("Other")

    class Status(models.TextChoices):
        IDEA = "idea", _("Idea")
        PROPOSAL = "proposal", _("Proposal")
        DRAFTING = "drafting", _("Drafting")
        INTERNAL_REVIEW = "internal_review", _("Internal review")
        READY = "ready", _("Ready to submit")
        SUBMITTED = "submitted", _("Submitted")
        UNDER_REVIEW = "under_review", _("Under review")
        MAJOR_REVISION = "major_revision", _("Major revision")
        MINOR_REVISION = "minor_revision", _("Minor revision")
        RESUBMITTED = "resubmitted", _("Revision submitted")
        ACCEPTED = "accepted", _("Accepted")
        PROOFS = "proofs", _("Proofs / In press")
        PUBLISHED = "published", _("Published")
        REJECTED = "rejected", _("Rejected")
        WITHDRAWN = "withdrawn", _("Withdrawn")
        ON_HOLD = "on_hold", _("On hold")

    # Board columns, in pipeline order.
    PIPELINE = [
        Status.IDEA, Status.PROPOSAL, Status.DRAFTING, Status.INTERNAL_REVIEW, Status.READY,
        Status.SUBMITTED, Status.UNDER_REVIEW, Status.MAJOR_REVISION, Status.MINOR_REVISION,
        Status.RESUBMITTED, Status.ACCEPTED, Status.PROOFS, Status.PUBLISHED,
    ]
    CLOSED = [Status.PUBLISHED, Status.WITHDRAWN]
    ACTION_NEEDED = [Status.MAJOR_REVISION, Status.MINOR_REVISION, Status.PROOFS, Status.REJECTED]

    class Priority(models.IntegerChoices):
        LOW = 1, _("Low")
        NORMAL = 2, _("Normal")
        HIGH = 3, _("High")
        URGENT = 4, _("Urgent")

    group = models.ForeignKey(ResearchGroup, on_delete=models.CASCADE, related_name="papers",
                              verbose_name=_("research group"))
    title = models.CharField(_("title"), max_length=500)
    short_title = models.CharField(_("short title"), max_length=80, blank=True,
                                   help_text=_("Used on cards and in reminders"))
    type = models.CharField(_("type"), max_length=12, choices=Type.choices, default=Type.JOURNAL)
    status = models.CharField(_("status"), max_length=16, choices=Status.choices, default=Status.IDEA,
                              db_index=True)
    priority = models.IntegerField(_("priority"), choices=Priority.choices, default=Priority.NORMAL)
    abstract = models.TextField(_("abstract"), blank=True)
    keywords = models.CharField(_("keywords"), max_length=400, blank=True)
    research_area = models.CharField(_("research area"), max_length=200, blank=True,
                                     help_text=_("e.g. Intrusion detection, LLM security"))
    lead = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="led_papers", verbose_name=_("lead / responsible"))
    target_submission_date = models.DateField(_("target submission date"), null=True, blank=True)
    funding = models.CharField(_("funding / grant"), max_length=300, blank=True)
    repository_url = models.URLField(_("code / data repository"), blank=True)
    overleaf_url = models.URLField(_("manuscript link (Overleaf, Drive…)"), blank=True)
    doi = models.CharField("DOI", max_length=200, blank=True)
    published_url = models.URLField(_("published URL"), blank=True)
    publication_date = models.DateField(_("publication date"), null=True, blank=True)
    volume_issue_pages = models.CharField(_("volume / issue / pages"), max_length=100, blank=True)
    notes = models.TextField(_("internal notes"), blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = _("paper")
        verbose_name_plural = _("papers")

    def __str__(self):
        return self.label

    @property
    def label(self):
        return self.short_title or (self.title[:77] + "…" if len(self.title) > 80 else self.title)

    def get_absolute_url(self):
        return reverse("paper_detail", args=[self.pk])

    @property
    def current_submission(self):
        return self.submissions.order_by("-created_at").first()

    @property
    def is_closed(self):
        return self.status in self.CLOSED

    @property
    def needs_action(self):
        return self.status in self.ACTION_NEEDED

    def next_deadline(self):
        return self.deadlines.filter(completed_at__isnull=True).order_by("due_at").first()

    def keywords_list(self):
        return [k.strip() for k in self.keywords.replace("؛", ",").replace(";", ",").split(",") if k.strip()]

    def authors_missing_data(self):
        return [a for a in self.authors.all() if a.missing_fields()]

    def citation(self):
        names = ", ".join(a.name for a in self.authors.all())
        sub = self.submissions.filter(decision=Submission.Decision.ACCEPTED).first() or self.current_submission
        venue = sub.journal.name if sub else ""
        year = self.publication_date.year if self.publication_date else ""
        parts = [p for p in [names + ("" if year else "."), f"({year})." if year else "", f"{self.title}.",
                             f"{venue}." if venue else "", self.volume_issue_pages,
                             f"https://doi.org/{self.doi}" if self.doi else ""] if p]
        return " ".join(parts)


class PaperAuthor(models.Model):
    """An author on a paper. Linked to a platform account when the person has one,
    otherwise stored as free text so external co-authors never block the work."""

    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name="authors")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="authorships", verbose_name=_("platform account"))
    name = models.CharField(_("name"), max_length=200, blank=True)
    email = models.EmailField(_("email"), blank=True)
    affiliation = models.CharField(_("affiliation"), max_length=300, blank=True)
    country = models.CharField(_("country"), max_length=100, blank=True)
    orcid = models.CharField("ORCID", max_length=19, blank=True)
    order = models.PositiveIntegerField(_("author order"), default=1)
    is_corresponding = models.BooleanField(_("corresponding author"), default=False)
    contribution = models.CharField(_("contribution (CRediT)"), max_length=300, blank=True,
                                    help_text=_("e.g. Conceptualization, Methodology, Software, Writing"))
    approved_submission = models.BooleanField(_("approved final version"), default=False)
    coi_declared = models.BooleanField(_("conflict-of-interest form done"), default=False)
    data_requested_at = models.DateTimeField(null=True, blank=True)
    update_token = models.CharField(max_length=64, unique=True, default=_invite_token, editable=False)

    class Meta:
        ordering = ["order", "pk"]
        verbose_name = _("author")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Fill blanks from the linked account so the author list is always complete.
        if self.user_id:
            u = self.user
            self.name = self.name or u.display_name
            self.email = self.email or u.email
            self.affiliation = self.affiliation or u.affiliation
            self.country = self.country or u.country
            self.orcid = self.orcid or u.orcid
        super().save(*args, **kwargs)

    def missing_fields(self):
        req = {"name": _("name"), "email": _("email"), "affiliation": _("affiliation"), "country": _("country")}
        missing = [str(label) for f, label in req.items() if not getattr(self, f)]
        if not self.approved_submission:
            missing.append(str(_("approval")))
        return missing

    def get_update_url(self):
        return settings.SITE_URL + reverse("author_self_update", args=[self.update_token])


class Submission(models.Model):
    class Decision(models.TextChoices):
        DRAFT = "draft", _("Not yet submitted")
        SUBMITTED = "submitted", _("Submitted")
        WITH_EDITOR = "with_editor", _("With editor")
        UNDER_REVIEW = "under_review", _("Under review")
        MAJOR = "major", _("Major revision")
        MINOR = "minor", _("Minor revision")
        REVISION_SUBMITTED = "revision_submitted", _("Revision submitted")
        ACCEPTED = "accepted", _("Accepted")
        REJECTED = "rejected", _("Rejected")
        DESK_REJECTED = "desk_rejected", _("Desk rejected")
        TRANSFER = "transfer", _("Transfer offered")
        WITHDRAWN = "withdrawn", _("Withdrawn")

    # How a submission decision moves the paper status.
    DECISION_TO_STATUS = {
        Decision.SUBMITTED: Paper.Status.SUBMITTED,
        Decision.WITH_EDITOR: Paper.Status.SUBMITTED,
        Decision.UNDER_REVIEW: Paper.Status.UNDER_REVIEW,
        Decision.MAJOR: Paper.Status.MAJOR_REVISION,
        Decision.MINOR: Paper.Status.MINOR_REVISION,
        Decision.REVISION_SUBMITTED: Paper.Status.RESUBMITTED,
        Decision.ACCEPTED: Paper.Status.ACCEPTED,
        Decision.REJECTED: Paper.Status.REJECTED,
        Decision.DESK_REJECTED: Paper.Status.REJECTED,
        Decision.TRANSFER: Paper.Status.REJECTED,
        Decision.WITHDRAWN: Paper.Status.WITHDRAWN,
    }

    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name="submissions")
    journal = models.ForeignKey(Journal, on_delete=models.PROTECT, related_name="submissions",
                                verbose_name=_("journal / venue"))
    manuscript_id = models.CharField(_("manuscript ID"), max_length=100, blank=True)
    submitted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+", verbose_name=_("submitted by"))
    submitted_at = models.DateTimeField(_("submission date & time"), null=True, blank=True)
    decision = models.CharField(_("current state"), max_length=20, choices=Decision.choices,
                                default=Decision.DRAFT)
    round = models.PositiveIntegerField(_("review round"), default=1)
    first_decision_at = models.DateTimeField(_("first decision date"), null=True, blank=True)
    last_decision_at = models.DateTimeField(_("last decision date"), null=True, blank=True)
    revision_due_at = models.DateTimeField(_("revision due"), null=True, blank=True,
                                           help_text=_("A deadline with reminders is created automatically"))
    accepted_at = models.DateTimeField(_("acceptance date"), null=True, blank=True)
    special_issue = models.CharField(_("special issue"), max_length=300, blank=True)
    portal_url = models.URLField(_("submission link"), blank=True)
    editor = models.CharField(_("handling editor"), max_length=200, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("submission")
        verbose_name_plural = _("submissions")

    def __str__(self):
        return f"{self.paper.label} → {self.journal.name}"

    def get_absolute_url(self):
        return reverse("paper_detail", args=[self.paper_id]) + f"#submission-{self.pk}"

    @property
    def is_rejected(self):
        return self.decision in (self.Decision.REJECTED, self.Decision.DESK_REJECTED, self.Decision.TRANSFER)

    @property
    def done_comments(self):
        return sum(1 for c in self.review_comments.all() if c.state in ("done", "rebutted"))

    @property
    def done_pct(self):
        total = len(self.review_comments.all())
        return round(100 * self.done_comments / total) if total else 0

    @property
    def days_in_review(self):
        if not self.submitted_at:
            return None
        end = self.accepted_at or (self.last_decision_at if self.is_rejected else None) or timezone.now()
        return (end - self.submitted_at).days


class SubmissionEvent(models.Model):
    """Timeline of everything that happened to a submission (immutable)."""

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="events")
    decision = models.CharField(max_length=20, choices=Submission.Decision.choices)
    happened_at = models.DateTimeField(_("date & time"), default=timezone.now)
    note = models.TextField(_("note"), blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-happened_at", "-pk"]


class ReviewComment(models.Model):
    """One reviewer/editor point. Assign each one to a co-author and track the reply —
    this becomes the 'response to reviewers' letter."""

    class State(models.TextChoices):
        OPEN = "open", _("Open")
        IN_PROGRESS = "in_progress", _("In progress")
        DONE = "done", _("Addressed")
        REBUTTED = "rebutted", _("Rebutted")

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="review_comments")
    round = models.PositiveIntegerField(_("round"), default=1)
    reviewer = models.CharField(_("reviewer"), max_length=50, default="Reviewer 1")
    number = models.CharField(_("#"), max_length=10, blank=True)
    comment = models.TextField(_("comment"))
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="review_tasks", verbose_name=_("assigned to"))
    state = models.CharField(_("state"), max_length=12, choices=State.choices, default=State.OPEN)
    response = models.TextField(_("response"), blank=True)
    changes_location = models.CharField(_("where changed in manuscript"), max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["round", "reviewer", "pk"]
        verbose_name = _("reviewer comment")


# ---------------------------------------------------------------------------
# Deadlines & reminders
# ---------------------------------------------------------------------------
class Deadline(models.Model):
    class Kind(models.TextChoices):
        REVISION = "revision", _("Revision due")
        SUBMISSION = "submission", _("Submission deadline")
        PROPOSAL = "proposal", _("Proposal deadline")
        PROOFS = "proofs", _("Proof corrections")
        CAMERA_READY = "camera_ready", _("Camera-ready")
        AUTHOR_DATA = "author_data", _("Author data collection")
        INTERNAL = "internal", _("Internal milestone")
        PAYMENT = "payment", _("APC payment")
        OTHER = "other", _("Other")

    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name="deadlines")
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, null=True, blank=True,
                                   related_name="deadlines")
    kind = models.CharField(_("type"), max_length=14, choices=Kind.choices, default=Kind.OTHER)
    title = models.CharField(_("title"), max_length=200)
    due_at = models.DateTimeField(_("due date & time"))
    assignees = models.ManyToManyField(User, blank=True, related_name="deadlines",
                                       verbose_name=_("responsible"))
    reminder_days = models.CharField(_("remind (days before)"), max_length=50, blank=True,
                                     help_text=_("Comma-separated, e.g. 14,7,3,1,0. Empty = default."))
    notes = models.TextField(_("notes"), blank=True)
    completed_at = models.DateTimeField(_("completed at"), null=True, blank=True)
    completed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["completed_at", "due_at"]
        verbose_name = _("deadline")
        verbose_name_plural = _("deadlines")

    def __str__(self):
        return f"{self.title} — {self.paper.label}"

    def clean(self):
        try:
            self.reminder_offsets()
        except ValueError:
            raise ValidationError({"reminder_days": _("Use numbers separated by commas, e.g. 14,7,3,1")})

    def reminder_offsets(self):
        raw = self.reminder_days or settings.DEFAULT_REMINDER_DAYS
        return sorted({int(x) for x in raw.split(",") if x.strip()}, reverse=True)

    @property
    def is_done(self):
        return self.completed_at is not None

    @property
    def is_overdue(self):
        return not self.is_done and self.due_at < timezone.now()

    @property
    def days_left(self):
        return (timezone.localtime(self.due_at).date() - timezone.localdate()).days

    @property
    def urgency(self):
        """CSS-friendly bucket used by the UI."""
        if self.is_done:
            return "done"
        d = self.days_left
        if d < 0:
            return "overdue"
        if d <= 3:
            return "danger"
        if d <= 7:
            return "warning"
        return "ok"

    def recipients(self):
        """Who gets reminded: assignees, else the paper lead, else group managers."""
        people = list(self.assignees.filter(is_active=True))
        if not people and self.paper.lead and self.paper.lead.is_active:
            people = [self.paper.lead]
        if not people:
            people = [m.user for m in self.paper.group.memberships.select_related("user")
                      if m.is_manager and m.user.is_active]
        return [u for u in people if u.email_reminders]


class ReminderLog(models.Model):
    """Prevents the same reminder being emailed twice."""

    deadline = models.ForeignKey(Deadline, on_delete=models.CASCADE, related_name="reminder_logs")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    key = models.CharField(max_length=30)  # e.g. "d7", "overdue-2026-11-02"
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("deadline", "user", "key")]


# ---------------------------------------------------------------------------
# Files & audit
# ---------------------------------------------------------------------------
def attachment_path(instance, filename):
    return f"papers/{instance.paper_id}/{timezone.now():%Y%m%d%H%M%S}_{filename}"


ALLOWED_EXT = ["pdf", "doc", "docx", "tex", "zip", "txt", "md", "xlsx", "csv", "png", "jpg", "jpeg", "bib"]


class Attachment(models.Model):
    class Kind(models.TextChoices):
        MANUSCRIPT = "manuscript", _("Manuscript")
        REVISED = "revised", _("Revised manuscript")
        RESPONSE = "response", _("Response to reviewers")
        DECISION = "decision", _("Decision letter / reviews")
        COVER = "cover", _("Cover letter")
        FORM = "form", _("Forms (copyright, COI…)")
        PROOF = "proof", _("Proofs")
        OTHER = "other", _("Other")

    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name="attachments")
    submission = models.ForeignKey(Submission, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="attachments", verbose_name=_("submission"))
    kind = models.CharField(_("type"), max_length=12, choices=Kind.choices, default=Kind.OTHER)
    file = models.FileField(_("file"), upload_to=attachment_path,
                            validators=[FileExtensionValidator(ALLOWED_EXT)])
    description = models.CharField(_("description"), max_length=200, blank=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def clean(self):
        if self.file and self.file.size > settings.MAX_ATTACHMENT_MB * 1024 * 1024:
            raise ValidationError({"file": _("File too large (max %(mb)s MB).") % {"mb": settings.MAX_ATTACHMENT_MB}})

    @property
    def filename(self):
        return self.file.name.rsplit("/", 1)[-1].split("_", 1)[-1]


class Activity(models.Model):
    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name="activities", null=True)
    group = models.ForeignKey(ResearchGroup, on_delete=models.CASCADE, related_name="activities", null=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    verb = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "activities"

    def __str__(self):
        return f"{self.user}: {self.verb}"
