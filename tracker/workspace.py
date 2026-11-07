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
    ("cards", _l("All records"), "bi-grid-3x2-gap-fill", "#0d6efd"),
    ("list", _l("Compact list"), "bi-list-ul", "#5b6bbf"),
    ("table", _l("Table"), "bi-table", "#0aa2c0"),
    ("board", _l("Board"), "bi-kanban-fill", "#198754"),
    ("venues", _l("Grouped"), "bi-collection-fill", "#6610f2"),
    ("timeline", _l("Timeline"), "bi-distribute-vertical", "#6f42c1"),
    ("gantt", _l("Gantt chart"), "bi-bar-chart-steps", "#0d9488"),
    ("calendar", _l("Calendar"), "bi-calendar3-week-fill", "#fd7e14"),
    ("stats", _l("Statistics"), "bi-pie-chart-fill", "#d63384"),
    ("matrix", _l("Matrix"), "bi-grid-3x3-gap-fill", "#e0a800"),
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
    "journal": "#0d6efd", "conference": "#6f42c1", "chapter": "#0aa2c0", "review": "#0aa2c0",
    "proposal": "#e0a800", "thesis": "#d63384", "other": "#5b6bbf",
}

# Colour of the timeline segment that *starts* with each event.
PHASE = {
    "prep": ("#7c8fd6", _l("Preparation")),
    m.Submission.Decision.SUBMITTED: ("#0d6efd", _l("Submitted")),
    m.Submission.Decision.WITH_EDITOR: ("#0d6efd", _l("With editor")),
    m.Submission.Decision.UNDER_REVIEW: ("#6f42c1", _l("Under review")),
    m.Submission.Decision.MAJOR: ("#fd7e14", _l("Major revision")),
    m.Submission.Decision.MINOR: ("#e0a800", _l("Minor revision")),
    m.Submission.Decision.REVISION_SUBMITTED: ("#6610f2", _l("Revision submitted")),
    m.Submission.Decision.ACCEPTED: ("#198754", _l("Accepted")),
    m.Submission.Decision.REJECTED: ("#dc3545", _l("Rejected")),
    m.Submission.Decision.DESK_REJECTED: ("#dc3545", _l("Desk rejected")),
    m.Submission.Decision.TRANSFER: ("#be123c", _l("Transfer offered")),
    m.Submission.Decision.WITHDRAWN: ("#8a5a83", _l("Withdrawn")),
    "published": ("#198754", _l("Published")),
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
    if data.get("phase") in PHASE_STATUSES:
        qs = qs.filter(status__in=PHASE_STATUSES[data["phase"]])
    # venue filters look at every submission of the paper (the current one and earlier ones)
    if data.get("venue_kind") in m.Journal.Kind.values:
        qs = qs.filter(submissions__journal__kind=data["venue_kind"]).distinct()
    elif data.get("venue_kind") == "none":
        qs = qs.filter(submissions__isnull=True)
    if str(data.get("venue") or "").isdigit():
        qs = qs.filter(submissions__journal_id=int(data["venue"])).distinct()
    if data.get("publisher"):
        qs = qs.filter(submissions__journal__publisher=data["publisher"]).distinct()
    if data.get("quartile") and data["quartile"] in m.Journal.Quartile.values:
        qs = qs.filter(submissions__journal__quartile=data["quartile"]).distinct()
    idx = data.get("index")
    if idx == "scopus":
        qs = qs.filter(submissions__journal__indexed_scopus=True).distinct()
    elif idx == "wos":
        qs = qs.filter(submissions__journal__indexed_wos=True).distinct()
    elif idx == "oa":
        qs = qs.filter(submissions__journal__open_access=True).distinct()
    dl = data.get("deadline")
    if dl in DEADLINE_WINDOWS:
        now = timezone.now()
        open_dl = Q(deadlines__completed_at__isnull=True)
        if dl == "overdue":
            qs = qs.filter(open_dl, deadlines__due_at__lt=now).distinct()
        elif dl == "none":
            upcoming = m.Deadline.objects.filter(completed_at__isnull=True, due_at__gte=now).values("paper_id")
            qs = qs.exclude(pk__in=upcoming)
        else:
            days = {"week": 7, "month": 30, "quarter": 90}[dl]
            qs = qs.filter(open_dl, deadlines__due_at__gte=now, deadlines__due_at__lt=now + timedelta(days=days)).distinct()
    if str(data.get("year") or "").isdigit():
        qs = qs.filter(submissions__submitted_at__year=int(data["year"])).distinct()
    if str(data.get("author") or "").isdigit():
        uid = int(data["author"])
        qs = qs.filter(Q(lead_id=uid) | Q(authors__user_id=uid)).distinct()
    return qs


DEADLINE_WINDOWS = OrderedDict([
    ("overdue", _l("Overdue")), ("week", _l("Due within 7 days")), ("month", _l("Due within 30 days")),
    ("quarter", _l("Due within 90 days")), ("none", _l("No upcoming deadline")),
])
INDEX_CHOICES = [("scopus", "Scopus"), ("wos", "Web of Science"), ("oa", _l("Open access"))]
SORT_CHOICES = [("updated", _l("Recently updated")), ("deadline", _l("Next deadline")),
                ("submitted", _l("Submission date")), ("title", _l("Title A–Z")), ("status", _l("Status"))]


def filter_options(base_qs):
    """Values that actually occur in the papers the user can see, for the filter bar."""
    subs = m.Submission.objects.filter(paper__in=base_qs).select_related("journal")
    venues, publishers, kinds, quartiles, years, indexed = {}, set(), set(), set(), set(), set()
    for sub in subs:
        j = sub.journal
        if j is None:
            continue
        venues[j.pk] = j.name
        kinds.add(j.kind)
        if j.publisher:
            publishers.add(j.publisher)
        if j.quartile:
            quartiles.add(j.quartile)
        for key, flag in (("scopus", j.indexed_scopus), ("wos", j.indexed_wos), ("oa", j.open_access)):
            if flag:
                indexed.add(key)
        if sub.submitted_at:
            years.add(sub.submitted_at.year)
    authors = {}
    for a in m.PaperAuthor.objects.filter(paper__in=base_qs, user__isnull=False).select_related("user"):
        authors[a.user_id] = a.name or str(a.user)
    for p in base_qs.select_related("lead"):
        if p.lead_id and p.lead_id not in authors:
            authors[p.lead_id] = getattr(p.lead, "display_name", "") or str(p.lead)
    return {
        "venue_kinds": [(k, lab) for k, lab in m.Journal.Kind.choices if k in kinds],
        "venues": sorted(venues.items(), key=lambda x: x[1].lower()),
        "publishers": sorted(publishers, key=str.lower),
        "quartiles": [q for q, _x in m.Journal.Quartile.choices if q in quartiles],
        "indexes": [(k, lab) for k, lab in INDEX_CHOICES if k in indexed],
        "deadlines": list(DEADLINE_WINDOWS.items()),
        "years": sorted(years, reverse=True),
        "authors": sorted(authors.items(), key=lambda x: x[1].lower()),
        "sorts": SORT_CHOICES,
    }


def sort_papers(papers, key):
    """Sort the already-filtered list; uses prefetched submissions and deadlines."""
    far = timezone.now() + timedelta(days=36500)
    old = timezone.now() - timedelta(days=36500)

    def next_due(p):
        due = [d.due_at for d in p.deadlines.all() if d.completed_at is None]
        return min(due) if due else far

    def submitted(p):
        dates = [s.submitted_at for s in p.submissions.all() if s.submitted_at]
        return max(dates) if dates else old

    if key == "deadline":
        return sorted(papers, key=next_due)
    if key == "submitted":
        return sorted(papers, key=submitted, reverse=True)
    if key == "title":
        return sorted(papers, key=lambda p: (p.title or "").lower())
    if key == "status":
        order = {c: i for i, c in enumerate(m.Paper.Status.values)}
        return sorted(papers, key=lambda p: order.get(p.status, 99))
    return sorted(papers, key=lambda p: p.updated_at, reverse=True)


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
            color, label = PHASE.get(kind, ("#7c8fd6", kind))
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
# The stages board always shows the whole path of a paper as five phases (the same phases as the dashboard),
# each with its stages and their counts, so an empty phase is still visible. "All stages" opens one column per stage.
BOARD_PHASES = [
    ("prep", _l("Preparation"), "#5b6bbf", "bi-pencil-square",
     ["idea", "proposal", "drafting", "internal_review", "ready"]),
    ("review", _l("Submitted / in review"), "#0d6efd", "bi-send-fill", ["submitted", "under_review", "resubmitted"]),
    ("revision", _l("Revision"), "#fd7e14", "bi-arrow-repeat", ["major_revision", "minor_revision"]),
    ("done", _l("Accepted & published"), "#198754", "bi-patch-check-fill", ["accepted", "proofs", "published"]),
    ("closed", _l("Rejected / stopped"), "#dc3545", "bi-x-octagon-fill", ["rejected", "withdrawn", "on_hold"]),
]


PHASE_STATUSES = {key: sts for key, _l2, _c, _i, sts in BOARD_PHASES}
PHASE_OF = {st: key for key, sts in PHASE_STATUSES.items() for st in sts}


def board_columns(papers, show_all=False):
    if show_all:
        cols = []
        for st in m.Paper.PIPELINE + [m.Paper.Status.REJECTED, m.Paper.Status.WITHDRAWN, m.Paper.Status.ON_HOLD]:
            cols.append({"status": st, "label": m.Paper.Status(st).label, "papers": [p for p in papers if p.status == st],
                         "stages": []})
        return cols
    order = {st: i for i, st in enumerate(m.Paper.Status.values)}
    cols = []
    for key, label, color, icon, sts in BOARD_PHASES:
        items = sorted([p for p in papers if p.status in sts], key=lambda p: order.get(p.status, 99))
        stages = [{"status": st, "label": m.Paper.Status(st).label, "count": sum(1 for p in items if p.status == st)}
                  for st in sts]
        cols.append({"phase": key, "label": label, "color": color, "icon": icon, "papers": items, "stages": stages})
    return cols


# ---------------------------------------------------------------- vertical timeline
EVENT_STYLE = {  # kind -> (icon, colour)
    "start": ("bi-lightbulb-fill", "#5b6bbf"),
    "submitted": ("bi-send-fill", "#0d6efd"), "with_editor": ("bi-person-workspace", "#0d6efd"),
    "under_review": ("bi-hourglass-split", "#6f42c1"), "major": ("bi-arrow-repeat", "#fd7e14"),
    "minor": ("bi-wrench-adjustable", "#e0a800"), "revision_submitted": ("bi-send-check-fill", "#6610f2"),
    "accepted": ("bi-patch-check-fill", "#198754"), "rejected": ("bi-x-octagon-fill", "#dc3545"),
    "desk_rejected": ("bi-x-octagon-fill", "#dc3545"), "transfer": ("bi-arrow-left-right", "#be123c"),
    "withdrawn": ("bi-box-arrow-left", "#8a5a83"), "published": ("bi-award-fill", "#198754"),
    "deadline": ("bi-alarm-fill", "#d63384"), "overdue": ("bi-exclamation-triangle-fill", "#dc3545"),
}


def vertical_timeline(papers, months_back=18):
    """Chronological feed of milestones (newest first) grouped by month, for the vertical timeline."""
    now = timezone.now()
    since = now - timedelta(days=months_back * 31)
    items = []

    def add(when, kind, title, paper, sub="", url=None, future=False):
        if when is None or when < since:
            return
        icon, color = EVENT_STYLE.get(kind, ("bi-circle-fill", "#5b6bbf"))
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


# ---------------------------------------------------------------- venues, statistics, matrix views
def venue_groups(papers):
    """Records grouped under the venue of their current submission, biggest venue first."""
    groups = OrderedDict()
    for p in papers:
        sub = p.current_submission
        j = sub.journal if sub else None
        key = j.pk if j else 0
        if key not in groups:
            groups[key] = {"journal": j, "papers": [], "phases": OrderedDict((k, 0) for k, *_r in BOARD_PHASES)}
        groups[key]["papers"].append(p)
        groups[key]["phases"][PHASE_OF.get(p.status, "prep")] += 1
    out = sorted(groups.values(), key=lambda g: (g["journal"] is None, -len(g["papers"]), g["journal"].name.lower() if g["journal"] else ""))
    colors = {k: c for k, _l2, c, _i, _s in BOARD_PHASES}
    labels = {k: lab for k, lab, _c, _i, _s in BOARD_PHASES}
    for g in out:
        n = len(g["papers"])
        g["bar"] = [{"key": k, "label": labels[k], "color": colors[k], "count": v, "pct": round(100 * v / n)}
                    for k, v in g["phases"].items() if v]
    return out


def _bars(counter, labels=None, colors=None, icons=None, limit=None):
    total = sum(counter.values()) or 1
    top = max(counter.values() or [1])
    rows = sorted(counter.items(), key=lambda kv: -kv[1])
    if limit:
        rows = rows[:limit]
    palette = ["#0d6efd", "#6f42c1", "#0aa2c0", "#fd7e14", "#198754", "#d63384", "#e0a800", "#5b6bbf", "#dc3545", "#0d9488"]
    return [{"key": k, "label": (labels or {}).get(k, k), "count": v, "pct": round(100 * v / total),
             "bar": round(100 * v / top), "color": (colors or {}).get(k, palette[i % len(palette)]),
             "icon": (icons or {}).get(k, "")} for i, (k, v) in enumerate(rows) if v]


def stats(papers):
    """Counts for the statistics view, all computed from the filtered list."""
    now = timezone.now()
    phase, typ, kind, pub, month, dl = {}, {}, {}, {}, OrderedDict(), OrderedDict()
    for k, *_r in BOARD_PHASES:
        phase[k] = 0
    for key in ("overdue", "week", "month", "later", "none"):
        dl[key] = 0
    for p in papers:
        phase[PHASE_OF.get(p.status, "prep")] += 1
        typ[p.type] = typ.get(p.type, 0) + 1
        sub = p.current_submission
        if sub:
            kind[sub.journal.kind] = kind.get(sub.journal.kind, 0) + 1
            if sub.journal.publisher:
                pub[sub.journal.publisher] = pub.get(sub.journal.publisher, 0) + 1
            if sub.submitted_at:
                mk = timezone.localtime(sub.submitted_at).strftime("%Y-%m")
                month[mk] = month.get(mk, 0) + 1
        else:
            kind["none"] = kind.get("none", 0) + 1
        due = [d.due_at for d in p.deadlines.all() if d.completed_at is None]
        if not due:
            dl["none"] += 1
        else:
            days = (min(due) - now).total_seconds() / 86400
            dl["overdue" if days < 0 else "week" if days <= 7 else "month" if days <= 30 else "later"] += 1
    phase_lab = {k: lab for k, lab, _c, _i, _s in BOARD_PHASES}
    phase_col = {k: c for k, _l2, c, _i, _s in BOARD_PHASES}
    kind_lab = dict(m.Journal.Kind.choices) | {"none": _l("Not submitted yet")}
    dl_lab = {"overdue": _l("Overdue"), "week": _l("Due within 7 days"), "month": _l("Due within 30 days"),
              "later": _l("Later"), "none": _l("No upcoming deadline")}
    dl_col = {"overdue": "#dc3545", "week": "#fd7e14", "month": "#e0a800", "later": "#0d6efd", "none": "#8a9bb8"}
    months = sorted(month.items())[-12:]
    mmax = max([v for _k, v in months] or [1])
    return {
        "total": len(papers),
        "phase": [r for r in _bars(phase, phase_lab, phase_col)],
        "type": _bars(typ, dict(m.Paper.Type.choices), TYPE_COLORS, TYPE_ICONS),
        "kind": _bars(kind, kind_lab),
        "publisher": _bars(pub, limit=8),
        "deadline": [r for r in _bars(dl, dl_lab, dl_col)],
        "months": [{"key": k, "count": v, "h": max(6, round(100 * v / mmax))} for k, v in months],
    }


def matrix(papers):
    """Type x phase counts; every cell links to the table filtered to that type and phase."""
    types = [(k, lab) for k, lab in m.Paper.Type.choices if any(p.type == k for p in papers)]
    rows = []
    col_tot = OrderedDict((k, 0) for k, *_r in BOARD_PHASES)
    for k, lab in types:
        cells = OrderedDict((ph, 0) for ph in col_tot)
        for p in papers:
            if p.type == k:
                cells[PHASE_OF.get(p.status, "prep")] += 1
        for ph, v in cells.items():
            col_tot[ph] += v
        rows.append({"type": k, "label": lab, "color": TYPE_COLORS.get(k), "icon": TYPE_ICONS.get(k),
                     "cells": [{"phase": ph, "count": v} for ph, v in cells.items()], "total": sum(cells.values())})
    cmax = max([c["count"] for r in rows for c in r["cells"]] or [1]) or 1
    for r in rows:
        for c in r["cells"]:
            c["alpha"] = round(8 + 62 * c["count"] / cmax) if c["count"] else 0
    phases = [{"key": k, "label": lab, "color": c, "icon": i, "total": col_tot[k]} for k, lab, c, i, _s in BOARD_PHASES]
    return {"rows": rows, "phases": phases, "total": sum(col_tot.values())}


# ---------------------------------------------------------------- grouped view (by venue, month, year, ...)
GROUPINGS = [  # key, label, icon, colour
    ("venue", _l("Journal / book"), "bi-journal-bookmark-fill", "#6610f2"),
    ("publisher", _l("Publisher"), "bi-building-fill", "#fd7e14"),
    ("kind", _l("Venue type"), "bi-easel-fill", "#0aa2c0"),
    ("month", _l("Submission month"), "bi-calendar-month-fill", "#0d6efd"),
    ("year", _l("Submission year"), "bi-calendar3", "#5b6bbf"),
    ("due_month", _l("Next deadline month"), "bi-alarm-fill", "#d63384"),
    ("phase", _l("Phase"), "bi-diagram-3-fill", "#198754"),
    ("type", _l("Type"), "bi-collection-fill", "#e0a800"),
    ("group", _l("Research group"), "bi-people-fill", "#0d9488"),
]
GROUPING_KEYS = [g[0] for g in GROUPINGS]
_PALETTE = ["#0d6efd", "#6f42c1", "#0aa2c0", "#fd7e14", "#198754", "#d63384", "#e0a800", "#5b6bbf", "#dc3545", "#0d9488"]


def group_records(papers, by):
    """Groups for the grouped view. Each group: label, optional sub-label/number, icon, colour,
    its records and a phase bar. Dated groupings are newest first; 'none' groups go last."""
    from datetime import date as _date
    phase_meta = {k: (lab, c, i) for k, lab, c, i, _s in BOARD_PHASES}
    groups = OrderedDict()
    for p in papers:
        sub = p.current_submission
        j = sub.journal if sub else None
        sort, label, extra, icon, color, when, url_key = None, "", "", "", None, None, ""
        if by == "venue":
            key = j.pk if j else 0
            label = j.name if j else str(_l("Not submitted yet"))
            extra = " · ".join(x for x in [str(j.get_kind_display()), j.publisher] if x) if j else ""
            icon = ("bi-easel-fill" if j and j.kind == "conference" else "bi-book-fill" if j and j.kind == "book"
                    else "bi-journal-bookmark-fill" if j else "bi-hourglass-split")
            url_key = f"venue={j.pk}" if j else "venue_kind=none"
        elif by == "publisher":
            key = (j.publisher or "—") if j else ""
            label = key or str(_l("Not submitted yet"))
            icon = "bi-building-fill"
            url_key = f"publisher={key}" if j and j.publisher else ""
        elif by == "kind":
            key = j.kind if j else ""
            label = str(j.get_kind_display()) if j else str(_l("Not submitted yet"))
            icon = {"conference": "bi-easel-fill", "book": "bi-book-fill"}.get(key, "bi-journal-bookmark-fill" if j else "bi-hourglass-split")
            url_key = f"venue_kind={key or 'none'}"
        elif by in ("month", "year"):
            dt = sub.submitted_at if sub and sub.submitted_at else None
            if dt:
                dt = timezone.localtime(dt)
                key = (dt.year, dt.month) if by == "month" else (dt.year,)
                when = _date(dt.year, dt.month if by == "month" else 1, 1)
                label = f"{dt.month:02d} / {dt.year}" if by == "month" else str(dt.year)
                sort = key
                url_key = f"year={dt.year}"
            else:
                key = ()
                label = str(_l("Not submitted yet"))
            icon = "bi-calendar-month-fill" if by == "month" else "bi-calendar3"
        elif by == "due_month":
            due = [d.due_at for d in p.deadlines.all() if d.completed_at is None]
            if due:
                dt = timezone.localtime(min(due))
                key = (dt.year, dt.month)
                when = _date(dt.year, dt.month, 1)
                label = f"{dt.month:02d} / {dt.year}"
                sort = key
            else:
                key = ()
                label = str(_l("No upcoming deadline"))
            icon = "bi-alarm-fill"
        elif by == "phase":
            key = PHASE_OF.get(p.status, "prep")
            label, color, icon = phase_meta[key]
            label = str(label)
            sort = [k for k, *_r in BOARD_PHASES].index(key)
            url_key = f"phase={key}"
        elif by == "type":
            key = p.type
            label, color, icon = str(p.get_type_display()), TYPE_COLORS.get(p.type), TYPE_ICONS.get(p.type)
            url_key = f"type={key}"
        else:  # research group
            key = p.group_id
            label, icon = p.group.name, "bi-people-fill"
            url_key = f"group={key}"
        if key not in groups:
            groups[key] = {"key": key, "label": label, "extra": extra, "icon": icon, "color": color, "when": when,
                           "sort": sort, "url_key": url_key, "papers": [], "empty": key in (0, "", ())}
        groups[key]["papers"].append(p)
    out = list(groups.values())
    if by in ("month", "year"):
        out.sort(key=lambda g: (g["empty"], tuple(-x for x in (g["sort"] or ()))))
    elif by == "due_month":
        out.sort(key=lambda g: (g["empty"], g["sort"] or ()))
    elif by == "phase":
        out.sort(key=lambda g: g["sort"])
    else:
        out.sort(key=lambda g: (g["empty"], -len(g["papers"]), str(g["label"]).lower()))
    labels = {k: lab for k, lab, _c, _i, _s in BOARD_PHASES}
    colors = {k: c for k, _l2, c, _i, _s in BOARD_PHASES}
    for i, g in enumerate(out):
        g["color"] = g["color"] or ("#8a9bb8" if g["empty"] else _PALETTE[i % len(_PALETTE)])
        counts = OrderedDict((k, 0) for k, *_r in BOARD_PHASES)
        for p in g["papers"]:
            counts[PHASE_OF.get(p.status, "prep")] += 1
        n = len(g["papers"])
        g["bar"] = [{"label": labels[k], "color": colors[k], "count": v, "pct": round(100 * v / n)} for k, v in counts.items() if v]
    return out
