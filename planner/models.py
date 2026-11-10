import uuid
from datetime import time

from django.conf import settings
from django.db import models

User = settings.AUTH_USER_MODEL
UNITS = [(key, key.title()) for key in ("days", "weeks", "months")]
MONEY = {"max_digits": 16, "decimal_places": 2}


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=120, blank=True)
    age = models.PositiveSmallIntegerField(null=True, blank=True)
    qualification = models.CharField(max_length=120, blank=True)
    specialization = models.CharField(max_length=120, blank=True)
    timezone = models.CharField(max_length=60, default="Europe/Budapest")
    currency = models.CharField(max_length=3, default="HUF")
    interval = models.PositiveSmallIntegerField(default=1)
    interval_unit = models.CharField(max_length=8, choices=UNITS, default="weeks")
    reminder_time = models.TimeField(default=time(8))


class Reason(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    label = models.CharField(max_length=120)
    active = models.BooleanField(default=True)


class Invite(models.Model):
    email = models.EmailField()
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    redeemed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.email} /signup/{self.token}/"


class Project(models.Model):
    MODES = [(key, key.title()) for key in ("standard", "hourly", "monthly")]
    STATES = [(key, key.replace("_", " ").title()) for key in
              ("active", "awaiting_payment", "closed")]
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=160)
    start = models.DateField()
    planned_end = models.DateField(null=True, blank=True)
    first_review = models.DateField()
    interval = models.PositiveSmallIntegerField()
    interval_unit = models.CharField(max_length=8, choices=UNITS)
    mode = models.CharField(max_length=10, choices=MODES, default="standard")
    currency = models.CharField(max_length=3, blank=True)
    status = models.CharField(max_length=20, choices=STATES, default="active")
    work_ended = models.DateField(null=True)
    closed_on = models.DateField(null=True)


class Cycle(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="cycles")
    sequence = models.PositiveIntegerField()
    start = models.DateField()
    end = models.DateField()
    closed_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "sequence"], name="unique_cycle_sequence"),
            models.UniqueConstraint(fields=["project"], condition=models.Q(closed_at__isnull=True),
                                    name="one_open_cycle"),
        ]


class TaskKind(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="kinds")
    name = models.CharField(max_length=120)
    task_fields = models.JSONField(default=list)
    entry_fields = models.JSONField(default=list)


class Task(models.Model):
    STATES = [(key, key.title()) for key in ("open", "completed", "partial", "discarded")]
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    kind = models.ForeignKey(TaskKind, on_delete=models.RESTRICT)
    name = models.CharField(max_length=160)
    status = models.CharField(max_length=12, choices=STATES, default="open")
    task_fields = models.JSONField(default=list)
    entry_fields = models.JSONField(default=list)
    values = models.JSONField(default=dict)
    closed_reason = models.CharField(max_length=120, blank=True)
    closed_reason_ref = models.ForeignKey(Reason, null=True, on_delete=models.PROTECT)
    closed_note = models.CharField(max_length=500, blank=True)


class Goal(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="goals")
    name = models.CharField(max_length=160)
    metric = models.CharField(max_length=100)
    kind = models.CharField(max_length=5, choices=[("count", "Count"), ("done", "Done")])


class Plan(models.Model):
    cycle = models.ForeignKey(Cycle, on_delete=models.CASCADE, related_name="plans")
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="plans")
    priority = models.CharField(max_length=8, default="normal")
    decision = models.CharField(max_length=12, blank=True)
    reason = models.CharField(max_length=120, blank=True)
    reason_ref = models.ForeignKey(Reason, null=True, on_delete=models.PROTECT)
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["cycle", "task"], name="unique_task_plan")]


class Target(models.Model):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="targets")
    goal = models.ForeignKey(Goal, on_delete=models.CASCADE, related_name="targets")
    quantity = models.PositiveIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["plan", "goal"], name="unique_plan_target")]


class DailyEntry(models.Model):
    target = models.ForeignKey(Target, on_delete=models.CASCADE, related_name="entries")
    day = models.DateField()
    items = models.JSONField(default=list)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["target", "day"], name="one_entry_per_day")]


class Correction(models.Model):
    entry = models.ForeignKey(DailyEntry, on_delete=models.CASCADE, related_name="corrections")
    previous = models.JSONField()
    revised = models.JSONField()
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)


class PayTerms(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="terms")
    effective_on = models.DateField()
    rate = models.DecimalField(**MONEY)
    tax_pct = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project", "effective_on"],
                                               name="unique_pay_terms_date")]


class Receivable(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="receivables")
    terms = models.ForeignKey(PayTerms, on_delete=models.RESTRICT)
    work_day = models.DateField()
    month = models.DateField(null=True)
    task = models.ForeignKey(Task, on_delete=models.RESTRICT, null=True)
    hours = models.DecimalField(max_digits=7, decimal_places=2, null=True)
    location = models.CharField(max_length=160, blank=True)
    gross = models.DecimalField(**MONEY)
    tax = models.DecimalField(**MONEY)
    net = models.DecimalField(**MONEY)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project", "month"],
                                               name="one_monthly_receivable")]


class Payment(models.Model):
    receivable = models.ForeignKey(Receivable, on_delete=models.CASCADE, related_name="payments")
    received_on = models.DateField()
    amount = models.DecimalField(**MONEY)


class Notification(models.Model):
    cycle = models.OneToOneField(Cycle, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True)
    emailed_at = models.DateTimeField(null=True)
