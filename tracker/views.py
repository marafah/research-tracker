import csv
import hmac
import re
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import forms as f
from . import models as m
from .permissions import (can_edit_paper, can_manage_group, get_group_or_403, get_paper_or_403, role,
                          visible_groups, visible_papers)
from .reminders import run_digest, run_reminders
from .services import apply_submission_change, log_activity, notify_new_deadline, send_templated_email, status_counts

User = get_user_model()


def _greeting():
    h = timezone.localtime().hour
    if h < 12:
        return _("Good morning")
    if h < 18:
        return _("Good afternoon")
    return _("Good evening")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@login_required
def dashboard(request):
    user = request.user
    papers = visible_papers(user)
    if not visible_groups(user).exists():
        messages.info(request, _("Welcome! Start by creating your first research group."))
        return redirect("group_create")
    now = timezone.now()
    open_dl = (m.Deadline.objects.filter(paper__in=papers, completed_at__isnull=True)
               .select_related("paper").prefetch_related("assignees").order_by("due_at"))
    my_dl = open_dl.filter(Q(assignees=user) | Q(paper__lead=user)).distinct()
    ctx = {
        "counts": status_counts(papers),
        "total": papers.count(),
        "active": papers.exclude(status__in=m.Paper.CLOSED + [m.Paper.Status.REJECTED]).count(),
        "under_review": papers.filter(status__in=["submitted", "under_review", "resubmitted"]).count(),
        "in_review_strict": papers.filter(status="under_review").count(),
        "published_year": papers.filter(status=m.Paper.Status.PUBLISHED,
                                        publication_date__year=now.year).count(),
        "accepted_year": m.Submission.objects.filter(paper__in=papers, accepted_at__year=now.year).count(),
        "overdue": open_dl.filter(due_at__lt=now),
        "upcoming": open_dl.filter(due_at__gte=now, due_at__lte=now + timedelta(days=30))[:12],
        "my_deadlines": my_dl[:8],
        "action_papers": papers.filter(status__in=m.Paper.ACTION_NEEDED),
        "my_comments": m.ReviewComment.objects.filter(
            assigned_to=user, state__in=[m.ReviewComment.State.OPEN, m.ReviewComment.State.IN_PROGRESS]
        ).select_related("submission__paper", "submission__journal")[:10],
        "missing_data": [p for p in papers.exclude(status__in=m.Paper.CLOSED).prefetch_related("authors")
                         if p.authors_missing_data()][:8],
        "activity": m.Activity.objects.filter(paper__in=papers).select_related("user", "paper")[:12],
        "profile_missing": user.missing_profile_fields(),
        "week_count": open_dl.filter(due_at__gte=now, due_at__lte=now + timedelta(days=7)).count(),
        "greeting": _greeting(),
        "recent_papers": papers.select_related("group").prefetch_related(
            "submissions__journal", "deadlines", "authors__user").order_by("-updated_at")[:6],
    }
    ctx.update(_dashboard_charts(papers, open_dl, now))
    return render(request, "tracker/dashboard.html", ctx)


def _dashboard_charts(papers, open_dl, now):
    """Status donut, type bars and a 7-day strip for the dashboard."""
    from . import workspace as ws
    from .templatetags.tracker_tags import STATUS_HEX
    counts = status_counts(papers)
    stops, acc = [], 0
    for c in counts:
        share = 100 * c["count"] / (sum(x["count"] for x in counts) or 1)
        c["color"] = STATUS_HEX.get(c["code"], "#6c757d")
        stops.append(f"{c['color']} {acc:.2f}% {acc + share:.2f}%")
        acc += share
    types = {}
    for t in papers.values_list("type", flat=True):
        types[t] = types.get(t, 0) + 1
    tmax = max(types.values() or [1])
    type_rows = [{"key": k, "label": lab, "count": types[k], "pct": round(100 * types[k] / tmax),
                  "color": ws.TYPE_COLORS[k], "icon": ws.TYPE_ICONS[k]}
                 for k, lab in m.Paper.Type.choices if types.get(k)]
    today = timezone.localdate()
    per_day = {}
    for d in open_dl.filter(due_at__date__gte=today, due_at__date__lt=today + timedelta(days=7)):
        day = timezone.localtime(d.due_at).date()
        per_day[day] = per_day.get(day, 0) + 1
    week = [{"date": today + timedelta(days=i), "count": per_day.get(today + timedelta(days=i), 0),
             "today": i == 0} for i in range(7)]
    total = sum(c["count"] for c in counts)
    done = sum(c["count"] for c in counts if c["code"] in ("accepted", "proofs", "published"))
    return {"donut": ", ".join(stops) or "var(--rt-surface-2) 0 100%", "status_rows": counts,
            "type_rows": type_rows, "week_strip": week,
            "success_rate": round(100 * done / total) if total else 0}


