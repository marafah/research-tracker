"""Import real submission records from a spreadsheet (or its JSON export).

Expected workbook layout (as exported from the author's tracking sheet):

* "Awaiting Approval" sheet  – book-chapter proposals:
      # | Chapter Title | Book | Status | Submission Date | Link
* "Journal Submissions" sheet – journal manuscripts:
      # | Journal | Publisher / System | Manuscript Number | Title |
        Initial Date Submitted | Status Date | Current Status | Link
* "Important Dates" sheet     – per-book milestone tables:
      "Proposals page:" <url>, then "Book: <name>" followed by Date | Milestone rows.

Usage
-----
    python manage.py import_records records.xlsx --owner you@uni.edu --replace-demo
    python manage.py import_records records.xlsx --dump-json records.json   # convert only
    python manage.py import_records records.json --owner you@uni.edu        # import the JSON

The import is idempotent: running it again updates the same records instead of duplicating them.
"""
import json
from datetime import date, datetime, time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from tracker import models as m

MISSING = {"", "not shown", "n/a", "na", "-", "—", "none"}

# Portal wording -> submission decision (paper status follows Submission.DECISION_TO_STATUS)
STATUS_MAP = [
    ("required reviews completed", "under_review"),
    ("under review", "under_review"),
    ("reviewers assigned", "under_review"),
    ("with editor", "with_editor"),
    ("editor assigned", "with_editor"),
    ("awaiting", "submitted"),
    ("submitted to journal", "submitted"),
    ("submitted", "submitted"),
    ("major revision", "major"),
    ("minor revision", "minor"),
    ("revise", "major"),
    ("accept", "accepted"),
    ("reject", "rejected"),
    ("withdrawn", "withdrawn"),
]

MILESTONE_KIND = {
    "proposal submission deadline": "proposal",
    "full chapter submission": "submission",
    "final chapter submission": "camera_ready",
}


