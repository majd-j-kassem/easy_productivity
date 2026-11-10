from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from . import serializers as inputs
from .models import (Correction, Cycle, DailyEntry, Goal, Notification, PayTerms, Payment,
                     Plan, Project, Reason, Target, Task, TaskKind)
from .presenters import cycle_data, fields_of, kind_data, plan_data, project_data, receivable_data
from .rules import (balance, build_receivable, clean_items, clean_values, default_first_review,
                    paid, payable, profile_for, target_actual, today_for)
from .services import (apply_decisions, close_cycle, generate_months, last_of_month,
                       missing_months, month_is_full)


def validate(serializer, request):
    form = serializer(data=request.data)
    form.is_valid(raise_exception=True)
    return form.validated_data


def owned(request, pk, lock=False):
    rows = Project.objects.filter(owner=request.user)
    return get_object_or_404(rows.select_for_update() if lock else rows, pk=pk)


def active(project):
    if project.status != "active":
        raise ValidationError("This action requires an active project.")


def open_cycle(project):
    return get_object_or_404(project.cycles, closed_at__isnull=True)


def planning_cycle(project, today):
    active(project)
    cycle = open_cycle(project)
    if cycle.end < today:
        raise ValidationError("Close the overdue cycle before changing the plan.")
    return cycle


@api_view(["GET", "PATCH"])
def preferences(request):
    profile = profile_for(request.user)
    if request.method == "PATCH":
        form = inputs.ProfileInput(profile, data=request.data, partial=True)
        form.is_valid(raise_exception=True)
        form.save()
    return Response(inputs.ProfileInput(profile).data)


@api_view(["GET", "POST"])
def reasons(request):
    profile_for(request.user)
    if request.method == "POST":
        form = inputs.ReasonInput(data=request.data)
        form.is_valid(raise_exception=True)
        form.save(user=request.user)
        return Response(form.data, status=201)
    return Response(inputs.ReasonInput(Reason.objects.filter(user=request.user).order_by("id"), many=True).data)


@api_view(["PATCH"])
def reason_detail(request, pk):
    row = get_object_or_404(Reason, user=request.user, pk=pk)
    form = inputs.ReasonInput(row, data=request.data, partial=True)
    form.is_valid(raise_exception=True)
    form.save()
    return Response(form.data)


@api_view(["GET", "POST"])
@transaction.atomic
def projects(request):
    if request.method == "POST":
        data = validate(inputs.ProjectSetupInput, request)
        initial_tasks = data.pop("tasks")
        profile = profile_for(request.user)
        data.setdefault("interval", profile.interval)
        data.setdefault("interval_unit", profile.interval_unit)
        data.setdefault("first_review", default_first_review(data["start"], data["interval"], data["interval_unit"]))
        if data["first_review"] < data["start"]:
            raise ValidationError({"first_review": "The first review must be on or after the start."})
        if data.get("planned_end") and data["planned_end"] < data["start"]:
            raise ValidationError({"planned_end": "The end must be on or after the start."})
        data["currency"] = data.get("currency", profile.currency).upper() if data.get("mode", "standard") != "standard" else ""
        project = Project.objects.create(owner=request.user, **data)
        cycle = Cycle.objects.create(project=project, sequence=1, start=project.start, end=project.first_review)
        for task_data in initial_tasks:
            create_task(project, cycle, task_data)
        return Response(project_data(project), status=201)
    rows = Project.objects.filter(owner=request.user).order_by("-id")
    query = request.query_params
    if query.get("status"):
        rows = rows.filter(status=query["status"])
    if query.get("task_status"):
        rows = rows.filter(tasks__status=query["task_status"])
    if query.get("q"):
        rows = rows.filter(Q(name__icontains=query["q"]) | Q(tasks__name__icontains=query["q"]))
    today = today_for(request.user)
    return Response([
        project_data(row) | {"review_due": any(
            not cycle.closed_at and cycle.end <= today for cycle in row.cycles.all()
        ) and row.status == "active"}
        for row in rows.distinct().prefetch_related("cycles")
    ])


@api_view(["GET", "PATCH", "DELETE"])
@transaction.atomic
def project_detail(request, pk):
    project = owned(request, pk, lock=request.method != "GET")
    if request.method == "DELETE":
        project.delete()
        return Response(status=204)
    today = today_for(request.user)
    if request.method == "PATCH":
        active(project)
        unknown = set(request.data) - {"name", "planned_end"}
        if unknown:
            raise ValidationError({key: "This field cannot be changed after creation." for key in unknown})
        data = validate(inputs.ProjectEdit, request)
        if data.get("planned_end") and data["planned_end"] < project.start:
            raise ValidationError({"planned_end": "The end must be on or after the start."})
        for key, value in data.items():
            setattr(project, key, value)
        if data:
            project.save(update_fields=list(data))
    return Response(project_data(project) | {
        "cycles": [cycle_data(cycle, today) for cycle in project.cycles.order_by("-sequence")],
        "kinds": [kind_data(kind) for kind in project.kinds.order_by("name", "id")],
    })