# ---------------------------------------------------------------------------
# Papers
# ---------------------------------------------------------------------------
def _filtered_papers(request):
    groups = visible_groups(request.user)
    form = f.PaperFilterForm(request.GET or None, groups=groups)
    qs = visible_papers(request.user).prefetch_related("submissions__journal", "deadlines", "authors")
    if form.is_valid():
        d = form.cleaned_data
        if d["q"]:
            qs = qs.filter(Q(title__icontains=d["q"]) | Q(short_title__icontains=d["q"]) |
                           Q(keywords__icontains=d["q"]) | Q(submissions__journal__name__icontains=d["q"]) |
                           Q(submissions__manuscript_id__icontains=d["q"])).distinct()
        if d["status"] == "active":
            qs = qs.exclude(status__in=m.Paper.CLOSED + [m.Paper.Status.REJECTED])
        elif d["status"]:
            qs = qs.filter(status=d["status"])
        if d["type"]:
            qs = qs.filter(type=d["type"])
        if d["group"]:
            qs = qs.filter(group=d["group"])
        if d["mine"]:
            qs = qs.filter(Q(lead=request.user) | Q(authors__user=request.user)).distinct()
    return form, qs


def _qs(request, **changes):
    params = request.GET.copy()
    for k, v in changes.items():
        if v in (None, ""):
            params.pop(k, None)
        else:
            params[k] = v
    return params.urlencode()


@login_required
def papers_workspace(request, force_view=None):
    from . import workspace as ws
    view = force_view or request.GET.get("view") or request.session.get("papers_view", "cards")
    if view not in ws.VIEW_KEYS:
        view = "cards"
    request.session["papers_view"] = view
    groups = visible_groups(request.user)
    form = f.PaperFilterForm(request.GET or None, groups=groups)
    data = form.cleaned_data if form.is_valid() else {}
    base = (visible_papers(request.user)
            .select_related("group", "lead")
            .prefetch_related("submissions__journal", "submissions__events", "deadlines", "authors__user"))
    without_type = ws.apply_filters(base, data, request.user, skip_type=True)
    papers = list(ws.apply_filters(base, data, request.user))
    group_by = request.GET.get("group_by", request.session.get("papers_group_by", "status"))
    if group_by not in dict(ws.GROUP_BY):
        group_by = "status"
    request.session["papers_group_by"] = group_by
    ctx = {
        "form": form, "papers": papers, "view": view, "group_by": group_by,
        "views": [{"key": k, "label": l, "icon": i, "color": c,
                   "url": reverse("paper_list") + "?" + _qs(request, view=k, tl=None, all=None, month=None),
                   "active": k == view} for k, l, i, c in ws.VIEWS],
        "kpi_urls": {k: reverse("paper_list") + "?" + _qs(request, status=k or None)
                     for k in ("", "active", "in_review", "accepted_pub")},
        "chips": [c | {"url": "?" + _qs(request, type=c["key"])}
                  for c in ws.type_chips(without_type, data.get("type"))],
        "group_choices": ws.GROUP_BY, "kpi": ws.kpis(papers),
        "statuses": m.Paper.Status.choices, "type_icons": ws.TYPE_ICONS, "type_colors": ws.TYPE_COLORS,
        "show_all": bool(request.GET.get("all")), "qs_base": _qs(request),
    }
    if view == "cards":
        ctx["groups"] = ws.grouped(papers, group_by)
    elif view == "timeline":
        tl_mode = request.GET.get("tl") or request.session.get("papers_tl", "vertical")
        tl_mode = tl_mode if tl_mode in ("vertical", "gantt") else "vertical"
        request.session["papers_tl"] = tl_mode
        ctx["tl_mode"] = tl_mode
        ctx["tl_urls"] = {k: "?" + _qs(request, tl=k) for k in ("vertical", "gantt")}
        ctx["tl"] = ws.timeline(papers) if tl_mode == "gantt" else ws.vertical_timeline(papers)
    elif view == "calendar":
        ctx["cal"] = ws.month_calendar(papers, request.GET.get("month"),
                                       first_weekday=5 if request.LANGUAGE_CODE == "ar" else 6)
        ctx["month_url"] = lambda mth: "?" + _qs(request, month=mth)
        ctx["prev_url"] = "?" + _qs(request, month=ctx["cal"]["prev"])
        ctx["next_url"] = "?" + _qs(request, month=ctx["cal"]["next"])
        ctx["this_url"] = "?" + _qs(request, month=ctx["cal"]["this"])
    elif view == "board":
        ctx["columns"] = ws.board_columns(papers, ctx["show_all"])
        ctx["toggle_all_url"] = "?" + _qs(request, all=None if ctx["show_all"] else "1")
    return render(request, "tracker/papers.html", ctx)


@login_required
def paper_list(request):
    return papers_workspace(request)


@login_required
def paper_board(request):
    params = request.GET.copy()
    params["view"] = "board"
    return redirect(reverse("paper_list") + "?" + params.urlencode())


