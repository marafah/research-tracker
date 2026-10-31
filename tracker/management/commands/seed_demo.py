"""Create realistic demo data so you can explore the platform in two minutes.

    python manage.py seed_demo            # creates demo@example.com / demo-pass-2026
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from tracker import models as m


class Command(BaseCommand):
    help = "Populate the database with demo groups, papers, submissions and deadlines."

    def add_arguments(self, parser):
        parser.add_argument("--email", default="demo@example.com")
        parser.add_argument("--password", default="demo-pass-2026")

    def handle(self, *args, **o):
        User = get_user_model()
        now = timezone.now()
        lead, created = User.objects.get_or_create(email=o["email"], defaults={
            "full_name": "Demo Researcher", "title": "Assistant Professor",
            "affiliation": "Department of Information Security, Example University", "country": "Jordan",
            "is_staff": True, "is_superuser": True})
        if created:
            lead.set_password(o["password"])
            lead.save()
        co1, _ = User.objects.get_or_create(email="sara.k@example.edu", defaults={
            "full_name": "Sara Khalil", "affiliation": "Example University", "country": "Jordan", "title": "PhD Student"})
        co2, _ = User.objects.get_or_create(email="j.smith@uk-example.ac.uk", defaults={
            "full_name": "James Smith", "affiliation": "Example University UK", "country": "United Kingdom",
            "is_external": True, "orcid": "0000-0002-1825-0097"})

        g, _ = m.ResearchGroup.objects.get_or_create(name="AI for Cyber Defense Lab", defaults={
            "institution": "Example University", "created_by": lead,
            "description": "Generative AI, intrusion detection and LLM security research."})
        for u, r in [(lead, "owner"), (co1, "member"), (co2, "external")]:
            m.GroupMembership.objects.get_or_create(group=g, user=u, defaults={"role": r})

        J = {}
        for name, pub, q, sc, wos in [
            ("Computers & Security", "Elsevier", "Q1", True, True),
            ("IEEE Access", "IEEE", "Q2", True, True),
            ("Expert Systems with Applications", "Elsevier", "Q1", True, True),
            ("Journal of Network and Computer Applications", "Elsevier", "Q1", True, True),
            ("ACM CCS", "ACM", "", True, False),
        ]:
            J[name], _ = m.Journal.objects.get_or_create(name=name, defaults={
                "publisher": pub, "quartile": q, "indexed_scopus": sc, "indexed_wos": wos,
                "kind": "conference" if "CCS" in name else "journal"})

        def paper(title, short, status, typ="journal", **kw):
            p, made = m.Paper.objects.get_or_create(group=g, title=title, defaults={
                "short_title": short, "status": status, "type": typ, "lead": lead, "created_by": lead, **kw})
            if made:
                for i, (u, corr) in enumerate([(lead, True), (co1, False), (co2, False)], 1):
                    m.PaperAuthor.objects.create(paper=p, user=u, order=i, is_corresponding=corr,
                                                 approved_submission=(i != 3))
            return p, made

        p1, made = paper("A Diffusion-Based Framework for Zero-Day Intrusion Detection in IoT Networks",
                         "Diffusion IDS for IoT", "major_revision", research_area="Intrusion detection",
                         keywords="diffusion models, IDS, IoT, zero-day", priority=3)
        if made:
            s = m.Submission.objects.create(paper=p1, journal=J["Computers & Security"], manuscript_id="COSE-D-26-01482",
                                            submitted_at=now - timedelta(days=96), decision="major",
                                            first_decision_at=now - timedelta(days=6), last_decision_at=now - timedelta(days=6),
                                            revision_due_at=now + timedelta(days=24), submitted_by=lead)
            m.SubmissionEvent.objects.create(submission=s, decision="submitted", happened_at=s.submitted_at, recorded_by=lead)
            m.SubmissionEvent.objects.create(submission=s, decision="under_review", happened_at=now - timedelta(days=80), recorded_by=lead)
            m.SubmissionEvent.objects.create(submission=s, decision="major", happened_at=now - timedelta(days=6), recorded_by=lead,
                                             note="Two reviewers. R2 asks for comparison with recent GAN baselines.")
            d = m.Deadline.objects.create(paper=p1, submission=s, kind="revision", title="Major revision — Computers & Security",
                                          due_at=now + timedelta(days=24), created_by=lead)
            d.assignees.add(lead, co1)
            for rv, n, txt, who, st in [
                ("Reviewer 1", "1", "The threat model is not clearly defined. Please specify attacker capabilities.", lead, "done"),
                ("Reviewer 1", "2", "Report false positive rates per attack class, not only macro F1.", co1, "in_progress"),
                ("Reviewer 2", "1", "Compare against recent GAN-based augmentation baselines (2024–2026).", co1, "open"),
                ("Reviewer 2", "2", "Release the code to support reproducibility.", co2, "open"),
            ]:
                m.ReviewComment.objects.create(submission=s, reviewer=rv, number=n, comment=txt, assigned_to=who, state=st,
                                               response="We added Section 3.1 defining the threat model." if st == "done" else "")

        p2, made = paper("LLM Agents for Automated Threat-Intelligence Report Generation", "LLM CTI reports",
                         "under_review", research_area="Threat intelligence")
        if made:
            m.Submission.objects.create(paper=p2, journal=J["Expert Systems with Applications"], manuscript_id="ESWA-D-26-11873",
                                        submitted_at=now - timedelta(days=41), decision="under_review", submitted_by=lead)

        p3, made = paper("Adversarial Robustness of Vision Transformers for Malware Image Classification",
                         "ViT malware robustness", "rejected", research_area="Adversarial ML")
        if made:
            m.Submission.objects.create(paper=p3, journal=J["IEEE Access"], manuscript_id="Access-2026-18822",
                                        submitted_at=now - timedelta(days=70), decision="desk_rejected",
                                        first_decision_at=now - timedelta(days=62), last_decision_at=now - timedelta(days=62))

        p4, made = paper("Federated Anomaly Detection for Smart-Grid SCADA Systems", "Federated SCADA AD", "accepted",
                         research_area="Anomaly detection")
        if made:
            m.Submission.objects.create(paper=p4, journal=J["Journal of Network and Computer Applications"],
                                        manuscript_id="JNCA-D-25-02210", submitted_at=now - timedelta(days=210),
                                        decision="accepted", first_decision_at=now - timedelta(days=150),
                                        accepted_at=now - timedelta(days=12), last_decision_at=now - timedelta(days=12))
            m.Deadline.objects.create(paper=p4, kind="proofs", title="Return proof corrections",
                                      due_at=now + timedelta(days=2), created_by=lead).assignees.add(lead)

        p5, made = paper("National Research Fund proposal: Generative AI for SOC automation", "SOC GenAI proposal",
                         "proposal", typ="proposal", target_submission_date=(now + timedelta(days=9)).date())
        if made:
            m.Deadline.objects.create(paper=p5, kind="proposal", title="Proposal submission deadline",
                                      due_at=now + timedelta(days=9), created_by=lead).assignees.add(lead, co1)
            m.Deadline.objects.create(paper=p5, kind="author_data", title="Collect CVs & signed forms from partners",
                                      due_at=now - timedelta(days=1), created_by=lead).assignees.add(co1)

        paper("Explainable GAN-based Data Augmentation for Imbalanced Network Traffic", "XAI-GAN augmentation", "drafting",
              research_area="Generative AI", target_submission_date=(now + timedelta(days=45)).date())
        paper("Prompt-injection detection benchmark for enterprise RAG systems", "RAG prompt-injection benchmark", "idea",
              typ="conference")
        p8, made = paper("Survey of Generative Models in Network Security", "GenAI security survey", "published", typ="review",
                         doi="10.1016/j.example.2026.104112", publication_date=(now - timedelta(days=60)).date(),
                         volume_issue_pages="Vol. 41, 104112")
        if made:
            m.Submission.objects.create(paper=p8, journal=J["Computers & Security"], submitted_at=now - timedelta(days=330),
                                        decision="accepted", accepted_at=now - timedelta(days=120),
                                        first_decision_at=now - timedelta(days=260))
        for p in m.Paper.objects.filter(group=g):
            if not p.activities.exists():
                m.Activity.objects.create(paper=p, group=g, user=lead, verb="created the paper")
        self.stdout.write(self.style.SUCCESS(f"Demo data ready. Log in as {o['email']} / {o['password']}"))
