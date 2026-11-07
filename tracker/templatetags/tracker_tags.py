from django import template
from django.utils.html import format_html
from django.utils.translation import gettext as _, gettext_lazy, ngettext

register = template.Library()

STATUS_COLORS = {
    "idea": "secondary", "proposal": "info", "drafting": "info", "internal_review": "info",
    "ready": "primary", "submitted": "primary", "under_review": "primary",
    "major_revision": "warning", "minor_revision": "warning", "resubmitted": "primary",
    "accepted": "success", "proofs": "success", "published": "success",
    "rejected": "danger", "withdrawn": "dark", "on_hold": "secondary",
    # submission decisions
    "draft": "secondary", "with_editor": "primary", "major": "warning", "minor": "warning",
    "revision_submitted": "primary", "desk_rejected": "danger", "transfer": "danger",
    # review comment states
    "open": "danger", "in_progress": "warning", "done": "success", "rebutted": "info",
}

# A distinct, flat colour for every status so pipelines, badges and boards read at a glance.
STATUS_HEX = {
    "idea": "#6c757d", "proposal": "#0aa2c0", "drafting": "#0aa2c0", "internal_review": "#3d8bfd",
    "ready": "#6610f2", "submitted": "#0d6efd", "under_review": "#6f42c1", "major_revision": "#fd7e14",
    "minor_revision": "#e0a800", "resubmitted": "#6366f1", "accepted": "#198754", "proofs": "#65a30d",
    "published": "#198754", "rejected": "#dc3545", "withdrawn": "#475569", "on_hold": "#a16207",
    "draft": "#6c757d", "with_editor": "#0d6efd", "major": "#fd7e14", "minor": "#e0a800",
    "revision_submitted": "#6366f1", "desk_rejected": "#dc3545", "transfer": "#be123c",
    "open": "#dc3545", "in_progress": "#e0a800", "done": "#198754", "rebutted": "#0aa2c0",
}
STATUS_ICONS = {
    "idea": "bi-lightbulb", "proposal": "bi-file-earmark-richtext", "drafting": "bi-pencil-square",
    "internal_review": "bi-people", "ready": "bi-check2-square", "submitted": "bi-send",
    "under_review": "bi-hourglass-split", "major_revision": "bi-arrow-repeat", "minor_revision": "bi-wrench-adjustable",
    "resubmitted": "bi-send-check", "accepted": "bi-patch-check", "proofs": "bi-file-earmark-check",
    "published": "bi-award", "rejected": "bi-x-octagon", "withdrawn": "bi-box-arrow-left", "on_hold": "bi-pause-circle",
}


@register.filter
def status_color(value):
    return STATUS_COLORS.get(value, "secondary")


@register.filter
def status_hex(value):
    return STATUS_HEX.get(value, "#6c757d")


@register.filter
def status_icon(value):
    return STATUS_ICONS.get(value, "bi-circle")


def _soft(color):
    return f"bg-{color}-subtle text-{color}-emphasis"


@register.simple_tag
def status_badge(obj, field="status"):
    value = getattr(obj, field)
    label = getattr(obj, f"get_{field}_display")()
    return format_html('<span class="sbadge" data-s="{}" style="--s:{}">{}</span>', value, status_hex(value), label)


@register.simple_tag
def status_badge_code(code, label):
    return format_html('<span class="sbadge" data-s="{}" style="--s:{}">{}</span>', code, status_hex(code), label)


@register.simple_tag
def due_badge(deadline):
    if deadline.is_done:
        return format_html('<span class="due due-done"><i class="bi bi-check2"></i>{}</span>', _("Done"))
    d = deadline.days_left
    color = {"overdue": "due-overdue", "danger": "due-danger", "warning": "due-warning", "ok": "due-ok"}[deadline.urgency]
    if d < 0:
        text = ngettext("%(n)s day overdue", "%(n)s days overdue", -d) % {"n": -d}
    elif d == 0:
        text = _("Today")
    elif d == 1:
        text = _("Tomorrow")
    else:
        text = ngettext("in %(n)s day", "in %(n)s days", d) % {"n": d}
    icon = "bi-exclamation-triangle-fill" if d < 0 else "bi-clock"
    return format_html('<span class="due {}"><i class="bi {}"></i>{}</span>', color, icon, text)


@register.filter
def initials(value):
    """'Sara Khalil' -> 'SK'; works with users, authors, strings."""
    name = getattr(value, "display_name", None) or getattr(value, "name", None) or str(value or "")
    if "@" in name:
        name = name.split("@")[0].replace(".", " ")
    parts = [p for p in name.replace("-", " ").split() if p[:1].isalpha()]
    if not parts:
        return "?"
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


@register.filter
def avatar_class(value):
    key = str(getattr(value, "pk", None) or value or "")
    return f"c{sum(map(ord, key)) % 5 + 1}"


STAGES = [
    ("prep", gettext_lazy("Preparation"), ["idea", "proposal", "drafting", "internal_review", "ready", "on_hold"]),
    ("sub", gettext_lazy("Submitted"), ["submitted"]),
    ("rev", gettext_lazy("Under review"), ["under_review"]),
    ("revision", gettext_lazy("Revision"), ["major_revision", "minor_revision", "resubmitted"]),
    ("acc", gettext_lazy("Accepted"), ["accepted", "proofs"]),
    ("pub", gettext_lazy("Published"), ["published"]),
]


@register.inclusion_tag("tracker/_stepper.html")
def paper_stepper(paper):
    status = paper.status
    halted = status in ("rejected", "withdrawn")
    current = None
    for i, (_k, _l, members) in enumerate(STAGES):
        if status in members:
            current = i
    if halted:
        # Show how far it got: the latest submission reached review.
        current = 2 if paper.submissions.exists() else 0
    steps = []
    for i, (key, label, _m) in enumerate(STAGES):
        state = "done" if current is not None and i < current else ("current" if i == current else "")
        if halted and i == current:
            label = paper.get_status_display()
        steps.append({"label": label, "state": state, "n": i + 1})
    return {"steps": steps, "halted": halted}


@register.filter
def get_item(d, key):
    return d.get(key)


@register.filter
def type_hex(value):
    from tracker.workspace import TYPE_COLORS
    return TYPE_COLORS.get(value, "#6c757d")


@register.filter
def type_icon(value):
    from tracker.workspace import TYPE_ICONS
    return TYPE_ICONS.get(value, "bi-file-earmark")
