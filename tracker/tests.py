from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from tracker import models as m
from tracker.reminders import reminder_key, run_digest, run_reminders


class Base(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner@uni.edu", "pw-123456789x", full_name="Owner")
        self.member = User.objects.create_user("member@uni.edu", "pw-123456789x", full_name="Member")
        self.external = User.objects.create_user("ext@abroad.ac.uk", "pw-123456789x", full_name="External")
        self.stranger = User.objects.create_user("x@else.com", "pw-123456789x")
        self.group = m.ResearchGroup.objects.create(name="Lab", created_by=self.owner)
        m.GroupMembership.objects.create(group=self.group, user=self.owner, role="owner")
        m.GroupMembership.objects.create(group=self.group, user=self.member, role="member")
        m.GroupMembership.objects.create(group=self.group, user=self.external, role="external")
        self.journal = m.Journal.objects.create(name="Computers & Security", publisher="Elsevier")
        self.paper = m.Paper.objects.create(group=self.group, title="Paper A", lead=self.owner, created_by=self.owner)
        self.other_paper = m.Paper.objects.create(group=self.group, title="Paper B", created_by=self.owner)
        m.PaperAuthor.objects.create(paper=self.paper, user=self.external, order=2)


class PermissionTests(Base):
    def test_stranger_cannot_see_paper(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(reverse("paper_detail", args=[self.paper.pk])).status_code, 403)

    def test_external_sees_only_own_papers(self):
        self.client.force_login(self.external)
        self.assertEqual(self.client.get(reverse("paper_detail", args=[self.paper.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("paper_detail", args=[self.other_paper.pk])).status_code, 403)

    def test_member_cannot_manage_group(self):
        self.client.force_login(self.member)
        r = self.client.post(reverse("group_invite", args=[self.group.pk]), {"email": "a@b.com", "role": "member"})
        self.assertEqual(r.status_code, 403)

    def test_attachment_requires_access(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(reverse("attachment_download", args=[self.paper.pk, 1])).status_code, 403)

    def test_login_required(self):
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 302)


class SubmissionFlowTests(Base):
    def test_major_revision_creates_deadline_and_moves_status(self):
        self.client.force_login(self.owner)
        due = (timezone.localtime() + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M")
        sent = (timezone.localtime() - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M")
        r = self.client.post(reverse("submission_add", args=[self.paper.pk]), {
            "journal": self.journal.pk, "decision": "major", "submitted_at": sent, "revision_due_at": due})
        self.assertEqual(r.status_code, 302)
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.status, "major_revision")
        dl = self.paper.deadlines.get(kind="revision")
        self.assertIn(self.owner, dl.assignees.all())
        sub = self.paper.submissions.get()
        self.assertIsNotNone(sub.first_decision_at)
        # Revision submitted closes the deadline and bumps the round.
        r = self.client.post(reverse("submission_edit", args=[self.paper.pk, sub.pk]), {
            "journal": self.journal.pk, "decision": "revision_submitted", "submitted_at": sent, "revision_due_at": due})
        dl.refresh_from_db()
        sub.refresh_from_db()
        self.assertIsNotNone(dl.completed_at)
        self.assertEqual(sub.round, 2)
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.status, "resubmitted")

    def test_major_requires_due_date(self):
        self.client.force_login(self.owner)
        r = self.client.post(reverse("submission_add", args=[self.paper.pk]), {
            "journal": self.journal.pk, "decision": "major", "submitted_at": "2026-01-01T10:00"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(self.paper.submissions.exists())

    def test_bulk_comment_import(self):
        sub = m.Submission.objects.create(paper=self.paper, journal=self.journal, decision="major")
        self.client.force_login(self.owner)
        text = "1. Clarify the threat model.\n2. Add baselines.\n3. Release code."
        self.client.post(reverse("comment_bulk", args=[self.paper.pk, sub.pk]),
                         {"reviewer": "Reviewer 1", "round": 1, "text": text})
        self.assertEqual(sub.review_comments.count(), 3)


@override_settings(DEFAULT_REMINDER_DAYS="7,3,1,0")
class ReminderTests(Base):
    def make_deadline(self, days):
        d = m.Deadline.objects.create(paper=self.paper, title="Revision", kind="revision",
                                      due_at=timezone.localtime().replace(hour=23, minute=59) + timedelta(days=days),
                                      created_by=self.owner)
        d.assignees.add(self.member)
        return d

    def test_reminder_sent_once(self):
        self.make_deadline(3)
        self.assertEqual(run_reminders(), 1)
        self.assertEqual(run_reminders(), 0)  # idempotent
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("3", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["member@uni.edu"])

    def test_no_reminder_far_away(self):
        self.make_deadline(20)
        self.assertEqual(run_reminders(), 0)

    def test_catch_up_missed_day(self):
        d = self.make_deadline(6)  # 7-day reminder missed yesterday → still sent today
        self.assertEqual(reminder_key(d)[0], "d7")

    def test_overdue_escalates_to_owner(self):
        d = self.make_deadline(0)
        d.due_at = timezone.now() - timedelta(days=1)
        d.save()
        run_reminders()
        recipients = sorted(e.to[0] for e in mail.outbox)
        self.assertEqual(recipients, ["member@uni.edu", "owner@uni.edu"])

    def test_completed_deadline_is_silent(self):
        d = self.make_deadline(1)
        d.completed_at = timezone.now()
        d.save()
        self.assertEqual(run_reminders(), 0)

    def test_opt_out(self):
        self.member.email_reminders = False
        self.member.save()
        self.make_deadline(1)
        self.assertEqual(run_reminders(), 0)

    def test_digest(self):
        self.make_deadline(5)
        self.assertGreaterEqual(run_digest(), 1)
        self.assertEqual(run_digest(), 0)  # weekly guard

    @override_settings(CRON_SECRET="s3cret")
    def test_cron_endpoint(self):
        self.make_deadline(1)
        url = reverse("cron", args=["reminders"])
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertEqual(self.client.post(url, HTTP_X_CRON_SECRET="wrong").status_code, 403)
        r = self.client.post(url, HTTP_X_CRON_SECRET="s3cret")
        self.assertEqual(r.json()["sent"], 1)


class InvitationTests(Base):
    def test_invite_signup_and_link_author(self):
        m.PaperAuthor.objects.create(paper=self.paper, name="New Person", email="new@abroad.org", order=3)
        inv = m.Invitation.objects.create(group=self.group, email="new@abroad.org", role="external",
                                          invited_by=self.owner)
        r = self.client.post(reverse("invitation_accept", args=[inv.token]), {
            "email": "new@abroad.org", "full_name": "New Person", "affiliation": "Abroad Uni", "country": "UAE",
            "password1": "a-Strong-pass-2026", "password2": "a-Strong-pass-2026"})
        self.assertEqual(r.status_code, 302)
        user = User.objects.get(email="new@abroad.org")
        self.assertTrue(user.is_external)
        self.assertEqual(self.group.role_of(user), "external")
        self.assertTrue(self.paper.authors.filter(user=user).exists())
        inv.refresh_from_db()
        self.assertIsNotNone(inv.accepted_at)

    def test_author_self_update_public_link(self):
        a = m.PaperAuthor.objects.create(paper=self.paper, name="Ext Author", email="e@x.org", order=4)
        r = self.client.post(reverse("author_self_update", args=[a.update_token]), {
            "name": "Ext Author", "email": "e@x.org", "affiliation": "X Univ", "country": "Egypt",
            "approved_submission": "on"})
        self.assertEqual(r.status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.affiliation, "X Univ")
        self.assertEqual(a.missing_fields(), [])


class PageSmokeTests(Base):
    def test_main_pages_render(self):
        self.client.force_login(self.owner)
        for name in ["dashboard", "paper_list", "paper_board", "deadline_list", "group_list", "journal_list",
                     "reports", "profile", "paper_create"]:
            self.assertEqual(self.client.get(reverse(name), follow=True).status_code, 200, name)
        self.assertEqual(self.client.get(reverse("paper_detail", args=[self.paper.pk])).status_code, 200)

    def test_arabic_rtl(self):
        self.owner.preferred_language = "ar"
        self.owner.save()
        self.client.force_login(self.owner)
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, 'dir="rtl"')


class ButtonFlowTests(Base):
    """Every primary button/form in the UI must do what its label says."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)

    def test_create_paper(self):
        r = self.client.post(reverse("paper_create"), {"group": self.group.pk, "title": "New work", "type": "journal",
                                                       "status": "drafting", "priority": 2, "lead": self.owner.pk})
        p = m.Paper.objects.get(title="New work")
        self.assertRedirects(r, p.get_absolute_url())
        self.assertTrue(p.authors.filter(user=self.owner).exists())

    def test_add_submission_deadline_author_comment(self):
        pk = self.paper.pk
        now = timezone.localtime()
        r = self.client.post(reverse("submission_add", args=[pk]), {
            "journal": self.journal.pk, "manuscript_id": "COSE-1", "decision": "submitted", "round": 1,
            "submitted_at": now.strftime("%Y-%m-%dT%H:%M"), "submitted_by": self.owner.pk})
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        sub = self.paper.submissions.get()
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.status, "submitted")
        r = self.client.post(reverse("deadline_add", args=[pk]), {
            "kind": "other", "title": "Check portal", "due_at": (now + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M"),
            "assignees": [self.owner.pk], "reminder_days": "1"})
        self.assertEqual(r.status_code, 302)
        d = self.paper.deadlines.get(title="Check portal")
        self.client.post(reverse("deadline_toggle", args=[pk, d.pk]))
        d.refresh_from_db()
        self.assertIsNotNone(d.completed_at)
        r = self.client.post(reverse("author_add", args=[pk]), {"name": "Co Author", "email": "co@x.org",
                                                                "affiliation": "X", "country": "JO", "order": 3})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(self.paper.authors.filter(name="Co Author").exists())
        r = self.client.post(reverse("comment_add", args=[pk, sub.pk]), {"round": 1, "reviewer": "Reviewer 1",
                                                                        "number": "1", "comment": "Fix it",
                                                                        "state": "open"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(sub.review_comments.count(), 1)

    def test_status_select_and_board_route(self):
        r = self.client.post(reverse("paper_status", args=[self.paper.pk]), {"status": "under_review",
                                                                             "next": reverse("paper_list")})
        self.assertEqual(r.status_code, 302)
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.status, "under_review")
        r = self.client.get(reverse("paper_board") + "?type=journal")
        self.assertRedirects(r, reverse("paper_list") + "?type=journal&view=board", fetch_redirect_response=False)

    def test_status_groups_filter(self):
        self.paper.status = "submitted"
        self.paper.save()
        self.other_paper.status = "accepted"
        self.other_paper.save()
        r = self.client.get(reverse("paper_list") + "?view=table&status=in_review")
        self.assertEqual([p.pk for p in r.context["papers"]], [self.paper.pk])
        r = self.client.get(reverse("paper_list") + "?view=table&status=accepted_pub")
        self.assertEqual([p.pk for p in r.context["papers"]], [self.other_paper.pk])

    def test_group_journal_invite(self):
        r = self.client.post(reverse("journal_create"), {"name": "New J", "kind": "journal", "apc_currency": "USD"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(m.Journal.objects.filter(name="New J").exists())
        r = self.client.post(reverse("group_create"), {"name": "Lab 2"})
        self.assertEqual(r.status_code, 302)
        r = self.client.post(reverse("group_invite", args=[self.group.pk]), {"email": "new@uni.edu", "role": "member"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(m.Invitation.objects.filter(email="new@uni.edu").exists())
