"""Multi-view papers workspace: cards · table · timeline · calendar · board.

All views share the same filters (search, type chips, status, group, "only mine")
so switching presentation never loses the user's context.
"""
import calendar as pycal
from collections import OrderedDict
from datetime import date, datetime, timedelta

from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _l

from . import models as m

VIEWS = [  # key, label, icon, colour
    ("cards", _l("All records"), "bi-grid-3x2-gap-fill", "#2c4a6e"),
    ("table", _l("Table"), "bi-table", "#2f6f78"),
    ("timeline", _l("Timeline"), "bi-bar-chart-steps", "#6b4f8a"),
    ("calendar", _l("Calendar"), "bi-calendar3-week-fill", "#b4612a"),
    ("board", _l("Board"), "bi-kanban-fill", "#2f6b46"),
]
VIEW_KEYS = [v[0] for v in VIEWS]

GROUP_BY = [
    ("status", _l("Status")),
    ("type", _l("Type")),
    ("group", _l("Research group")),
    ("venue", _l("Venue")),
    ("lead", _l("Lead")),
    ("none", _l("No grouping")),
]

TYPE_ICONS = {
    "journal": "bi-journal-text", "conference": "bi-easel", "chapter": "bi-book", "review": "bi-search",
    "proposal": "bi-lightbulb", "thesis": "bi-mortarboard", "other": "bi-file-earmark",
}
TYPE_COLORS = {
    "journal": "#2c4a6e", "conference": "#6b4f8a", "chapter": "#2f6f78", "review": "#2f6f78",
    "proposal": "#a87c22", "thesis": "#9a4a5c", "other": "#7a7266",
}

# Colour of the timeline segment that *starts* with each event.
PHASE = {
    "prep": ("#94a3b8", _l("Preparation")),
    m.Submission.Decision.SUBMITTED: ("#2c4a6e", _l("Submitted")),
    m.Submission.Decision.WITH_EDITOR: ("#2c4a6e", _l("With editor")),
    m.Submission.Decision.UNDER_REVIEW: ("#6b4f8a", _l("Under review")),
    m.Submission.Decision.MAJOR: ("#b4612a", _l("Major revision")),
    m.Submission.Decision.MINOR: ("#a87c22", _l("Minor revision")),
    m.Submission.Decision.REVISION_SUBMITTED: ("#3d4f7c", _l("Revision submitted")),
    m.Submission.Decision.ACCEPTED: ("#2f6b46", _l("Accepted")),
    m.Submission.Decision.REJECTED: ("#a63a2b", _l("Rejected")),
    m.Submission.Decision.DESK_REJECTED: ("#a63a2b", _l("Desk rejected")),
    m.Submission.Decision.TRANSFER: ("#be123c", _l("Transfer offered")),
    m.Submission.Decision.WITHDRAWN: ("#475569", _l("Withdrawn")),
    "published": ("#2f6b46", _l("Published")),
}


STATUS_GROUPS = {
    "in_review": ["submitted", "under_review", "resubmitted"],
    "revision": ["major_revision", "minor_revision"],
    "accepted_pub": ["accepted", "proofs", "published"],
}


def apply_filters(qs, data, user, skip_type=False):
    if data.get("q"):
        q = data["q"]
        qs = qs.filter(Q(title__icontains=q) | Q(short_title__icontains=q) | Q(keywords__icontains=q) |
                       Q(submissions__journal__name__icontains=q) | Q(submissions__manuscript_id__icontains=q)).distinct()
    if data.get("status") == "active":
        qs = qs.exclude(status__in=m.Paper.CLOSED + [m.Paper.Status.REJECTED])
    elif data.get("status") in STATUS_GROUPS:
        qs = qs.filter(status__in=STATUS_GROUPS[data["status"]])
    elif data.get("status"):
        qs = qs.filter(status=data["status"])
    if data.get("type") and not skip_type:
        qs = qs.filter(type=data["type"])
    if data.get("group"):
        qs = qs.filter(group=data["group"])
    if data.get("mine"):
        qs = qs.filter(Q(lead=user) | Q(authors__user=user)).distinct()
    return qs


