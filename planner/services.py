from calendar import monthrange
from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import Cycle, DailyEntry, Notification, Plan, Target, Task
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
    new_cycle = cycle.project.cycles.filter(sequence=cycle.sequence + 1, is_draft=True).first()
    if new_cycle is None:
        new_cycle = next_cycle(cycle)
    else:
        if new_cycle.plans.filter(targets__goal__kind="net_income").exists() and any(
            plan.targets.filter(goal__kind="net_income").exists() for plan in carried
        ):
            raise ValidationError("Remove the draft Net income goal or choose a different decision for the current one.")
        new_cycle.is_draft = False
        new_cycle.save(update_fields=["is_draft"])
    for old in carried:
        plan = Plan.objects.create(cycle=new_cycle, task=old.task, priority=old.priority)
        Target.objects.bulk_create([
            Target(plan=plan, goal=target.goal, quantity=carry_quantity(target))
            for target in old.targets.select_related("goal", "plan__cycle")
        ])
    return new_cycle


def change_cycle_dates(cycle, data):
    if cycle.closed_at:
        raise ValidationError("Closed cycle dates are kept for reporting.")
    project = cycle.project
    start = data.get("start", cycle.start)
    end = data.get("end", cycle.end)
    if (start, end) == (cycle.start, cycle.end):
        return
    if cycle.sequence > 1 and start != cycle.start:
        raise ValidationError({"start": "This cycle starts the day after the previous cycle ends."})
    if end < start:
        raise ValidationError({"end": "The review date must be on or after the start."})
    if cycle.sequence == 1 and project.planned_end and project.planned_end < start:
        raise ValidationError({"start": "The start must be on or before the planned project end."})
    if DailyEntry.objects.filter(target__plan__cycle=cycle).exclude(day__range=(start, end)).exists():
        raise ValidationError("The new dates must include all daily entries in this cycle.")
    work = project.receivables.filter(work_day__range=(cycle.start, cycle.end))
    if not cycle.is_draft and work.exclude(work_day__range=(start, end)).exists():
        raise ValidationError("The new dates must include recorded work in this cycle.")
    if start != cycle.start and (
        project.receivables.filter(payments__received_on__lt=start).exists()
        or (project.mode == "monthly" and project.receivables.exists())
    ):
        raise ValidationError("The start date would conflict with the existing income ledger.")
    shift = end - cycle.end
    cycle.start, cycle.end = start, end
    cycle.save(update_fields=["start", "end"])
    if cycle.sequence == 1:
        project.start, project.first_review = start, end
        project.save(update_fields=["start", "first_review"])
    if shift:
        Notification.objects.filter(cycle=cycle).delete()
        drafts = list(project.cycles.filter(sequence__gt=cycle.sequence, is_draft=True))
        for draft in drafts:
            draft.start += shift
            draft.end += shift
        Cycle.objects.bulk_update(drafts, ["start", "end"])


def copy_plan_to_draft(source, cycle):
    original = source.task
    task = Task.objects.create(
        project=cycle.project, kind=original.kind, name=original.name, description=original.description,
        reference_url=original.reference_url, values=original.values,
        task_fields=original.task_fields, entry_fields=original.entry_fields,
    )
    plan = Plan.objects.create(cycle=cycle, task=task, priority=source.priority)
    for target in source.targets.select_related("goal"):
        goal = target.goal
        copied = task.goals.create(name=goal.name, metric=goal.metric, kind=goal.kind)
        quantity = target.quantity or goal.targets.order_by("plan__cycle__sequence").first().quantity
        Target.objects.create(plan=plan, goal=copied, quantity=quantity)


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


def record_hourly_work(project, today, data):
    if project.status != "active":
        raise ValidationError("This action requires an active project.")
    if project.mode != "hourly":
        raise ValidationError("This project does not use hourly pay.")
    day = data["work_day"]
    if not project.start <= day <= today:
        raise ValidationError({"work_day": "Use a past or present work date on or after the project start."})
    task = None
    if "task_id" in data:
        task = get_object_or_404(project.tasks.filter(plans__cycle__is_draft=False).distinct(), pk=data["task_id"])
    terms = payable(project, day)
    return build_receivable(project, day, terms, gross=data["hours"] * terms.rate,
                            hours=data["hours"], location=data["location"], task=task)
