# Running Research Tracker on any server — تشغيل المنصة على أي خادم

Everything needed to run the platform is in this folder: the Django code, templates, styles, translations,
tests, a `Dockerfile`, `docker-compose.yml`, `render.yaml` and `run-local.bat`.
Your own data (accounts, papers, submissions, deadlines) is **not** in the code. Export it as a JSON file
and keep it private (see "Your data" below).

كل ما يلزم لتشغيل المنصة موجود في هذا المجلد. بياناتك (الحسابات والأبحاث والمواعيد) ليست جزءاً من الكود،
وتُحفظ في ملف JSON خاص خارج GitHub (انظر «بياناتك» أدناه).

## Requirements — المتطلبات

- Python 3.11+ (tested on 3.12 and 3.14) **or** Docker.
- A database: SQLite works out of the box. PostgreSQL is recommended for a shared server (`DATABASE_URL`).

## 1. On your own computer (Windows) — على جهازك

Double-click `run-local.bat`. It creates `.venv`, installs the requirements, migrates, loads demo data and opens
http://127.0.0.1:8000.

To use **your real data** instead of the demo, run these in the project folder:

```bat
.venv\Scripts\activate
set DEBUG=1
python manage.py migrate
python manage.py loaddata private-data\rt-data-YYYY-MM-DD.json
python manage.py runserver
```

## 2. On a Linux server (no Docker) — على خادم لينكس

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY='a-long-random-string'   # required when DEBUG is off
export DEBUG=0
export ALLOWED_HOSTS='research.example.edu'
export CSRF_TRUSTED_ORIGINS='https://research.example.edu'
export SITE_URL='https://research.example.edu'
export DATABASE_URL='postgres://user:pass@localhost:5432/research_tracker'   # optional; SQLite if empty
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py loaddata private-data/rt-data-YYYY-MM-DD.json   # or: python manage.py createsuperuser
gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3
```

Put Nginx (or the university's reverse proxy) in front of port 8000 with HTTPS.

## 3. With Docker — باستخدام Docker

```bash
cp .env.example .env                  # then edit SECRET_KEY, ALLOWED_HOSTS, SITE_URL, e-mail
docker compose up -d --build          # web + PostgreSQL + hourly reminders (docker-compose.yml)
docker compose cp private-data/rt-data-YYYY-MM-DD.json web:/tmp/rt-data.json
docker compose exec web python manage.py loaddata /tmp/rt-data.json
```

## 4. On Render — على Render

New → Blueprint → choose this repository. `render.yaml` creates the web service, a PostgreSQL database and a disk
for uploads. Set `SITE_URL`, `CSRF_TRUSTED_ORIGINS` and the e-mail settings in the dashboard, then load your data
from the Render shell with `python manage.py loaddata ...`.

## Settings (environment variables) — الإعدادات

| Variable | Meaning |
|---|---|
| `SECRET_KEY` | Required in production. Long random string. |
| `DEBUG` | `1` for local development only, `0` on a server. |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SITE_URL` | The address of your site. |
| `DATABASE_URL` | PostgreSQL connection string; SQLite (`db.sqlite3`) if empty. |
| `TIME_ZONE` | Default `Asia/Amman`. |
| `LANGUAGE_CODE` | Default interface language (`ar` or `en`). |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | Outgoing mail for reminders. |
| `CRON_SECRET` | Protects the reminder/digest web hooks. |
| `MEDIA_ROOT`, `MAX_ATTACHMENT_MB` | Where uploaded files are stored, and their size limit. |
| `INSTITUTION_NAME`, `INSTITUTION_NAME_AR`, `SITE_NAME` | Branding. |

## Reminders — التذكيرات

Schedule these daily (cron, Task Scheduler or the host's scheduler):

```bash
python manage.py send_reminders
python manage.py send_digest      # weekly digest
```

## Your data — بياناتك

Export (on the running server or Codespace):

```bash
python manage.py dumpdata --natural-foreign --natural-primary \
  -e contenttypes -e auth.permission -e sessions -e admin.logentry \
  --indent 1 -o private-data/rt-data-$(date +%F).json
```

Import on a new server after `migrate`:

```bash
python manage.py loaddata private-data/rt-data-YYYY-MM-DD.json
```

The file contains accounts (with hashed passwords) and all research records. Keep it out of GitHub:
`private-data/` is listed in `.gitignore`. Uploaded attachments live in `media/`; copy that folder too if you use attachments.

## Checks — الفحص

```bash
python manage.py check
python manage.py test tracker
```