def type_chips(base_qs, active):
    counts = {}
    for t in base_qs.values_list("type", flat=True):
        counts[t] = counts.get(t, 0) + 1
    chips = [{"key": "", "label": _l("All"), "count": sum(counts.values()), "icon": "bi-collection",
              "color": "#0f172a", "active": not active}]
    for key, label in m.Paper.Type.choices:
        if counts.get(key):
            chips.append({"key": key, "label": label, "count": counts[key], "icon": TYPE_ICONS[key],
                          "color": TYPE_COLORS[key], "active": active == key})
    return chips


def kpis(papers):
    papers = list(papers)
    now = timezone.now()
    open_dl = [d for p in papers for d in p.deadlines.all() if d.completed_at is None]
    return {
        "total": len(papers),
        "active": sum(1 for p in papers if p.status not in m.Paper.CLOSED + [m.Paper.Status.REJECTED]),
        "review": sum(1 for p in papers if p.status in STATUS_GROUPS["in_review"]),
        "overdue": sum(1 for d in open_dl if d.due_at < now),
        "published": sum(1 for p in papers if p.status in STATUS_GROUPS["accepted_pub"]),
    }


# ---------------------------------------------------------------- cards
def grouped(papers, by):
    papers = list(papers)
    if by == "none":
        return [{"label": None, "papers": papers, "color": None}]
    groups = OrderedDict()
    if by == "status":
        order = m.Paper.PIPELINE + [m.Paper.Status.REJECTED, m.Paper.Status.ON_HOLD, m.Paper.Status.WITHDRAWN]
        for st in order:
            groups[st] = {"label": m.Paper.Status(st).label, "papers": [], "status": st}
        for p in papers:
            groups[p.status]["papers"].append(p)
    else:
        for p in papers:
            if by == "type":
                key, label = p.type, p.get_type_display()
            elif by == "group":
                key, label = p.group_id, p.group.name
            elif by == "venue":
                s = p.current_submission
                key, label = (s.journal_id, s.journal.name) if s else (0, str(_l("Not submitted yet")))
            else:
                key, label = (p.lead_id, p.lead.display_name) if p.lead else (0, "—")
            groups.setdefault(key, {"label": label, "papers": [], "type": p.type if by == "type" else None})
            groups[key]["papers"].append(p)
    return [g for g in groups.values() if g["papers"]]


