from zoneinfo import ZoneInfo

from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from planner.models import Notification, Project
from planner.rules import profile_for
from planner.services import generate_months


class Command(BaseCommand):
    help = "Generate monthly receivables and deliver cycle review reminders."

    def handle(self, *args, **options):
        failures = 0
        ids = Project.objects.filter(status="active").values_list("pk", flat=True)
        for pk in list(ids):
            try:
                self.process(pk)
            except Exception as error:
                self.stderr.write(f"Project {pk}: {type(error).__name__}")
                failures += 1
        if failures:
            self.stderr.write(f"{failures} project(s) will be retried on the next run.")

    def process(self, pk):
        with transaction.atomic():
            project = Project.objects.select_for_update().select_related("owner").get(pk=pk)
            if project.status != "active":
                return
            profile = profile_for(project.owner)
            now = timezone.localtime(timezone.now(), ZoneInfo(profile.timezone))
            if project.mode == "monthly":
                generate_months(project, now.date())
            cycle = project.cycles.filter(closed_at=None, end__lte=now.date()).first()
            if cycle is None or (cycle.end == now.date() and now.time() < profile.reminder_time):
                return
            reminder, _ = Notification.objects.get_or_create(cycle=cycle)
        if not reminder.emailed_at and project.owner.email:
            with transaction.atomic():
                reminder = Notification.objects.select_for_update().get(pk=reminder.pk)
                if reminder.emailed_at:
                    return
                sent = send_mail("Project cycle ready for review",
                                 f"{project.name} · cycle {cycle.sequence} · {cycle.end}",
                                 None, [project.owner.email])
                if sent:
                    reminder.emailed_at = timezone.now()
                    reminder.save(update_fields=["emailed_at"])