def _clean(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        return None if v.lower() in MISSING else v
    return v


def _iso(v):
    v = _clean(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _dt(v, end_of_day=False):
    """ISO string / date / datetime -> aware datetime in the site time zone."""
    v = _clean(v)
    if v is None:
        return None
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v)
        except ValueError:
            for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
                try:
                    v = datetime.strptime(v, fmt)
                    break
                except ValueError:
                    continue
            else:
                raise CommandError(f"Unrecognised date: {v!r}")
    if isinstance(v, date) and not isinstance(v, datetime):
        v = datetime.combine(v, time.min)
    if end_of_day and v.time() == time.min:
        v = datetime.combine(v.date(), time(23, 59))
    return timezone.make_aware(v) if timezone.is_naive(v) else v


def _cell_link(cell):
    if cell.hyperlink and cell.hyperlink.target:
        return cell.hyperlink.target
    return _clean(cell.value) if isinstance(cell.value, str) and cell.value.startswith("http") else None


def parse_workbook(path):
    try:
        import openpyxl
    except ImportError as e:  # pragma: no cover
        raise CommandError("openpyxl is required to read .xlsx files (pip install openpyxl)") from e
    wb = openpyxl.load_workbook(path)
    data = {"chapters": [], "journals": [], "books": {}, "proposals_page": None}

    def rows_with_header(ws):
        header = [str(c.value).strip().lower() if c.value else "" for c in ws[1]]
        for row in ws.iter_rows(min_row=2):
            first = row[0].value
            if not isinstance(first, (int, float)):  # skip totals / footer lines
                continue
            yield {header[i]: c for i, c in enumerate(row) if i < len(header)}

    names = {ws.title.lower(): ws for ws in wb.worksheets}
    ch = next((ws for t, ws in names.items() if "approval" in t or "chapter" in t), None)
    if ch is not None:
        for r in rows_with_header(ch):
            data["chapters"].append({
                "title": _clean(r["chapter title"].value), "book": _clean(r["book"].value),
                "status": _clean(r["status"].value), "submitted_at": _iso(r["submission date"].value),
                "link": _cell_link(r["link"])})
    js = next((ws for t, ws in names.items() if "journal" in t), None)
    if js is not None:
        for r in rows_with_header(js):
            data["journals"].append({
                "journal": _clean(r["journal"].value), "publisher_system": _clean(r["publisher / system"].value),
                "manuscript_id": _clean(r["manuscript number"].value), "title": _clean(r["title"].value),
                "submitted_at": _iso(r["initial date submitted"].value), "status_date": _iso(r["status date"].value),
                "status": _clean(r["current status"].value), "link": _cell_link(r["link"])})
    imp = next((ws for t, ws in names.items() if "date" in t), None)
    if imp is not None:
        book = None
        for row in imp.iter_rows():
            a = row[0].value
            b = row[1] if len(row) > 1 else None
            if isinstance(a, str) and a.strip().lower().startswith("proposals page") and b is not None:
                data["proposals_page"] = _cell_link(b)
            elif isinstance(a, str) and a.strip().lower().startswith("book:"):
                book = a.split(":", 1)[1].strip()
                data["books"][book] = []
            elif book and isinstance(a, (datetime, date)) and b is not None and b.value:
                data["books"][book].append({"date": _iso(a), "milestone": str(b.value).strip()})
    return data


def _decision(status):
    s = (status or "").lower()
    for key, dec in STATUS_MAP:
        if key in s:
            return dec
    return "submitted"


def _split_publisher(text):
    """'Elsevier (Editorial Manager)' -> ('Elsevier', 'Editorial Manager')."""
    if not text:
        return "", ""
    if "(" in text and text.endswith(")"):
        pub, system = text[:-1].split("(", 1)
        return pub.strip(), system.strip()
    return text.strip(), ""


class Command(BaseCommand):
    help = "Import real chapter proposals, journal submissions and book milestones from an .xlsx/.json file."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--owner", help="E-mail of the account that owns the records (must exist).")
        parser.add_argument("--owner-name", default="")
        parser.add_argument("--owner-title", default="")
        parser.add_argument("--owner-affiliation", default="")
        parser.add_argument("--owner-country", default="")
        parser.add_argument("--group", default="", help="Research group name (created if missing).")
        parser.add_argument("--institution", default="")
        parser.add_argument("--replace-demo", action="store_true",
                            help="Delete ALL existing papers, venues and demo users first (the seed_demo data).")
        parser.add_argument("--dump-json", metavar="OUT", help="Only convert the workbook to JSON and exit.")

    def handle(self, *args, **o):
        path = o["path"]
        data = json.load(open(path, encoding="utf-8")) if path.endswith(".json") else parse_workbook(path)
        if o["dump_json"]:
            with open(o["dump_json"], "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
            self.stdout.write(self.style.SUCCESS(
                f"Wrote {o['dump_json']}: {len(data['chapters'])} chapters, {len(data['journals'])} journal "
                f"submissions, {sum(len(v) for v in data['books'].values())} milestones."))
            return
        if not o["owner"]:
            raise CommandError("--owner is required")
        User = get_user_model()
        try:
            owner = User.objects.get(email__iexact=o["owner"])
        except User.DoesNotExist as e:
            raise CommandError(f"No account with e-mail {o['owner']}") from e
        with transaction.atomic():
            self._import(data, owner, o)

    # ------------------------------------------------------------------ import
    def _import(self, data, owner, o):
        if o["replace_demo"]:
            n_p = m.Paper.objects.count()
            m.Activity.objects.all().delete()
            m.Paper.objects.all().delete()          # cascades: authors, submissions, events, deadlines, files
            m.Journal.objects.all().delete()
            demo_users = get_user_model().objects.filter(email__iendswith="example.edu") | \
                get_user_model().objects.filter(email__iendswith="example.ac.uk")
            demo_users.exclude(pk=owner.pk).delete()
            self.stdout.write(f"Removed demo data ({n_p} papers, all venues, demo co-authors).")

        changed = []
        for field in ("owner_name", "owner_title", "owner_affiliation", "owner_country"):
            if o[field]:
                attr = {"owner_name": "full_name", "owner_title": "title",
                        "owner_affiliation": "affiliation", "owner_country": "country"}[field]
                setattr(owner, attr, o[field])
                changed.append(attr)
        if changed:
            owner.save(update_fields=changed)

        group = None
        if o["group"]:
            group = m.ResearchGroup.objects.filter(memberships__user=owner).order_by("pk").first()
            if group is None:
                group = m.ResearchGroup.objects.create(name=o["group"], created_by=owner)
            group.name = o["group"]
            if o["institution"]:
                group.institution = o["institution"]
            group.description = group.description if not o["replace_demo"] else \
                "Book chapters and journal manuscripts under submission."
            group.save()
        else:
            group = m.ResearchGroup.objects.filter(memberships__user=owner).order_by("pk").first()
            if group is None:
                raise CommandError("Owner has no research group; pass --group")
        m.GroupMembership.objects.get_or_create(group=group, user=owner, defaults={"role": "owner"})

        def venue(name, kind, publisher, link, notes=""):
            j, _ = m.Journal.objects.get_or_create(name=name, defaults={"kind": kind, "created_by": owner})
            j.kind = kind
            j.publisher = publisher or j.publisher
            if link:
                j.submission_portal = link
                j.website = j.website or link
            if notes:
                j.notes = notes
            j.save()
            return j

        def paper(title, typ):
            p, made = m.Paper.objects.get_or_create(group=group, title=title, defaults={
                "type": typ, "lead": owner, "created_by": owner, "status": "submitted"})
            p.type = typ
            p.lead = p.lead or owner
            author, _ = m.PaperAuthor.objects.get_or_create(paper=p, user=owner,
                                                            defaults={"order": 1, "is_corresponding": True})
            if not author.approved_submission:  # already submitted, so the author approved it
                author.approved_submission = True
                author.save()
            return p, made

        def submission(p, j, submitted_at, decision, link, manuscript_id, notes):
            s = p.submissions.filter(journal=j).order_by("pk").first() or m.Submission(paper=p, journal=j)
            s.submitted_at = submitted_at
            s.submitted_by = owner
            s.decision = decision
            s.portal_url = link or ""
            s.manuscript_id = manuscript_id or ""
            s.notes = notes
            s.save()
            p.status = m.Submission.DECISION_TO_STATUS[decision]
            p.save()
            return s

        def event(s, decision, when, note):
            if when is None:
                return
            m.SubmissionEvent.objects.update_or_create(
                submission=s, decision=decision, happened_at=when,
                defaults={"note": note, "recorded_by": owner})

        stats = {"chapters": 0, "journals": 0, "deadlines": 0, "new": 0}

        # ---- Book chapters (proposals awaiting approval)
        books = {}
        for row in data.get("chapters", []):
            if not row.get("title") or not row.get("book"):
                continue
            milestones = data.get("books", {}).get(row["book"], [])
            notes = "IGI Global book. Important dates:\n" + "\n".join(
                f"{_dt(x['date']).strftime('%d/%m/%Y')} — {x['milestone']}" for x in milestones) if milestones else ""
            link = row.get("link") or data.get("proposals_page")
            if row["book"] not in books:
                books[row["book"]] = venue(row["book"], "book", "IGI Global", link, notes)
            j = books[row["book"]]
            p, made = paper(row["title"], "chapter")
            stats["new"] += made
            when = _dt(row.get("submitted_at"))
            dec = _decision(row.get("status"))
            s = submission(p, j, when, dec, link, "",
                           f"Chapter proposal — portal status: {row.get('status') or '—'}\n"
                           f"Proposals page: {link}")
            event(s, "submitted", when, f"Chapter proposal submitted ({row.get('status') or 'submitted'})")
            # Book milestones become per-chapter deadlines
            for x in milestones:
                due = _dt(x["date"], end_of_day=True)
                kind = MILESTONE_KIND.get(x["milestone"].lower(), "other")
                d, created = m.Deadline.objects.update_or_create(
                    paper=p, title=x["milestone"], defaults={
                        "submission": s, "kind": kind, "due_at": due, "created_by": owner,
                        "notes": f"{row['book']} (IGI Global)"})
                if created:
                    d.assignees.add(owner)
                # The proposal deadline is already met for a submitted proposal.
                if kind == "proposal" and when and not d.completed_at:
                    d.completed_at, d.completed_by = when, owner
                    d.save(update_fields=["completed_at", "completed_by"])
                stats["deadlines"] += 1
            if made:
                m.Activity.objects.create(paper=p, group=group, user=owner, verb="imported the chapter proposal")
            stats["chapters"] += 1

        # ---- Journal submissions
        for row in data.get("journals", []):
            if not row.get("title") or not row.get("journal"):
                continue
            publisher, system = _split_publisher(row.get("publisher_system"))
            j = venue(row["journal"], "journal", publisher, row.get("link"),
                      f"Submission system: {system}" if system else "")
            p, made = paper(row["title"], "journal")
            stats["new"] += made
            dec = _decision(row.get("status"))
            sub_at = _dt(row.get("submitted_at"))
            status_at = _dt(row.get("status_date"))
            notes = [f"Portal status: {row.get('status') or '—'}"]
            notes.append(f"Status date: {status_at.strftime('%d/%m/%Y') if status_at else 'not shown in portal'}")
            if not sub_at:
                notes.append("Initial submission date: not shown in portal")
            if system:
                notes.append(f"Submission system: {system}")
            s = submission(p, j, sub_at, dec, row.get("link"), row.get("manuscript_id"), "\n".join(notes))
            event(s, "submitted", sub_at, "Initial submission")
            if dec != "submitted":
                event(s, dec, status_at, row.get("status") or "")
            elif status_at and status_at != sub_at:
                event(s, "submitted", status_at, row.get("status") or "")
            if made:
                m.Activity.objects.create(paper=p, group=group, user=owner, verb="imported the journal submission")
            stats["journals"] += 1

        self.stdout.write(self.style.SUCCESS(
            f"Imported {stats['chapters']} chapter proposals and {stats['journals']} journal submissions "
            f"({stats['new']} new records), {stats['deadlines']} milestone deadlines, {len(books)} books."))