@api_view(["POST"])
@transaction.atomic
def kinds(request, pk):
    project = owned(request, pk, lock=True)
    active(project)
    data = validate(inputs.KindInput, request)
    return Response(kind_data(TaskKind.objects.create(project=project, **data)), status=201)


@api_view(["PATCH", "DELETE"])
@transaction.atomic
def kind_detail(request, pk, kind_id):
    project = owned(request, pk, lock=True)
    active(project)
    kind = get_object_or_404(project.kinds, pk=kind_id)
    if request.method == "DELETE":
        if project.tasks.filter(kind=kind).exists():
            raise ValidationError("This task type is still used by existing tasks.")
        kind.delete()
        return Response(status=204)
    form = inputs.KindInput(data=request.data, partial=True)
    form.is_valid(raise_exception=True)
    for key, value in form.validated_data.items():
        setattr(kind, key, value)
    if form.validated_data:
        kind.save(update_fields=list(form.validated_data))
    return Response(kind_data(kind))


def require_hourly_project(project):
    if project.mode != "hourly":
        raise ValidationError("An Hours worked goal requires an hourly income project.")


def create_goal(plan, data):
    if data["kind"] == "hours":
        require_hourly_project(plan.cycle.project)
    elif data["kind"] == "net_income":
        if plan.cycle.project.mode == "standard":
            raise ValidationError("A Net income goal requires an income project.")
        if Target.objects.filter(plan__cycle=plan.cycle, goal__kind="net_income").exists():
            raise ValidationError("This cycle already has a project-wide Net income goal.")
    quantity = data.pop("quantity")
    goal = Goal.objects.create(task=plan.task, **data)
    Target.objects.create(plan=plan, goal=goal, quantity=quantity)


def create_task(project, cycle, data):
    kind = get_object_or_404(project.kinds, pk=data["kind_id"]) if "kind_id" in data else None
    task_fields = kind.task_fields if kind else []
    task = Task.objects.create(
        project=project, kind=kind, name=data["name"], description=data["description"],
        reference_url=data["reference_url"], values=clean_values(task_fields, data["values"]),
        task_fields=task_fields, entry_fields=kind.entry_fields if kind else [],
    )
    plan = Plan.objects.create(cycle=cycle, task=task, priority=data["priority"])
    for item in data["goals"]:
        create_goal(plan, item)
    return plan


@api_view(["POST"])
@transaction.atomic
def tasks(request, pk):
    project = owned(request, pk, lock=True)
    cycle = planning_cycle(project, today_for(request.user))
    return Response(plan_data(create_task(project, cycle, validate(inputs.TaskInput, request))), status=201)


@api_view(["DELETE"])
@transaction.atomic
def task_detail(request, pk, task_id):
    project = owned(request, pk, lock=True)
    active(project)
    task = get_object_or_404(project.tasks, pk=task_id)
    if task.plans.filter(cycle__closed_at__isnull=False).exists():
        raise ValidationError("This task is part of a closed cycle and is kept for reporting.")
    if project.receivables.filter(task=task).exists():
        raise ValidationError("This task is linked to recorded work in the income ledger.")
    task.delete()
    return Response(status=204)


@api_view(["POST"])
@transaction.atomic
def plan_goals(request, pk, plan_id):
    project = owned(request, pk, lock=True)
    cycle = planning_cycle(project, today_for(request.user))
    plan = get_object_or_404(cycle.plans.select_related("task"), pk=plan_id, task__status="open")
    if plan.targets.count() >= 20:
        raise ValidationError("A task can have up to 20 goals in a cycle.")
    create_goal(plan, validate(inputs.GoalInput, request))
    return Response(plan_data(plan), status=201)