@login_required
def paper_create(request):
    form = f.PaperForm(request.POST or None, user=request.user)
    if not form.fields["group"].queryset.exists():
        messages.warning(request, _("Create or join a research group first."))
        return redirect("group_create")
    if request.method == "POST" and form.is_valid():
        paper = form.save(commit=False)
        paper.created_by = request.user
        paper.save()
        if paper.lead:
            m.PaperAuthor.objects.create(paper=paper, user=paper.lead, order=1, is_corresponding=True)
        log_activity(request.user, _("created the paper"), paper)
        messages.success(request, _("Paper created. Now add co-authors and a target journal."))
        return redirect(paper)
    return render(request, "tracker/form.html", {"form": form, "title": _("New paper / proposal")})


@login_required
def paper_detail(request, pk):
    paper = get_paper_or_403(request.user, pk)
    subs = paper.submissions.select_related("journal", "submitted_by").prefetch_related(
        "events__recorded_by", "review_comments__assigned_to")
    return render(request, "tracker/paper_detail.html", {
        "paper": paper,
        "can_edit": can_edit_paper(request.user, paper),
        "authors": paper.authors.select_related("user"),
        "submissions": subs,
        "deadlines": paper.deadlines.prefetch_related("assignees").select_related("submission__journal"),
        "attachments": paper.attachments.select_related("uploaded_by", "submission__journal"),
        "activity": paper.activities.select_related("user")[:25],
        "statuses": m.Paper.Status.choices,
    })


@login_required
def paper_edit(request, pk):
    paper = get_paper_or_403(request.user, pk, edit=True)
    old_status = paper.status
    form = f.PaperForm(request.POST or None, instance=paper, user=request.user)
    if request.method == "POST" and form.is_valid():
        paper = form.save()
        if old_status != paper.status:
            log_activity(request.user, _("changed status to %(s)s") % {"s": paper.get_status_display()}, paper)
        else:
            log_activity(request.user, _("edited the paper details"), paper)
        messages.success(request, _("Saved."))
        return redirect(paper)
    return render(request, "tracker/form.html", {"form": form, "title": _("Edit paper"), "back": paper})


@login_required
@require_POST
def paper_status(request, pk):
    paper = get_paper_or_403(request.user, pk, edit=True)
    new = request.POST.get("status")
    if new in m.Paper.Status.values and new != paper.status:
        paper.status = new
        paper.save(update_fields=["status", "updated_at"])
        log_activity(request.user, _("changed status to %(s)s") % {"s": paper.get_status_display()}, paper)
        messages.success(request, _("Status updated."))
    return redirect(request.POST.get("next") or paper.get_absolute_url())


@login_required
def paper_delete(request, pk):
    paper = get_paper_or_403(request.user, pk, edit=True)
    if not can_manage_group(request.user, paper.group) and paper.created_by_id != request.user.id:
        raise PermissionDenied
    if request.method == "POST":
        paper.delete()
        messages.success(request, _("Paper deleted."))
        return redirect("paper_list")
    return render(request, "tracker/confirm_delete.html", {"object": paper, "back": paper})


# ---------------------------------------------------------------------------
# Authors
# ---------------------------------------------------------------------------
@login_required
def author_form(request, pk, author_pk=None):
    paper = get_paper_or_403(request.user, pk, edit=True)
    author = get_object_or_404(m.PaperAuthor, pk=author_pk, paper=paper) if author_pk else None
    initial = {"order": paper.authors.count() + 1} if not author else None
    form = f.AuthorForm(request.POST or None, instance=author, paper=paper, initial=initial)
    if request.method == "POST" and form.is_valid():
        a = form.save(commit=False)
        a.paper = paper
        a.save()
        log_activity(request.user, (_("updated author %(n)s") if author else _("added author %(n)s")) % {"n": a.name},
                     paper)
        if "request_data" in request.POST and a.email:
            _send_author_request(request, a)
        return redirect(paper.get_absolute_url() + "#authors")
    return render(request, "tracker/form.html", {"form": form, "back": paper,
                                                 "title": _("Edit author") if author else _("Add author"),
                                                 "extra_submit": None if author else _("Save & request their data")})


@login_required
@require_POST
def author_delete(request, pk, author_pk):
    paper = get_paper_or_403(request.user, pk, edit=True)
    a = get_object_or_404(m.PaperAuthor, pk=author_pk, paper=paper)
    log_activity(request.user, _("removed author %(n)s") % {"n": a.name}, paper)
    a.delete()
    return redirect(paper.get_absolute_url() + "#authors")


def _send_author_request(request, author):
    send_templated_email(author.email, _("Please complete your author details"), "author_request",
                         {"author": author, "paper": author.paper, "sender": request.user,
                          "url": author.get_update_url()},
                         author.user.preferred_language if author.user else request.LANGUAGE_CODE)
    author.data_requested_at = timezone.now()
    author.save(update_fields=["data_requested_at"])
    log_activity(request.user, _("requested author data from %(n)s") % {"n": author.name}, author.paper)
    messages.success(request, _("Request emailed to %(e)s.") % {"e": author.email})


@login_required
@require_POST
def author_request_data(request, pk, author_pk):
    paper = get_paper_or_403(request.user, pk, edit=True)
    a = get_object_or_404(m.PaperAuthor, pk=author_pk, paper=paper)
    if not a.email:
        messages.error(request, _("This author has no email address."))
    else:
        _send_author_request(request, a)
    return redirect(paper.get_absolute_url() + "#authors")


