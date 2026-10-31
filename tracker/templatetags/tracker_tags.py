from django import template
from django.utils.html import format_html
from django.utils.translation import gettext as _, ngettext

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


@register.filter
def status_color(value):
    return STATUS_COLORS.get(value, "secondary")


@register.simple_tag
def status_badge(obj, field="status"):
    value = getattr(obj, field)
    label = getattr(obj, f"get_{field}_display")()
    return format_html('<span class="badge rounded-pill text-bg-{} status-badge">{}</span>',
                       status_color(value), label)


@register.simple_tag
def due_badge(deadline):
    if deadline.is_done:
        return format_html('<span class="badge text-bg-success">{}</span>', _("Done"))
    d = deadline.days_left
    cls = {"overdue": "danger", "danger": "danger", "warning": "warning", "ok": "secondary"}[deadline.urgency]
    if d < 0:
        text = ngettext("%(n)s day overdue", "%(n)s days overdue", -d) % {"n": -d}
    elif d == 0:
        text = _("Today")
    elif d == 1:
        text = _("Tomorrow")
    else:
        text = ngettext("in %(n)s day", "in %(n)s days", d) % {"n": d}
    return format_html('<span class="badge text-bg-{}">{}</span>', cls, text)


@register.filter
def get_item(d, key):
    return d.get(key)