@api_view(["PATCH", "DELETE"])
@transaction.atomic
def goal_detail(request, pk, goal_id):
    project = owned(request, pk, lock=True)
    active(project)
    goal = get_object_or_404(Goal, task__project=project, pk=goal_id)
    if goal.targets.filter(plan__cycle__closed_at__isnull=False).exists():
        raise ValidationError("This goal is part of a closed cycle and is kept for reporting.")
    if request.method == "DELETE":
        goal.delete()
        return Response(status=204)
    require_hourly_project(project)
    cycle = planning_cycle(project, today_for(request.user))
    target = get_object_or_404(goal.targets, plan__cycle=cycle, plan__task__status="open")
    if goal.kind != "count" or target.entries.exists():
        raise ValidationError("Only a Count goal without daily entries can be converted to Hours worked.")
    data = validate(inputs.HoursGoalInput, request)
    goal.kind = "hours"
    goal.metric = "hours worked"
    goal.save(update_fields=["kind", "metric"])
    target.quantity = data["quantity"]
    target.save(update_fields=["quantity"])
    return Response(plan_data(target.plan))


@api_view(["GET"])
def cycle_detail(request, pk, cycle_id):
    project = owned(request, pk)
    cycle = get_object_or_404(project.cycles, pk=cycle_id)
    rows = cycle.plans.select_related("task__kind")
    if request.query_params.get("status"):
        rows = rows.filter(task__status=request.query_params["status"])
    if request.query_params.get("q"):
        rows = rows.filter(task__name__icontains=request.query_params["q"])
    return Response(cycle_data(cycle, today_for(request.user)) | {
        "plans": [plan_data(plan) for plan in rows.order_by("id")],
    })


@api_view(["PATCH"])
@transaction.atomic
def plan_detail(request, pk, plan_id):
    project = owned(request, pk, lock=True)
    cycle = planning_cycle(project, today_for(request.user))
    plan = get_object_or_404(cycle.plans, pk=plan_id, task__status="open")
    data = validate(inputs.PlanInput, request)
    task_updates = {key: data[key] for key in ("name", "description", "reference_url") if key in data}
    for key, value in task_updates.items():
        setattr(plan.task, key, value)
    if task_updates:
        plan.task.save(update_fields=list(task_updates))
    if "priority" in data:
        plan.priority = data["priority"]
        plan.save(update_fields=["priority"])
    targets = {str(target.pk): target for target in plan.targets.select_related("goal")}
    for key, quantity in data.get("targets", {}).items():
        target = targets.get(key)
        if target is None:
            raise ValidationError({"targets": "Invalid target."})
        inputs.validate_quantity(target.goal.kind, quantity)
        if quantity == 0 and target.quantity != 0:
            raise ValidationError({"targets": "An active target needs a positive quantity."})
        target.quantity = quantity
        target.save(update_fields=["quantity"])
    return Response(plan_data(plan))


@api_view(["GET", "PUT"])
@transaction.atomic
def entry(request, pk, target_id, day):
    project = owned(request, pk, lock=request.method == "PUT")
    target = get_object_or_404(Target.objects.select_related("goal__task", "plan__cycle"),
                               plan__cycle__project=project, pk=target_id)
    parsed_day = inputs.s.DateField().run_validation(day)
    cycle = target.plan.cycle
    if not cycle.start <= parsed_day <= cycle.end:
        raise ValidationError({"day": "Use a date within the selected cycle."})
    if parsed_day > today_for(request.user):
        raise ValidationError({"day": "The entry date cannot be in the future."})
    row = DailyEntry.objects.filter(target=target, day=parsed_day).first()
    if request.method == "GET":
        return Response({"day": parsed_day, "items": row.items if row else [],
                         "corrections": [fields_of(change, "previous revised reason created_at")
                                         for change in row.corrections.order_by("id")] if row else []})
    if target.goal.kind in {"hours", "net_income"}:
        raise ValidationError("This goal is calculated from the income ledger.")
    data = validate(inputs.EntryInput, request)
    items = clean_items(target.goal, data["items"])
    if cycle.closed_at or project.status == "closed":
        if not data.get("reason"):
            raise ValidationError({"reason": "Explain the correction to this closed cycle."})
        if row is None:
            row = DailyEntry.objects.create(target=target, day=parsed_day, items=[])
        if row.items != items:
            Correction.objects.create(entry=row, previous=row.items, revised=items, reason=data["reason"])
    else:
        active(project)
        if target.plan.task.status != "open":
            raise ValidationError("This task is already closed.")
        if target.quantity == 0:
            raise ValidationError("This target is already satisfied from an earlier cycle.")
        if row is None:
            row = DailyEntry.objects.create(target=target, day=parsed_day, items=[])
    row.items = items
    row.save(update_fields=["items"])
    return Response({"day": parsed_day, "items": row.items})


@api_view(["GET"])
def entry_dates(request, pk, target_id):
    project = owned(request, pk)
    target = get_object_or_404(Target, plan__cycle__project=project, pk=target_id)
    return Response(list(target.entries.order_by("day").values_list("day", flat=True)))