def author_self_update(request, token):
    """Public page (no login) where a co-author confirms their own details via a secret link."""
    a = get_object_or_404(m.PaperAuthor.objects.select_related("paper"), update_token=token)
    form = f.AuthorSelfUpdateForm(request.POST or None, instance=a)
    if request.method == "POST" and form.is_valid():
        form.save()
        m.Activity.objects.create(paper=a.paper, group=a.paper.group, user=a.user,
                                  verb=_("%(n)s updated their author details") % {"n": a.name})
        return render(request, "tracker/author_self_update.html", {"done": True, "author": a})
    return render(request, "tracker/author_self_update.html", {"form": form, "author": a})


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------
@login_required
def submission_form(request, pk, sub_pk=None):
    paper = get_paper_or_403(request.user, pk, edit=True)
    sub = get_object_or_404(m.Submission, pk=sub_pk, paper=paper) if sub_pk else None
    prev = sub.decision if sub else None
    initial = None
    if not sub:
        initial = {"submitted_by": request.user, "decision": m.Submission.Decision.DRAFT}
        if "journal" in request.GET:
            initial["journal"] = request.GET["journal"]
    form = f.SubmissionForm(request.POST or None, instance=sub, paper=paper, initial=initial)
    if request.method == "POST" and form.is_valid():
        s = form.save(commit=False)
        s.paper = paper
        s.save()
        if not sub:
            log_activity(request.user, _("added a submission to %(j)s") % {"j": s.journal.name}, paper)
        apply_submission_change(s, request.user, previous_decision=prev, note=form.cleaned_data.get("note", ""))
        messages.success(request, _("Submission saved."))
        return redirect(s.get_absolute_url())
    return render(request, "tracker/form.html", {
        "form": form, "back": paper,
        "title": _("Update submission") if sub else _("New submission"),
        "help": _("Tip: when you set the state to Major/Minor revision with a due date, a deadline with "
                  "email reminders is created automatically."),
        "add_journal": True})


