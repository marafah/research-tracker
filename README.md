# Research Tracker — منصة متابعة النشر البحثي

**Track every paper from idea to publication: submissions, revisions, deadlines, co-authors and email reminders, in Arabic and English.**

Research Tracker is an open-source web platform for academics who work with several research groups, inside and outside their university. It answers the questions that usually live in scattered emails and spreadsheets:

- Where did we send this paper, when exactly, and what is the manuscript ID?
- It was rejected. Where did it go next, and what did the reviewers say?
- The major revision is due in 9 days. Who is handling Reviewer 2's comments?
- Which co-author still hasn't sent their affiliation and ORCID?
- What did we publish this year, for the annual report or the promotion file?

---

## Features

| Area | What you get |
|---|---|
| **Papers & proposals** | Journal articles, conference papers, chapters, reviews and grant proposals. 16 pipeline stages, from *Idea* to *Published*, plus *Rejected*, *Withdrawn* and *On hold*. Priority, research area, target submission date, links to Overleaf and the code repo, DOI. |
| **Submissions** | One paper, many attempts. Each submission records the journal, manuscript ID, submission **date and time**, the person who submitted, the handling editor and the portal link. It also keeps an **immutable timeline** of every decision. After a rejection, *Submit to another journal* starts a new attempt and keeps the history. |
| **Revisions** | When you set a submission to *Major* or *Minor revision* with a due date, the platform automatically creates a deadline with reminders. Recording the revision as submitted closes that deadline and starts the next round. |
| **Reviewer comments** | Paste a whole review and it is split into individual points. Assign each point to a co-author, who gets an email. Track its state (open, in progress, addressed, rebutted), write the response, and print a **response-to-reviewers letter** in one click. |
| **Deadlines & reminders** | Every deadline has a type (revision, proposal, proofs, camera-ready, APC, author data…), a due date and time, and assignees. Reminders go out **14, 7, 3, 1 and 0 days before** by default (configurable per deadline). Overdue deadlines get a daily reminder and are escalated to the group owners. There is also a **weekly digest**. No duplicate emails, ever. |
| **Co-authors** | Co-authors can be platform members or free-text external people. A secure **self-update link** (no account needed; you can share it by email or WhatsApp) lets each co-author fill in their own affiliation, country, ORCID, CRediT contribution, COI form and approval. The dashboard shows whose data is missing. |
| **Groups & roles** | Several research groups per user. Roles: Owner, Admin, Member and **External collaborator** (sees only the papers they author). Invite people by email. Pending author rows are linked automatically when the invitee signs up. |
| **Journals** | A shared venue catalogue (publisher, ISSN, quartile, Scopus/WoS, APC, open access, *questionable-venue* flag) with your own statistics per venue: acceptance count and average time to first decision. |
| **Views** | Dashboard, list with filters, **Kanban board**, deadlines page, and reports (acceptance rate, time to decision, per-venue table, printable list of publications by year). |
| **Integrations** | Excel-friendly CSV export, and a private **calendar feed (.ics)** for Google, Outlook or Apple Calendar. |
| **Bilingual** | Full **Arabic (RTL)** and English interface. Each user picks their language, and emails follow it. |
| **Security** | Row-level access control on every query. Files are served only after a permission check. Secrets come from the environment. Hardened cookies and HSTS in production, password validators, CSRF protection, an audit trail on every paper, and no third-party CDNs (all assets are self-hosted). |

## Quick start

### Windows: one double-click
- **`run-local.bat`**: installs everything in a virtual environment, loads demo data and opens http://127.0.0.1:8000 (needs Python 3.11+).
- **`publish-to-github.bat`**: creates the `research-tracker` repository on your GitHub account and pushes the code (needs Git + GitHub CLI).

### Option 1: GitHub Codespaces (zero install)
Click **Code → Codespaces → Create codespace**. The app installs, loads demo data and opens in your browser.
Log in with `demo@example.com` / `demo-pass-2026`.

### Option 2: Local (Python 3.11+)
```bash
git clone https://github.com/<your-username>/research-tracker.git
cd research-tracker
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export DEBUG=1                                          # Windows PowerShell: $env:DEBUG=1
python manage.py migrate
python manage.py seed_demo          # optional demo data
python manage.py createsuperuser    # your own admin account
python manage.py runserver
```
Open http://127.0.0.1:8000. In development mode, emails are printed to the console.

### Option 3: Docker (server / university VM)
```bash
cp .env.example .env      # edit: SECRET_KEY, SITE_URL, ALLOWED_HOSTS, SMTP settings
docker compose up -d
docker compose exec web python manage.py createsuperuser
```
This starts PostgreSQL, the web app and a **scheduler** container that sends reminders every hour.

### Option 4: Render.com (managed hosting)
Fork the repo, then in Render choose **New → Blueprint** and select it. `render.yaml` creates the web service and the PostgreSQL database. Set `SITE_URL`, `CSRF_TRUSTED_ORIGINS` and the email variables, then enable the GitHub Actions reminder workflow (below).