@api_view(["POST"])
@transaction.atomic
def complete_plan(request, pk, plan_id):
    project = owned(request, pk, lock=True)
    active(project)
    cycle = open_cycle(project)
    plan = get_object_or_404(cycle.plans.select_related("task"), pk=plan_id)
    if plan.task.status == "completed":
        return Response(plan_data(plan))
    if plan.task.status != "open":
        raise ValidationError("The task is already closed.")
    apply_decisions(request.user, [plan], {str(plan.pk): {"action": "complete", "note": ""}}, allow_carry=False)
    return Response(plan_data(plan))


@api_view(["POST"])
@transaction.atomic
def review(request, pk, cycle_id):
    project = owned(request, pk, lock=True)
    active(project)
    cycle = get_object_or_404(project.cycles, pk=cycle_id)
    today = today_for(request.user)
    if cycle.closed_at:
        return Response({"closed": cycle.pk, "already_closed": True})
    if cycle.end > today:
        raise ValidationError("Review opens on the scheduled review date.")
    data = validate(inputs.ReviewInput, request)
    new_cycle = close_cycle(cycle, request.user, data["decisions"])
    return Response({"closed": cycle.pk, "next": cycle_data(new_cycle, today)})


@api_view(["POST"])
@transaction.atomic
def finish(request, pk):
    project = owned(request, pk, lock=True)
    if project.status == "closed":
        return Response(project_data(project))
    today = today_for(request.user)
    data = validate(inputs.ReviewInput, request)
    if project.status == "active":
        if project.start > today:
            raise ValidationError("The project has not started.")
        cycle = open_cycle(project)
        if cycle.end < today:
            raise ValidationError("Review overdue cycles before ending the project.")
        if project.mode == "monthly":
            generate_months(project, today, through=today)
            missing = missing_months(project, today)
            if missing:
                raise ValidationError({"receivables": f"Record outstanding monthly amounts for {', '.join(missing)}."})
        plans = list(cycle.plans.filter(task__status="open").select_related("task"))
        apply_decisions(request.user, plans, data["decisions"], allow_carry=False)
        cycle.closed_at = timezone.now()
        cycle.save(update_fields=["closed_at"])
        project.work_ended = today
    if project.mode != "standard" and balance(project) > 0:
        project.status = "awaiting_payment"
    else:
        project.status = "closed"
        project.closed_on = today
    project.save(update_fields=["work_ended", "closed_on", "status"])
    return Response(project_data(project))


@api_view(["GET", "POST"])
@transaction.atomic
def terms(request, pk):
    project = owned(request, pk, lock=request.method == "POST")
    if project.mode == "standard":
        raise ValidationError("This project is not financial.")
    if request.method == "POST":
        active(project)
        data = validate(inputs.TermsInput, request)
        if project.terms.filter(effective_on=data["effective_on"]).exists():
            raise ValidationError({"effective_on": "Pay terms already exist on this date."})
        if project.mode == "monthly" and project.terms.exists() and data["effective_on"].day != 1:
            raise ValidationError({"effective_on": "New monthly terms start on the first day of a month."})
        if project.receivables.filter(work_day__gte=data["effective_on"]).exists():
            raise ValidationError({"effective_on": "Choose a date after the latest recorded work."})
        row = PayTerms.objects.create(project=project, **data)
        return Response(fields_of(row, "id effective_on rate tax_pct"), status=201)
    return Response([fields_of(row, "id effective_on rate tax_pct")
                     for row in project.terms.order_by("-effective_on")])


@api_view(["DELETE"])
@transaction.atomic
def terms_detail(request, pk, terms_id):
    project = owned(request, pk, lock=True)
    active(project)
    row = get_object_or_404(project.terms, pk=terms_id)
    if project.receivables.filter(terms=row).exists():
        raise ValidationError("These pay terms are used by recorded work in the income ledger.")
    row.delete()
    return Response(status=204)


@api_view(["GET"])
def ledger(request, pk):
    project = owned(request, pk)
    rows = [receivable_data(item) for item in project.receivables.select_related("terms").order_by("-work_day", "-id")]
    monthly = {}
    for row in rows:
        for payment in row["payments"]:
            key = payment["received_on"].strftime("%Y-%m")
            monthly[key] = monthly.get(key, Decimal(0)) + payment["amount"]
    return Response({"currency": project.currency, "items": rows, "received_by_month": monthly,
                     "remaining": sum((row["remaining"] for row in rows), Decimal(0))})


