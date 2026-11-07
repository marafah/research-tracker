from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from . import models as m

User = get_user_model()


class DateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, **kw):
        super().__init__(format="%Y-%m-%dT%H:%M", **kw)


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kw):
        super().__init__(format="%Y-%m-%d", **kw)


class BootstrapMixin:
    """Adds Bootstrap classes to every widget."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            w = field.widget
            if isinstance(w, (forms.CheckboxInput,)):
                w.attrs.setdefault("class", "form-check-input")
            elif isinstance(w, (forms.Select, forms.SelectMultiple)):
                w.attrs.setdefault("class", "form-select")
            else:
                w.attrs.setdefault("class", "form-control")
            if isinstance(w, forms.Textarea) and str(w.attrs.get("rows")) == "10":
                w.attrs["rows"] = 3


def group_users(group):
    return User.objects.filter(memberships__group=group).order_by("full_name", "email")


class GroupForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = m.ResearchGroup
        fields = ["name", "institution", "description"]


class InvitationForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = m.Invitation
        fields = ["email", "role", "message"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = [c for c in self.fields["role"].choices if c[0] != "owner"]


class MembershipRoleForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = m.GroupMembership
        fields = ["role"]


class PaperForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = m.Paper
        fields = ["group", "title", "short_title", "type", "status", "priority", "lead", "research_area",
                  "keywords", "abstract", "target_submission_date", "funding", "overleaf_url",
                  "repository_url", "doi", "published_url", "publication_date", "volume_issue_pages", "notes"]
        widgets = {"target_submission_date": DateInput(), "publication_date": DateInput(),
                   "abstract": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .permissions import EDITOR_ROLES
        groups = m.ResearchGroup.objects.filter(memberships__user=user, memberships__role__in=EDITOR_ROLES)
        if self.instance.pk:
            groups = groups | m.ResearchGroup.objects.filter(pk=self.instance.group_id)
        self.fields["group"].queryset = groups.distinct()
        group = self.instance.group if self.instance.pk else groups.first()
        self.fields["lead"].queryset = (User.objects.filter(research_groups__in=groups).distinct()
                                        .order_by("full_name"))
        if not self.instance.pk:
            self.fields["lead"].initial = user
            if group:
                self.fields["group"].initial = group


class AuthorForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = m.PaperAuthor
        fields = ["user", "name", "email", "affiliation", "country", "orcid", "order", "is_corresponding",
                  "contribution", "approved_submission", "coi_declared"]

    def __init__(self, *args, paper=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = group_users(paper.group) if paper else User.objects.none()
        self.fields["user"].required = False
        self.fields["user"].help_text = _("Pick a platform member, or leave empty and type the details")

    def clean(self):
        data = super().clean()
        if not data.get("user") and not data.get("name"):
            raise forms.ValidationError(_("Choose a member or enter the author's name."))
        return data


class AuthorSelfUpdateForm(BootstrapMixin, forms.ModelForm):
    """Public (token) form an external co-author fills in without an account."""

    class Meta:
        model = m.PaperAuthor
        fields = ["name", "email", "affiliation", "country", "orcid", "contribution",
                  "approved_submission", "coi_declared"]


class SubmissionForm(BootstrapMixin, forms.ModelForm):
    note = forms.CharField(label=_("Note for the timeline"), required=False, widget=forms.Textarea(attrs={"rows": 2}))

    class Meta:
        model = m.Submission
        fields = ["journal", "manuscript_id", "decision", "submitted_at", "submitted_by", "revision_due_at",
                  "accepted_at", "special_issue", "portal_url", "editor", "notes"]
        widgets = {"submitted_at": DateTimeInput(), "revision_due_at": DateTimeInput(),
                   "accepted_at": DateTimeInput()}

    def __init__(self, *args, paper=None, **kwargs):
        super().__init__(*args, **kwargs)
        for f in ("submitted_at", "revision_due_at", "accepted_at"):
            self.fields[f].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["submitted_by"].queryset = group_users(paper.group) if paper else User.objects.none()
        self.fields["journal"].queryset = m.Journal.objects.order_by("name")

    def clean(self):
        data = super().clean()
        if data.get("decision") in ("major", "minor") and not data.get("revision_due_at"):
            self.add_error("revision_due_at", _("Please set the revision due date so reminders can be sent."))
        if data.get("decision") not in ("draft", None) and not data.get("submitted_at"):
            self.add_error("submitted_at", _("Please set the submission date."))
        return data


class DeadlineForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = m.Deadline
        fields = ["kind", "title", "due_at", "submission", "assignees", "reminder_days", "notes"]
        widgets = {"due_at": DateTimeInput(), "assignees": forms.SelectMultiple(attrs={"size": 5})}

    def __init__(self, *args, paper=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["due_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["assignees"].queryset = group_users(paper.group)
        self.fields["submission"].queryset = paper.submissions.all()
        self.fields["submission"].required = False


class ReviewCommentForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = m.ReviewComment
        fields = ["round", "reviewer", "number", "comment", "assigned_to", "state", "response", "changes_location"]
        widgets = {"comment": forms.Textarea(attrs={"rows": 3}), "response": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, paper=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = group_users(paper.group)


class BulkCommentsForm(BootstrapMixin, forms.Form):
    reviewer = forms.CharField(label=_("Reviewer"), initial="Reviewer 1", max_length=50)
    round = forms.IntegerField(label=_("Round"), initial=1, min_value=1)
    text = forms.CharField(
        label=_("Paste the reviewer's comments"), widget=forms.Textarea(attrs={"rows": 12}),
        help_text=_("Separate comments with an empty line, or number them (1. 2. 3. …)"))


class AttachmentForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = m.Attachment
        fields = ["kind", "file", "submission", "description"]

    def __init__(self, *args, paper=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["submission"].queryset = paper.submissions.all()
        self.fields["submission"].required = False


class JournalForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = m.Journal
        fields = ["name", "kind", "publisher", "issn", "eissn", "website", "submission_portal", "quartile",
                  "impact_factor", "indexed_scopus", "indexed_wos", "open_access", "apc_amount", "apc_currency",
                  "flagged", "notes"]


class PaperFilterForm(BootstrapMixin, forms.Form):
    q = forms.CharField(label=_("Search"), required=False)
    status = forms.ChoiceField(label=_("Status"), required=False,
                               choices=[("", _("All statuses")), ("active", _("Active only")), ("in_review", _("Submitted / in review")),
                                        ("revision", _("Needs revision")), ("accepted_pub", _("Accepted / published"))]
                               + list(m.Paper.Status.choices))
    type = forms.ChoiceField(label=_("Type"), required=False, choices=[("", _("All types"))] + list(m.Paper.Type.choices))
    group = forms.ModelChoiceField(label=_("Group"), required=False, queryset=m.ResearchGroup.objects.none(),
                                   empty_label=_("All groups"))
    mine = forms.BooleanField(label=_("Only mine"), required=False)
    # extra filters (free values, checked in workspace.apply_filters)
    venue_kind = forms.CharField(required=False)
    venue = forms.CharField(required=False)
    publisher = forms.CharField(required=False)
    quartile = forms.CharField(required=False)
    index = forms.CharField(required=False)
    deadline = forms.CharField(required=False)
    year = forms.CharField(required=False)
    author = forms.CharField(required=False)
    sort = forms.CharField(required=False)
    phase = forms.CharField(required=False)

    def __init__(self, *args, groups=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["group"].queryset = groups
        self.fields["q"].widget.attrs["placeholder"] = _("Search titles, keywords, journals…")