> **Note:** GitHub hosts the code, CI and the reminder scheduler. GitHub Pages cannot run a backend with logins, so the app itself runs on a server: Docker, Render, Railway, a university VM or similar.

## Email reminders

1. Configure SMTP in `.env`. Any provider works: university Exchange or Office 365, a Gmail app password, Amazon SES, Brevo and so on.
2. Pick **one** way to trigger the reminders:
   - **Docker Compose:** already handled by the `scheduler` service.
   - **GitHub Actions:** set the repository variable `SITE_URL` and the secret `CRON_SECRET` (the same value as on the server). `.github/workflows/reminders.yml` then calls the site every hour, plus a weekly digest on Sunday.
   - **cron:** `python manage.py send_reminders` (hourly) and `python manage.py send_digest` (weekly).

The commands are idempotent, so running them more often never sends duplicates.

## Configuration

All settings are environment variables. See [`.env.example`](.env.example). The most important ones:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Long random string (required in production) |
| `DATABASE_URL` | PostgreSQL URL (SQLite is used if empty) |
| `SITE_URL` | Public URL, used in email links |
| `ALLOW_SIGNUP` | `0` = invitation-only platform |
| `DEFAULT_REMINDER_DAYS` | e.g. `14,7,3,1,0` |
| `CRON_SECRET` | Protects `/cron/reminders/` and `/cron/digest/` |
| `TIME_ZONE` | Default `Asia/Amman` |

## Project structure
```
config/          settings, urls, wsgi
accounts/        email-login user model, profile, sign-up, language switch
tracker/
  models.py      ResearchGroup, Paper, PaperAuthor, Submission, Deadline, ReviewComment, Journal, …
  permissions.py row-level access control (every view goes through it)
  services.py    business rules: decision → status, auto deadlines, emails
  reminders.py   reminder engine and weekly digest
  views.py, forms.py, urls.py, tests.py
templates/       Bootstrap 5 UI (LTR + RTL) and HTML/text emails
locale/          Arabic translation (ar.json → compiled .po/.mo)
scripts/         i18n_extract.py: extract and compile translations without GNU gettext
```

## Development

```bash
DEBUG=1 python manage.py test                    # test suite
python scripts/i18n_extract.py extract           # list translatable strings → locale/messages.json
python scripts/i18n_extract.py compile           # locale/ar.json → .po/.mo (needs: pip install Babel)
```
To change Arabic wording, edit `locale/ar.json` and recompile.

## Roadmap
- [ ] Forward journal emails to the platform; an AI parser extracts the decision and due date and updates the submission
- [ ] AI journal recommender from the abstract, and scope checks
- [ ] ORCID OAuth sign-in and author import
- [ ] Two-factor authentication (TOTP)
- [ ] WhatsApp / Telegram reminder channel
- [ ] Drag-and-drop Kanban
- [ ] REST API

Contributions are welcome. Please open an issue first for larger changes.

## License
[GNU AGPL-3.0](LICENSE). You may use, modify and self-host the platform freely. If you run a modified version as a public service, you must publish your changes.

## Citation
If this platform helps your research group, please cite it (a Zenodo DOI will be added on the first release).

---

<div dir="rtl">

## بالعربية

**منصة مفتوحة المصدر لمتابعة الأبحاث من الفكرة حتى النشر.** تتابع المنصة لكل بحث: إلى أين أُرسل، والمجلة والناشر، وتاريخ الإرسال ووقته، ورقم المخطوطة، وقرارات التحكيم، والتعديلات ومواعيد تسليمها، وتاريخ القبول والنشر. وتشمل أيضاً:

- **مجموعات بحثية** من داخل الجامعة وخارجها، مع صلاحيات للمالك والمشرف والعضو والباحث الخارجي.
- **رابط آمن لكل مؤلف مشارك** يكمل به بياناته بنفسه (الانتساب، ORCID، المساهمة، الموافقة) دون الحاجة إلى حساب، ويمكن إرساله عبر واتساب.
- **تذكيرات تلقائية بالبريد** قبل كل موعد نهائي بـ 14 و7 و3 أيام وبيوم واحد وفي يوم الموعد، وتنبيه يومي عند التأخير يصل إلى مالك المجموعة، وملخص أسبوعي.
- **ملاحظات المحكّمين:** الصق التحكيم كاملاً فيُقسَّم إلى نقاط، تُسند كل نقطة إلى أحد المؤلفين، ثم يُطبع خطاب الرد بضغطة واحدة.
- **لوحة Kanban**، وتقارير جاهزة للتقرير السنوي وملف الترقية، وتصدير CSV، ومزامنة مع التقويم.
- **واجهة عربية كاملة (RTL) وإنجليزية**، ويختار كل مستخدم لغته.

**التشغيل السريع:** من GitHub اختر Code ثم Codespaces، أو استخدم Docker عبر `docker compose up -d`. تفاصيل الإعداد في الأقسام الإنجليزية أعلاه.

</div>
