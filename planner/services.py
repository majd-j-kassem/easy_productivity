from calendar import monthrange
from datetime import timedelta

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import Cycle, Goal, Plan, Receivable, Target
from .rules import (add_months, build_receivable, carry_quantity, goals_met,
                    next_cycle, payable, reason_for)


def apply_decisions(user, plans, decisions, allow_carry):
    expected = {str(plan.pk) for plan in plans}
    if set(decisions) != expected:
        raise ValidationError("Provide one decision for every listed open task.")
    carried = []
    for plan in plans:
        data = decisions[str(plan.pk)]
        action = data["action"]
        if action == "carry" and not allow_carry:
            raise ValidationError("Choose a final decision for each open task.")
        task = plan.task
        if action == "complete" and not goals_met(task):
            raise ValidationError(f"{task.name} still has unmet targets.")
        reason = None if action == "complete" else reason_for(user, data.get("reason_id"))
        plan.decision = action
        plan.reason = reason.label if reason else ""
        plan.reason_ref = reason
        plan.note = data["note"]
        plan.save(update_fields=["decision", "reason", "reason_ref", "note"])
        if action == "carry":
            carried.append(plan)
            continue
        task.status = {"complete": "completed", "partial": "partial", "discard": "discarded"}[action]
        task.closed_reason = plan.reason
        task.closed_reason_ref = reason
        task.closed_note = plan.note
        task.save(update_fields=["status", "closed_reason", "closed_reason_ref", "closed_note"])
    return carried


def close_cycle(cycle, user, decisions):
    plans = list(cycle.plans.filter(task__status="open").select_related("task"))
    carried = apply_decisions(user, plans, decisions, allow_carry=True)
    cycle.closed_at = timezone.now()
    cycle.save(update_fields=["closed_at"])
    new_cycle = next_cycle(cycle)
    for old in carried:
        plan = Plan.objects.create(cycle=new_cycle, task=old.task, priority=old.priority)
        Target.objects.bulk_create([
            Target(plan=plan, goal=target.goal, quantity=carry_quantity(target))
            for target in old.targets.select_related("goal", "plan__cycle")
        ])
    return new_cycle


def last_of_month(month):
    return month.replace(day=monthrange(month.year, month.month)[1])


def month_end_for_work(project, month):
    month_end = last_of_month(month)
    return min(month_end, project.work_ended) if project.work_ended else month_end


def month_is_full(project, month):
    return project.start <= month and month_end_for_work(project, month) == last_of_month(month)


def generate_months(project, today, *, through=None):
    month = project.start.replace(day=1)
    last_day = through or project.work_ended or today
    last_month = last_day.replace(day=1)
    existing = set(project.receivables.exclude(month=None).values_list("month", flat=True))
    while month <= last_month:
        month_end = last_of_month(month)
        if month_end <= today and month_is_full(project, month) and month not in existing:
            terms = project.terms.filter(effective_on__lte=month).order_by("-effective_on").first()
            if terms:
                build_receivable(project, month_end, terms, gross=terms.rate, month=month)
        month = add_months(month, 1)


def missing_months(project, through):
    if project.mode != "monthly":
        return []
    month = project.start.replace(day=1)
    last_month = through.replace(day=1)
    existing = set(project.receivables.exclude(month=None).values_list("month", flat=True))
    missing = []
    while month <= last_month:
        if month not in existing:
            missing.append(month.strftime("%Y-%m"))
        month = add_months(month, 1)
    return missing