# ---------------------------------------------------------------------------
# Deadlines
# ---------------------------------------------------------------------------
@login_required
def deadline_form(request, pk, dl_pk=None):
    paper = get_paper_or_403(request.user, pk, edit=True)
    dl = get_object_or_404(m.Deadline, pk=dl_pk, paper=paper) if dl_pk else None
    old_due = dl.due_at if dl else None
    initial = None if dl else {"assignees": [paper.lead] if paper.lead else []}
    form = f.DeadlineForm(request.POST or None, instance=dl, paper=paper, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.save(commit=False)
        d.paper = paper
        if not dl:
            d.created_by = request.user
        d.save()
        form.save_m2m()
        if dl and old_due != d.due_at:
            d.reminder_logs.all().delete()
        if not dl:
            notify_new_deadline(d)
            log_activity(request.user, _("added deadline “%(t)s”") % {"t": d.title}, paper)
        return redirect(paper.get_absolute_url() + "#deadlines")
    return render(request, "tracker/form.html", {"form": form, "back": paper,
                                                 "title": _("Edit deadline") if dl else _("New deadline")})


@login_required
@require_POST
def deadline_toggle(request, pk, dl_pk):
    paper = get_paper_or_403(request.user, pk, edit=True)
    dl = get_object_or_404(m.Deadline, pk=dl_pk, paper=paper)
    if dl.completed_at:
        dl.completed_at, dl.completed_by = None, None
        log_activity(request.user, _("reopened “%(t)s”") % {"t": dl.title}, paper)
    else:
        dl.completed_at, dl.completed_by = timezone.now(), request.user
        log_activity(request.user, _("completed “%(t)s”") % {"t": dl.title}, paper)
    dl.save(update_fields=["completed_at", "completed_by"])
    return redirect(request.POST.get("next") or paper.get_absolute_url() + "#deadlines")


@login_required
@require_POST
def deadline_delete(request, pk, dl_pk):
    paper = get_paper_or_403(request.user, pk, edit=True)
    get_object_or_404(m.Deadline, pk=dl_pk, paper=paper).delete()
    return redirect(paper.get_absolute_url() + "#deadlines")


@login_required
def deadline_list(request):
    from . import workspace as ws
    papers = visible_papers(request.user)
    qs = (m.Deadline.objects.filter(paper__in=papers).select_related("paper", "submission__journal")
          .prefetch_related("assignees"))
    show = request.GET.get("show", "open")
    view = request.GET.get("view", "list")
    if show == "mine":
        qs = qs.filter(Q(assignees=request.user) | Q(paper__lead=request.user)).distinct()
    now = timezone.now()
    week = now + timedelta(days=7)
    month = now + timedelta(days=30)
    open_qs = qs.filter(completed_at__isnull=True).order_by("due_at")
    buckets = [
        {"key": "overdue", "label": _("Overdue"), "icon": "bi-exclamation-octagon", "tone": "danger",
         "items": list(open_qs.filter(due_at__lt=now))},
        {"key": "week", "label": _("Next 7 days"), "icon": "bi-lightning-charge", "tone": "warning",
         "items": list(open_qs.filter(due_at__gte=now, due_at__lt=week))},
        {"key": "month", "label": _("Next 30 days"), "icon": "bi-calendar-week", "tone": "primary",
         "items": list(open_qs.filter(due_at__gte=week, due_at__lt=month))},
        {"key": "later", "label": _("Later"), "icon": "bi-calendar3", "tone": "slate",
         "items": list(open_qs.filter(due_at__gte=month))},
    ]
    if show == "done":
        buckets = [{"key": "done", "label": _("Completed"), "icon": "bi-check2-all", "tone": "success",
                    "items": list(qs.filter(completed_at__isnull=False).order_by("-completed_at")[:100])}]
    ctx = {"buckets": buckets, "show": show, "view": view,
           "counts": {"open": qs.filter(completed_at__isnull=True).count(),
                      "overdue": len(buckets[0]["items"]) if show != "done" else 0,
                      "week": len(buckets[1]["items"]) if show != "done" else 0,
                      "done": qs.filter(completed_at__isnull=False).count()}}
    if view == "calendar":
        ctx["cal"] = ws.month_calendar(list(papers), request.GET.get("month"),
                                       first_weekday=5 if request.LANGUAGE_CODE == "ar" else 6)
        ctx["prev_url"] = "?" + _qs(request, month=ctx["cal"]["prev"])
        ctx["next_url"] = "?" + _qs(request, month=ctx["cal"]["next"])
        ctx["this_url"] = "?" + _qs(request, month=ctx["cal"]["this"])
    return render(request, "tracker/deadline_list.html", ctx)


# ---------------------------------------------------------------------------
# Reviewer comments & response letter
# ---------------------------------------------------------------------------
def _sub_for(request, pk, sub_pk):
    paper = get_paper_or_403(request.user, pk, edit=True)
    return paper, get_object_or_404(m.Submission, pk=sub_pk, paper=paper)


@login_required
def comment_form(request, pk, sub_pk, c_pk=None):
    paper, sub = _sub_for(request, pk, sub_pk)
    c = get_object_or_404(m.ReviewComment, pk=c_pk, submission=sub) if c_pk else None
    form = f.ReviewCommentForm(request.POST or None, instance=c, paper=paper,
                               initial=None if c else {"round": sub.round})
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.submission = sub
        prev_assignee = c.assigned_to_id if c else None
        obj.save()
        if obj.assigned_to and obj.assigned_to_id != prev_assignee and obj.assigned_to != request.user:
            send_templated_email(obj.assigned_to.email, _("A reviewer comment was assigned to you"),
                                 "comment_assigned", {"comment": obj, "paper": paper, "sender": request.user},
                                 obj.assigned_to.preferred_language)
        return redirect(paper.get_absolute_url() + f"#submission-{sub.pk}")
    return render(request, "tracker/form.html", {"form": form, "back": paper,
                                                 "title": _("Reviewer comment") + f" — {sub.journal.name}"})


_SPLIT = re.compile(r"\n\s*\n|\n(?=\s*(?:\d+[\.\)\-]|[-•*])\s+)")


@login_required
def comment_bulk(request, pk, sub_pk):
    """Paste a whole review; it is split into individual trackable comments."""
    paper, sub = _sub_for(request, pk, sub_pk)
    form = f.BulkCommentsForm(request.POST or None, initial={"round": sub.round})
    if request.method == "POST" and form.is_valid():
        parts = [p.strip() for p in _SPLIT.split(form.cleaned_data["text"]) if p and p.strip()]
        for i, part in enumerate(parts, 1):
            m.ReviewComment.objects.create(submission=sub, round=form.cleaned_data["round"],
                                           reviewer=form.cleaned_data["reviewer"], number=str(i), comment=part)
        log_activity(request.user, _("imported %(n)s comments from %(r)s") % {
            "n": len(parts), "r": form.cleaned_data["reviewer"]}, paper)
        messages.success(request, _("%(n)s comments imported. Now assign them to co-authors.") % {"n": len(parts)})
        return redirect(paper.get_absolute_url() + f"#submission-{sub.pk}")
    return render(request, "tracker/form.html", {"form": form, "back": paper,
                                                 "title": _("Import reviewer comments")})


@login_required
def response_letter(request, pk, sub_pk):
    paper = get_paper_or_403(request.user, pk)
    sub = get_object_or_404(m.Submission, pk=sub_pk, paper=paper)
    rnd = int(request.GET.get("round", sub.round if sub.review_comments.filter(round=sub.round).exists()
                              else max(sub.round - 1, 1)))
    comments = sub.review_comments.filter(round=rnd).select_related("assigned_to")
    reviewers = {}
    for c in comments:
        reviewers.setdefault(c.reviewer, []).append(c)
    return render(request, "tracker/response_letter.html",
                  {"paper": paper, "sub": sub, "reviewers": reviewers, "round": rnd})


# ---------------------------------------------------------------------------
# Attachments (served through permission check, never publicly)
# ---------------------------------------------------------------------------
@login_required
def attachment_add(request, pk):
    paper = get_paper_or_403(request.user, pk, edit=True)
    form = f.AttachmentForm(request.POST or None, request.FILES or None, paper=paper)
    if request.method == "POST" and form.is_valid():
        a = form.save(commit=False)
        a.paper, a.uploaded_by = paper, request.user
        a.full_clean()
        a.save()
        log_activity(request.user, _("uploaded %(f)s") % {"f": a.filename}, paper)
        return redirect(paper.get_absolute_url() + "#files")
    return render(request, "tracker/form.html", {"form": form, "back": paper, "title": _("Upload file"),
                                                 "multipart": True})


@login_required
def attachment_download(request, pk, att_pk):
    paper = get_paper_or_403(request.user, pk)
    a = get_object_or_404(m.Attachment, pk=att_pk, paper=paper)
    try:
        return FileResponse(a.file.open("rb"), as_attachment=True, filename=a.filename)
    except FileNotFoundError:
        raise Http404


@login_required
@require_POST
def attachment_delete(request, pk, att_pk):
    paper = get_paper_or_403(request.user, pk, edit=True)
    a = get_object_or_404(m.Attachment, pk=att_pk, paper=paper)
    a.file.delete(save=False)
    a.delete()
    return redirect(paper.get_absolute_url() + "#files")


# ---------------------------------------------------------------------------
# Groups & invitations
# ---------------------------------------------------------------------------
@login_required
def group_list(request):
    groups = visible_groups(request.user).annotate(n_members=Count("memberships", distinct=True),
                                                   n_papers=Count("papers", distinct=True))
    return render(request, "tracker/group_list.html", {"groups": groups})


@login_required
def group_create(request):
    form = f.GroupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        g = form.save(commit=False)
        g.created_by = request.user
        g.save()
        m.GroupMembership.objects.create(group=g, user=request.user, role=m.GroupMembership.Role.OWNER)
        log_activity(request.user, _("created the group"), group=g)
        return redirect(g)
    return render(request, "tracker/form.html", {"form": form, "title": _("New research group")})


@login_required
def group_detail(request, pk):
    g = get_group_or_403(request.user, pk)
    manage = can_manage_group(request.user, g)
    return render(request, "tracker/group_detail.html", {
        "group": g, "manage": manage,
        "memberships": g.memberships.select_related("user").order_by("role", "user__full_name"),
        "invitations": g.invitations.filter(accepted_at__isnull=True) if manage else [],
        "papers": visible_papers(request.user).filter(group=g),
        "invite_form": f.InvitationForm() if manage else None,
        "roles": m.GroupMembership.Role.choices,
    })


@login_required
def group_edit(request, pk):
    g = get_group_or_403(request.user, pk, manage=True)
    form = f.GroupForm(request.POST or None, instance=g)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(g)
    return render(request, "tracker/form.html", {"form": form, "title": _("Edit group"), "back": g})


@login_required
@require_POST
def group_invite(request, pk):
    g = get_group_or_403(request.user, pk, manage=True)
    form = f.InvitationForm(request.POST)
    if form.is_valid():
        email = form.cleaned_data["email"].lower()
        existing = User.objects.filter(email=email).first()
        if existing and g.memberships.filter(user=existing).exists():
            messages.info(request, _("%(e)s is already a member.") % {"e": email})
            return redirect(g)
        inv = form.save(commit=False)
        inv.email, inv.group, inv.invited_by = email, g, request.user
        inv.save()
        send_templated_email(email, _("Invitation to join %(g)s") % {"g": g.name}, "invitation",
                             {"inv": inv, "url": inv.get_accept_url()},
                             existing.preferred_language if existing else request.LANGUAGE_CODE)
        log_activity(request.user, _("invited %(e)s") % {"e": email}, group=g)
        messages.success(request, _("Invitation sent to %(e)s. You can also share this link: %(u)s") % {
            "e": email, "u": inv.get_accept_url()})
    else:
        messages.error(request, _("Please enter a valid email."))
    return redirect(g)


@login_required
@require_POST
def invitation_revoke(request, pk, inv_pk):
    g = get_group_or_403(request.user, pk, manage=True)
    get_object_or_404(m.Invitation, pk=inv_pk, group=g).delete()
    return redirect(g)


def invitation_accept(request, token):
    inv = get_object_or_404(m.Invitation.objects.select_related("group"), token=token)
    if not inv.is_valid:
        return render(request, "tracker/invitation.html", {"inv": inv, "invalid": True})
    if request.user.is_authenticated:
        if request.method == "POST":
            m.GroupMembership.objects.get_or_create(group=inv.group, user=request.user,
                                                    defaults={"role": inv.role})
            if inv.role == m.GroupMembership.Role.EXTERNAL and not request.user.is_external:
                request.user.is_external = True
                request.user.save(update_fields=["is_external"])
            inv.accepted_at, inv.accepted_by = timezone.now(), request.user
            inv.save(update_fields=["accepted_at", "accepted_by"])
            # Link any author rows that were typed in with this email before the account existed.
            m.PaperAuthor.objects.filter(email__iexact=request.user.email, user__isnull=True,
                                         paper__group=inv.group).update(user=request.user)
            log_activity(request.user, _("joined the group"), group=inv.group)
            messages.success(request, _("Welcome to %(g)s!") % {"g": inv.group.name})
            return redirect(inv.group)
        return render(request, "tracker/invitation.html", {"inv": inv})
    # Not logged in: sign up (or log in) first, then come back here.
    from accounts.forms import SignupForm
    if User.objects.filter(email__iexact=inv.email).exists():
        messages.info(request, _("Please log in to accept the invitation."))
        from django.urls import reverse
        return redirect(f"{reverse('login')}?next={request.path}")
    form = SignupForm(request.POST or None, initial={"email": inv.email})
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.is_external = inv.role == m.GroupMembership.Role.EXTERNAL
        user.preferred_language = request.LANGUAGE_CODE[:2] if request.LANGUAGE_CODE[:2] in ("ar", "en") else "en"
        user.save()
        login(request, user, backend="accounts.backends.EmailBackend")
        return invitation_accept(_as_post(request), token)
    return render(request, "tracker/invitation.html", {"inv": inv, "signup_form": form})


def _as_post(request):
    request.method = "POST"
    return request


@login_required
@require_POST
def member_update(request, pk, mem_pk):
    g = get_group_or_403(request.user, pk, manage=True)
    mem = get_object_or_404(m.GroupMembership, pk=mem_pk, group=g)
    action = request.POST.get("action")
    owners = g.memberships.filter(role=m.GroupMembership.Role.OWNER)
    if mem.role == m.GroupMembership.Role.OWNER and owners.count() == 1 and action in ("remove", "role"):
        if action == "remove" or request.POST.get("role") != "owner":
            messages.error(request, _("A group needs at least one owner."))
            return redirect(g)
    if action == "remove":
        mem.delete()
        messages.success(request, _("Member removed."))
    elif action == "role" and request.POST.get("role") in m.GroupMembership.Role.values:
        if request.POST["role"] == "owner" and role(request.user, g) != "owner":
            raise PermissionDenied
        mem.role = request.POST["role"]
        mem.save(update_fields=["role"])
    return redirect(g)


# ---------------------------------------------------------------------------
# Journals
# ---------------------------------------------------------------------------
@login_required
def journal_list(request):
    q = request.GET.get("q", "")
    quartile = request.GET.get("quartile", "")
    view = request.GET.get("view", "cards")
    qs = m.Journal.objects.annotate(n=Count("submissions")).order_by("-n", "name")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(publisher__icontains=q) | Q(issn__icontains=q))
    if quartile in ("Q1", "Q2", "Q3", "Q4"):
        qs = qs.filter(quartile=quartile)
    elif quartile == "flagged":
        qs = qs.filter(flagged=True)
    chips = [("", _("All")), ("Q1", "Q1"), ("Q2", "Q2"), ("Q3", "Q3"), ("Q4", "Q4"), ("flagged", _("Questionable"))]
    return render(request, "tracker/journal_list.html", {"journals": qs, "q": q, "quartile": quartile,
                                                         "view": view, "quartile_chips": chips})


