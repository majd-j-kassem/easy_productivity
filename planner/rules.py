from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import Cycle, PayTerms, Profile, Reason, Receivable


DEFAULT_REASONS = ("Priority changed", "Estimate was inaccurate", "External blocker", "Scope changed", "Other")


@transaction.atomic
def profile_for(user):
    profile, created = Profile.objects.get_or_create(user=user)
    if created:
        Reason.objects.bulk_create([Reason(user=user, label=label) for label in DEFAULT_REASONS])
    return profile


def today_for(user):
    return timezone.localdate(timezone=ZoneInfo(profile_for(user).timezone))


def add_months(day, count):
    year, month = divmod(day.year * 12 + day.month - 1 + count, 12)
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))


def review_date(project, sequence):
    offset = (sequence - 1) * project.interval
    if project.interval_unit == "months":
        return add_months(project.first_review, offset)
    return project.first_review + timedelta(days=offset * (7 if project.interval_unit == "weeks" else 1))


def default_first_review(start, interval, unit):
    if unit == "months":
        return add_months(start, interval) - timedelta(days=1)
    return start + timedelta(days=interval * (7 if unit == "weeks" else 1) - 1)


def next_cycle(previous):
    sequence = previous.sequence + 1
    return Cycle.objects.create(project=previous.project, sequence=sequence,
                                start=previous.end + timedelta(days=1),
                                end=review_date(previous.project, sequence))


def count_items(target):
    total = 0
    for entry in target.entries.all():
        total += len(entry.items)
    return min(total, 1) if target.goal.kind == "done" else total


def goals_met(task):
    goals = list(task.goals.all())
    if not goals:
        return False
    for goal in goals:
        targets = list(goal.targets.order_by("plan__cycle__sequence"))
        if not targets or count_items(targets[-1]) < targets[-1].quantity:
            return False
    return True


def carry_quantity(target):
    targets = list(target.goal.targets.filter(
        plan__cycle__sequence__lte=target.plan.cycle.sequence
    ).order_by("plan__cycle__sequence"))
    previous_actual = sum(count_items(item) for item in targets[:-1])
    cycle_baseline = targets[-1].quantity
    # A carry is its own cycle commitment. A completed earlier binary goal stays done.
    if target.goal.kind == "done" and previous_actual:
        return 0
    return max(0, cycle_baseline - count_items(targets[-1]))


def reason_for(user, reason_id):
    reason = Reason.objects.filter(user=user, pk=reason_id, active=True).first()
    if reason is None:
        raise ValidationError({"reason_id": "Choose an active reason from your preferences."})
    return reason


def clean_values(fields, raw):
    if not isinstance(raw, dict):
        raise ValidationError("Enter a field-value object.")
    unknown = set(raw) - {field["key"] for field in fields}
    if unknown:
        raise ValidationError(f"Unknown fields: {', '.join(sorted(unknown))}.")
    clean = {}
    for field in fields:
        key, kind, label = field["key"], field["type"], field["label"]
        value = raw.get(key)
        if value is None or value == "":
            if field["required"]:
                raise ValidationError({key: f"{label} is required."})
            continue
        valid = False
        if kind == "number":
            try:
                number = Decimal(str(value))
                valid = number.is_finite() and abs(number) <= Decimal("1000000000000")
                value = str(number) if valid else value
            except ArithmeticError:
                pass
        elif kind == "date":
            try:
                value = date.fromisoformat(value).isoformat()
                valid = True
            except (TypeError, ValueError):
                pass
        elif kind == "url" and isinstance(value, str):
            try:
                parsed = urlsplit(value)
                valid = len(value) <= 2048 and parsed.scheme in {"http", "https"} and bool(parsed.hostname)
            except ValueError:
                pass
        elif kind == "choice":
            valid = value in field["choices"]
        elif kind == "text":
            valid = isinstance(value, str) and 0 < len(value.strip()) <= 2000
        if not valid:
            raise ValidationError({key: f"Enter a valid value for {label}."})
        clean[key] = value
    return clean


def clean_items(goal, raw):
    if len(raw) > 500 or (goal.kind == "done" and len(raw) > 1):
        raise ValidationError({"items": "Enter one item for a Done goal or up to 500 for a Count goal."})
    return [clean_values(goal.task.entry_fields, item) for item in raw]


def money(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def payable(project, day):
    terms = PayTerms.objects.filter(project=project, effective_on__lte=day).order_by("-effective_on").first()
    if terms is None:
        raise ValidationError("Add pay terms effective on or before this work date.")
    return terms


def build_receivable(project, day, terms, *, gross, **kwargs):
    gross = money(gross)
    if gross >= Decimal("100000000000000"):
        raise ValidationError("The gross amount exceeds the supported limit.")
    tax = money(gross * terms.tax_pct / Decimal(100))
    return Receivable.objects.create(project=project, work_day=day, terms=terms,
                                     gross=gross, tax=tax, net=gross-tax, **kwargs)


def paid(receivable):
    return receivable.payments.aggregate(total=Sum("amount"))["total"] or Decimal(0)


def balance(project):
    return sum((item.net - paid(item) for item in project.receivables.all()), Decimal(0))
