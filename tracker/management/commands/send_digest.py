from django.core.management.base import BaseCommand

from tracker.reminders import run_digest


class Command(BaseCommand):
    help = "Email the weekly digest to every user who opted in."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Ignore the once-a-week guard")

    def handle(self, *args, **opts):
        run_digest(force=opts["force"], stdout=self.stdout)
