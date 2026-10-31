# Security policy

Research Tracker stores unpublished research, so please report vulnerabilities privately
(GitHub → Security → *Report a vulnerability*) rather than in public issues.

Deployment checklist:
- `DEBUG=0`, long random `SECRET_KEY` and `CRON_SECRET`, HTTPS only.
- Set `ALLOW_SIGNUP=0` if the instance is for invited researchers only.
- Back up the PostgreSQL database and the `media/` volume (uploaded manuscripts).
- Keep dependencies updated (`pip install -U -r requirements.txt`) — Dependabot is recommended.