@login_required
def journal_form(request, pk=None):
    j = get_object_or_404(m.Journal, pk=pk) if pk else None
    if j and not (request.user.is_staff or j.created_by_id in (None, request.user.id)):
        raise PermissionDenied
    form = f.JournalForm(request.POST or None, instance=j)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if not j:
            obj.created_by = request.user
        obj.save()
        nxt = request.GET.get("next")
        if nxt and nxt.startswith("/"):
            return redirect(f"{nxt}{'&' if '?' in nxt else '?'}journal={obj.pk}")
        return redirect(obj)
    return render(request, "tracker/form.html", {"form": form, "title": _("Edit venue") if j else _("New journal / venue")})


@login_required
def journal_detail(request, pk):
    j = get_object_or_404(m.Journal, pk=pk)
    subs = j.submissions.filter(paper__in=visible_papers(request.user)).select_related("paper")
    return render(request, "tracker/journal_detail.html", {"journal": j, "subs": subs, "stats": j.stats()})


# ---------------------------------------------------------------------------
# Reports, export, calendar
# ---------------------------------------------------------------------------
@login_required
def reports(request):
    papers = visible_papers(request.user)
    year = request.GET.get("year")
    years = sorted({d.year for d in papers.filter(publication_date__isnull=False)
                   .values_list("publication_date", flat=True)} | {timezone.now().year}, reverse=True)
    published = papers.filter(status__in=[m.Paper.Status.PUBLISHED, m.Paper.Status.PROOFS,
                                          m.Paper.Status.ACCEPTED]).prefetch_related("authors", "submissions__journal")
    if year and year.isdigit():
        published = published.filter(Q(publication_date__year=int(year)) |
                                     Q(publication_date__isnull=True, submissions__accepted_at__year=int(year))).distinct()
    subs = m.Submission.objects.filter(paper__in=papers).exclude(submitted_at__isnull=True)
    decided = [s for s in subs if s.first_decision_at]
    per_journal = (subs.values("journal__name").annotate(
        total=Count("id"), accepted=Count("id", filter=Q(decision="accepted")),
        rejected=Count("id", filter=Q(decision__in=["rejected", "desk_rejected"]))).order_by("-total")[:15])
    return render(request, "tracker/reports.html", {
        "published": published, "years": years, "year": year,
        "counts": status_counts(papers),
        "total_submissions": subs.count(),
        "accept_rate": round(100 * subs.filter(decision="accepted").count() /
                             max(1, subs.filter(decision__in=["accepted", "rejected", "desk_rejected"]).count())),
        "avg_decision_days": round(sum((s.first_decision_at - s.submitted_at).days for s in decided) /
                                   len(decided)) if decided else None,
        "per_journal": per_journal,
        "per_year": _per_year(subs),
    })


