from django.core.management.base import BaseCommand

from tracker.reminders import run_reminders


class Command(BaseCommand):
    help = "Email deadline reminders (safe to run hourly; duplicates are prevented)."

    def handle(self, *args, **opts):
        run_reminders(stdout=self.stdout)