@api_view(["POST"])
@transaction.atomic
def hourly(request, pk):
    project = owned(request, pk, lock=True)
    active(project)
    if project.mode != "hourly":
        raise ValidationError("This project does not use hourly pay.")
    data = validate(inputs.HoursInput, request)
    if not project.start <= data["work_day"] <= today_for(request.user):
        raise ValidationError({"work_day": "Use a past or present work date on or after the project start."})
    task = None
    if "task_id" in data:
        task = get_object_or_404(project.tasks, pk=data["task_id"])
    terms_row = payable(project, data["work_day"])
    row = build_receivable(project, data["work_day"], terms_row, gross=data["hours"] * terms_row.rate,
                           hours=data["hours"], location=data["location"], task=task)
    return Response(receivable_data(row), status=201)


@api_view(["POST"])
@transaction.atomic
def monthly(request, pk):
    project = owned(request, pk, lock=True)
    active(project)
    if project.mode != "monthly":
        raise ValidationError("This project does not use monthly pay.")
    data = validate(inputs.MonthInput, request)
    month = data["month"].replace(day=1)
    today = today_for(request.user)
    if not project.start.replace(day=1) <= month <= today.replace(day=1):
        raise ValidationError({"month": "Choose a month within the project's work period."})
    if month_is_full(project, month) and last_of_month(month) <= today:
        raise ValidationError({"month": "Only partial months can be entered manually."})
    if project.receivables.filter(month=month).exists():
        raise ValidationError({"month": "A receivable already exists for this month."})
    work_day = min(today, last_of_month(month))
    terms_row = payable(project, max(month, project.start))
    row = build_receivable(project, work_day, terms_row, gross=data["gross"], month=month)
    return Response(receivable_data(row), status=201)


@api_view(["DELETE"])
@transaction.atomic
def receivable_detail(request, pk, receivable_id):
    project = owned(request, pk, lock=True)
    active(project)
    row = get_object_or_404(project.receivables, pk=receivable_id)
    if row.payments.exists():
        raise ValidationError("Delete the recorded payments for this entry first.")
    if project.cycles.filter(closed_at__isnull=False, start__lte=row.work_day, end__gte=row.work_day).exists():
        raise ValidationError("This entry belongs to a closed cycle and is kept for reporting.")
    if row.month and month_is_full(project, row.month) and last_of_month(row.month) <= today_for(request.user):
        raise ValidationError("A full-month receivable is generated automatically and cannot be deleted.")
    completed = Target.objects.select_related("goal", "plan__cycle").filter(
        plan__cycle__project=project, plan__cycle__start__lte=row.work_day,
        plan__cycle__end__gte=row.work_day, plan__task__status="completed",
    ).filter(Q(goal__kind="net_income") | Q(goal__kind="hours", goal__task_id=row.task_id))
    for target in completed:
        contribution = row.net if target.goal.kind == "net_income" else row.hours or Decimal(0)
        if contribution and target_actual(target) - contribution < target.quantity:
            raise ValidationError("This entry is needed to meet a completed goal.")
    row.delete()
    return Response(status=204)


@api_view(["POST"])
@transaction.atomic
def payments(request, pk, receivable_id):
    project = owned(request, pk, lock=True)
    if project.status == "closed":
        raise ValidationError("The project is already closed.")
    row = get_object_or_404(project.receivables, pk=receivable_id)
    data = validate(inputs.PaymentInput, request)
    if not project.start <= data["received_on"] <= today_for(request.user):
        raise ValidationError({"received_on": "Use a past or present date on or after the project start."})
    if data["amount"] > row.net - paid(row):
        raise ValidationError({"amount": "The payment exceeds the remaining amount."})
    Payment.objects.create(receivable=row, **data)
    return Response(receivable_data(row), status=201)


@api_view(["DELETE"])
@transaction.atomic
def payment_detail(request, pk, receivable_id, payment_id):
    project = owned(request, pk, lock=True)
    if project.status == "closed":
        raise ValidationError("The project is already closed.")
    row = get_object_or_404(project.receivables, pk=receivable_id)
    payment = get_object_or_404(row.payments, pk=payment_id)
    payment.delete()
    return Response(status=204)


@api_view(["GET"])
def notifications(request):
    rows = Notification.objects.filter(cycle__project__owner=request.user).select_related("cycle__project")
    return Response([
        fields_of(row, "id read_at created_at") | {
            "project_id": row.cycle.project_id, "project": row.cycle.project.name,
            "cycle_id": row.cycle_id, "review_on": row.cycle.end,
        } for row in rows.order_by("-created_at")[:100]
    ])


@api_view(["POST"])
def notification_read(request, pk):
    row = get_object_or_404(Notification, pk=pk, cycle__project__owner=request.user)
    if not row.read_at:
        row.read_at = timezone.now()
        row.save(update_fields=["read_at"])
    return Response({"read_at": row.read_at})