def _per_year(subs):
    rows = {}
    for sub in subs:
        y = timezone.localtime(sub.submitted_at).year
        r = rows.setdefault(y, {"year": y, "submitted": 0, "accepted": 0, "rejected": 0})
        r["submitted"] += 1
        if sub.decision == "accepted":
            r["accepted"] += 1
        elif sub.decision in ("rejected", "desk_rejected"):
            r["rejected"] += 1
    out = sorted(rows.values(), key=lambda r: r["year"])[-6:]
    peak = max([r["submitted"] for r in out] + [1])
    for r in out:
        r["h_sub"] = round(100 * r["submitted"] / peak)
        r["h_acc"] = round(100 * r["accepted"] / peak)
        r["h_rej"] = round(100 * r["rejected"] / peak)
    return out


@login_required
def export_csv(request):
    papers = visible_papers(request.user).prefetch_related("authors", "submissions__journal")
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="research-tracker-export.csv"'
    resp.write("\ufeff")  # Excel-friendly UTF-8 (Arabic text displays correctly)
    w = csv.writer(resp)
    w.writerow(["Title", "Type", "Status", "Group", "Lead", "Authors", "Venue", "Publisher", "Quartile",
                "Manuscript ID", "Submitted", "First decision", "Accepted", "Published", "DOI"])
    for p in papers:
        s = p.current_submission
        w.writerow([p.title, p.get_type_display(), p.get_status_display(), p.group.name,
                    p.lead.display_name if p.lead else "", "; ".join(a.name for a in p.authors.all()),
                    s.journal.name if s else "", s.journal.publisher if s else "", s.journal.quartile if s else "",
                    s.manuscript_id if s else "",
                    timezone.localtime(s.submitted_at).strftime("%Y-%m-%d %H:%M") if s and s.submitted_at else "",
                    s.first_decision_at.date() if s and s.first_decision_at else "",
                    s.accepted_at.date() if s and s.accepted_at else "",
                    p.publication_date or "", p.doi])
    return resp