# ---------------------------------------------------------------- timeline
def timeline(papers, months_back=12, months_ahead=3):
    today = timezone.localdate()
    start = (today.replace(day=1) - timedelta(days=months_back * 31)).replace(day=1)
    end_month = today.month + months_ahead
    end = date(today.year + (end_month - 1) // 12, (end_month - 1) % 12 + 1, 1)
    span = (end - start).days or 1

    def pos(d):
        if isinstance(d, datetime):
            d = timezone.localtime(d).date()
        return max(0.0, min(100.0, (d - start).days * 100 / span))

    months = []
    cur = start
    while cur < end:
        nxt = date(cur.year + (cur.month // 12), cur.month % 12 + 1, 1)
        months.append({"label": cur, "left": pos(cur), "width": pos(nxt) - pos(cur),
                       "is_now": cur.year == today.year and cur.month == today.month})
        cur = nxt

    rows = []
    for p in papers:
        events = []
        for s in p.submissions.all():
            evs = list(s.events.all())
            for e in evs:
                events.append((e.happened_at, e.decision, s.journal.name))
            if not evs:  # older/imported records: rebuild milestones from the submission's dates
                if s.submitted_at:
                    events.append((s.submitted_at, "submitted", s.journal.name))
                if s.first_decision_at and s.decision not in ("submitted", "draft", "accepted"):
                    events.append((s.first_decision_at, s.decision if s.decision != "accepted" else "under_review",
                                   s.journal.name))
                elif s.first_decision_at and s.accepted_at and s.first_decision_at < s.accepted_at:
                    events.append((s.first_decision_at, "major", s.journal.name))
                if s.accepted_at:
                    events.append((s.accepted_at, "accepted", s.journal.name))
                elif s.decision == "under_review" and s.submitted_at:
                    events.append((s.submitted_at + timedelta(days=5), "under_review", s.journal.name))
        events.sort(key=lambda x: x[0])
        if p.publication_date:
            events.append((timezone.make_aware(datetime.combine(p.publication_date, datetime.min.time())),
                           "published", ""))
        first = min([p.created_at] + [e[0] for e in events])
        points = [(first, "prep", "")] + [e for e in events if e[0] > first]
        segs = []
        for i, (when, kind, venue) in enumerate(points):
            stop = points[i + 1][0] if i + 1 < len(points) else timezone.now()
            if kind in ("rejected", "desk_rejected", "transfer", "withdrawn") and i + 1 == len(points):
                stop = when + timedelta(days=4)  # short red tick, not a bar to today
            if kind == "published":
                stop = when + timedelta(days=6)
            color, label = PHASE.get(kind, ("#94a3b8", kind))
            left, right = pos(when), pos(stop)
            if right <= 0 or left >= 100:
                continue
            segs.append({"left": left, "width": max(right - left, .6), "color": color,
                         "title": f"{label}{' · ' + venue if venue else ''} · {timezone.localtime(when):%d/%m/%Y}"})
        marks = [{"left": pos(d.due_at), "title": f"{d.title} · {timezone.localtime(d.due_at):%d/%m/%Y}",
                  "overdue": d.is_overdue}
                 for d in p.deadlines.all() if d.completed_at is None and 0 <= pos(d.due_at) <= 100]
        last = max([first] + [e[0] for e in events])
        rows.append({"paper": p, "segs": segs, "marks": marks, "sort": last})
    rows.sort(key=lambda r: r["sort"], reverse=True)
    legend = [PHASE[k] for k in ("prep", "submitted", "under_review", "major", "revision_submitted", "accepted",
                                 "rejected", "published")]
    return {"months": months, "rows": rows, "today": pos(today), "legend": legend}


# ---------------------------------------------------------------- calendar
def month_calendar(papers, month_param, first_weekday=6):
    today = timezone.localdate()
    try:
        y, mo = map(int, (month_param or "").split("-"))
        anchor = date(y, mo, 1)
    except ValueError:
        anchor = today.replace(day=1)
    cal = pycal.Calendar(firstweekday=first_weekday)
    weeks = cal.monthdatescalendar(anchor.year, anchor.month)
    first, last = weeks[0][0], weeks[-1][-1]

    events = {}
    paper_ids = [p.pk for p in papers]

    def add(d, item):
        events.setdefault(d, []).append(item)

    dls = (m.Deadline.objects.filter(paper_id__in=paper_ids).select_related("paper")
           .filter(due_at__date__gte=first - timedelta(days=1), due_at__date__lte=last + timedelta(days=1)))
    for d in dls:
        day = timezone.localtime(d.due_at).date()
        tone = "done" if d.completed_at else ("overdue" if d.is_overdue else "deadline")
        add(day, {"kind": tone, "icon": "bi-alarm", "title": d.title, "sub": d.paper.label,
                  "url": d.paper.get_absolute_url() + "#deadlines", "time": timezone.localtime(d.due_at)})
    evs = (m.SubmissionEvent.objects.filter(submission__paper_id__in=paper_ids)
           .select_related("submission__journal", "submission__paper")
           .filter(happened_at__date__gte=first - timedelta(days=1), happened_at__date__lte=last + timedelta(days=1)))
    for e in evs:
        day = timezone.localtime(e.happened_at).date()
        tone = {"accepted": "good", "rejected": "bad", "desk_rejected": "bad", "major": "warn", "minor": "warn"}.get(
            e.decision, "event")
        add(day, {"kind": tone, "icon": "bi-send" if e.decision == "submitted" else "bi-flag",
                  "title": e.get_decision_display(), "sub": f"{e.submission.paper.label} · {e.submission.journal.name}",
                  "url": e.submission.get_absolute_url(), "time": timezone.localtime(e.happened_at)})
    for p in papers:
        if p.publication_date and first <= p.publication_date <= last:
            add(p.publication_date, {"kind": "good", "icon": "bi-award", "title": str(_l("Published")),
                                     "sub": p.label, "url": p.get_absolute_url(), "time": None})

    grid = [[{"date": d, "in_month": d.month == anchor.month, "today": d == today,
              "items": sorted(events.get(d, []), key=lambda x: (x["time"] is None, x["time"] or 0))}
             for d in week] for week in weeks]
    prev_m = (anchor - timedelta(days=1)).replace(day=1)
    next_m = (anchor + timedelta(days=32)).replace(day=1)
    weekday_names = [date(2024, 1, 7 + ((first_weekday + 1 + i) % 7)) for i in range(7)]  # 2024-01-07 is Sunday
    month_items = sum(len(c["items"]) for w in grid for c in w if c["in_month"])
    upcoming = sorted([i | {"date": d} for d, items in events.items() if d.month == anchor.month for i in items],
                      key=lambda x: (x["date"], x["time"] is None))
    return {"weeks": grid, "anchor": anchor, "prev": prev_m.strftime("%Y-%m"), "next": next_m.strftime("%Y-%m"),
            "this": today.strftime("%Y-%m"), "weekdays": weekday_names, "count": month_items, "agenda": upcoming}


# ---------------------------------------------------------------- board
def board_columns(papers, show_all=False):
    cols = []
    for st in m.Paper.PIPELINE + [m.Paper.Status.REJECTED, m.Paper.Status.ON_HOLD]:
        items = [p for p in papers if p.status == st]
        if items or show_all:
            cols.append({"status": st, "label": m.Paper.Status(st).label, "papers": items})
    return cols


# ---------------------------------------------------------------- vertical timeline
EVENT_STYLE = {  # kind -> (icon, colour)
    "start": ("bi-lightbulb-fill", "#7a7266"),
    "submitted": ("bi-send-fill", "#2c4a6e"), "with_editor": ("bi-person-workspace", "#2c4a6e"),
    "under_review": ("bi-hourglass-split", "#6b4f8a"), "major": ("bi-arrow-repeat", "#b4612a"),
    "minor": ("bi-wrench-adjustable", "#a87c22"), "revision_submitted": ("bi-send-check-fill", "#3d4f7c"),
    "accepted": ("bi-patch-check-fill", "#2f6b46"), "rejected": ("bi-x-octagon-fill", "#a63a2b"),
    "desk_rejected": ("bi-x-octagon-fill", "#a63a2b"), "transfer": ("bi-arrow-left-right", "#be123c"),
    "withdrawn": ("bi-box-arrow-left", "#475569"), "published": ("bi-award-fill", "#2f6b46"),
    "deadline": ("bi-alarm-fill", "#9a4a5c"), "overdue": ("bi-exclamation-triangle-fill", "#a63a2b"),
}


def vertical_timeline(papers, months_back=18):
    """Chronological feed of milestones (newest first) grouped by month, for the vertical timeline."""
    now = timezone.now()
    since = now - timedelta(days=months_back * 31)
    items = []

    def add(when, kind, title, paper, sub="", url=None, future=False):
        if when is None or when < since:
            return
        icon, color = EVENT_STYLE.get(kind, ("bi-circle-fill", "#7a7266"))
        items.append({"when": when, "kind": kind, "icon": icon, "color": color, "title": title,
                      "paper": paper, "sub": sub, "url": url or paper.get_absolute_url(), "future": future})

    for p in papers:
        if not p.submissions.all():
            add(p.created_at, "start", str(_l("Work started")), p)
        for s in p.submissions.all():
            evs = list(s.events.all())
            if evs:
                for e in evs:
                    add(e.happened_at, e.decision, e.get_decision_display(), p, s.journal.name, s.get_absolute_url())
            else:
                if s.submitted_at:
                    add(s.submitted_at, "submitted", str(_l("Submitted")), p, s.journal.name, s.get_absolute_url())
                if s.first_decision_at and s.decision not in ("draft", "submitted"):
                    add(s.first_decision_at, s.decision, s.get_decision_display(), p, s.journal.name,
                        s.get_absolute_url())
                if s.accepted_at and s.decision != "accepted":
                    add(s.accepted_at, "accepted", str(_l("Accepted")), p, s.journal.name, s.get_absolute_url())
        if p.publication_date:
            add(timezone.make_aware(datetime.combine(p.publication_date, datetime.min.time())), "published",
                str(_l("Published")), p)
        for d in p.deadlines.all():
            if d.completed_at is None:
                add(d.due_at, "overdue" if d.due_at < now else "deadline", d.title, p, d.get_kind_display(),
                    p.get_absolute_url() + "#deadlines", future=d.due_at >= now)
    items.sort(key=lambda x: x["when"], reverse=True)
    months = OrderedDict()
    for it in items:
        key = timezone.localtime(it["when"]).date().replace(day=1)
        months.setdefault(key, []).append(it)
    out = []
    for month, evs in months.items():
        out.append({"month": month, "items": evs})
    # index of the first past item so the template can draw a "Today" marker
    for it in items:
        if not it["future"]:
            it["first_past"] = True
            break
    return {"months": out, "count": len(items)}