def _ics_escape(s):
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def calendar_feed(request, token):
    """Subscribe in Google/Outlook/Apple Calendar. Secret per-user URL, no login needed."""
    user = get_object_or_404(User, calendar_token=token, is_active=True)
    dls = (m.Deadline.objects.filter(paper__in=visible_papers(user), completed_at__isnull=True)
           .select_related("paper"))
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Research Tracker//EN", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{_ics_escape(settings.SITE_NAME)}"]
    stamp = timezone.now().strftime("%Y%m%dT%H%M%SZ")
    for d in dls:
        start = d.due_at.astimezone(timezone.get_fixed_timezone(0))
        lines += ["BEGIN:VEVENT", f"UID:deadline-{d.pk}@research-tracker", f"DTSTAMP:{stamp}",
                  f"DTSTART:{start:%Y%m%dT%H%M%SZ}", f"DTEND:{(start + timedelta(minutes=30)):%Y%m%dT%H%M%SZ}",
                  f"SUMMARY:{_ics_escape(d.title + ' — ' + d.paper.label)}",
                  f"DESCRIPTION:{_ics_escape(settings.SITE_URL + d.paper.get_absolute_url())}",
                  "BEGIN:VALARM", "TRIGGER:-P1D", "ACTION:DISPLAY", "DESCRIPTION:Reminder", "END:VALARM",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return HttpResponse("\r\n".join(lines), content_type="text/calendar; charset=utf-8")


# ---------------------------------------------------------------------------
# Scheduler hook (GitHub Actions / Render cron / any uptime pinger)
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
def cron(request, job):
    secret = settings.CRON_SECRET
    given = request.headers.get("X-Cron-Secret", "")
    if not secret or not hmac.compare_digest(secret, given):
        raise PermissionDenied
    if job == "reminders":
        return JsonResponse({"sent": run_reminders()})
    if job == "digest":
        return JsonResponse({"sent": run_digest()})
    raise Http404


def healthz(request):
    return JsonResponse({"ok": True})
