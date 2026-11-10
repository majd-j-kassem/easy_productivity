from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST
from rest_framework.exceptions import ValidationError

from planner.models import Payment, Project, Receivable, Target
from planner.rules import target_actual, today_for
from planner.serializers import HoursInput
from planner.services import record_hourly_work

from .models import AgendaItem


class AgendaForm(forms.ModelForm):
    class Meta:
        model = AgendaItem
        fields = ("project", "kind", "name", "day", "hours")
        widgets = {"day": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, projects, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = projects.order_by("name", "id")
        self.fields["project"].label_from_instance = lambda project: project.name
        self.fields["hours"].label = "Planned hours (shifts only)"

    def clean(self):
        data = super().clean()
        if data.get("kind") == "shift":
            project = data.get("project")
            if project and project.mode != "hourly":
                self.add_error("project", "Choose an hourly income project for this shift.")
            if not Decimal(0) < (data.get("hours") or Decimal(0)) <= Decimal(24):
                self.add_error("hours", "Enter planned hours between 0 and 24.")
            if project and data.get("day") and data["day"] < project.start:
                self.add_error("day", "A shift cannot be before the project starts.")
        else:
            data["hours"] = None
        return data


def weekly_balances(projects, start, end):
    totals = defaultdict(lambda: {"earned": Decimal(0), "received": Decimal(0), "outstanding": Decimal(0)})
    receivables = Receivable.objects.filter(project__in=projects, work_day__range=(start, end))
    for row in receivables.values("project__currency").annotate(earned=Sum("net")):
        total = totals[row["project__currency"]]
        total["earned"] = total["outstanding"] = row["earned"]
    paid = Payment.objects.filter(receivable__in=receivables)
    for row in paid.values("receivable__project__currency").annotate(amount=Sum("amount")):
        totals[row["receivable__project__currency"]]["outstanding"] -= row["amount"]
    received = Payment.objects.filter(receivable__project__in=projects, received_on__range=(start, end))
    for row in received.values("receivable__project__currency").annotate(amount=Sum("amount")):
        totals[row["receivable__project__currency"]]["received"] = row["amount"]
    return sorted(totals.items())


@login_required
def weekly_view(request):
    today = today_for(request.user)
    try:
        day = parse_date(request.GET.get("week", "")) or today
    except ValueError:
        day = today
    if not date(2, 1, 1) <= day <= date(9998, 12, 31):
        day = today
    start = day - timedelta(days=day.weekday())
    end = start + timedelta(days=6)
    projects = Project.objects.filter(owner=request.user)
    form = AgendaForm(request.POST or None, projects=projects.filter(status="active"), initial={"day": day})
    if request.method == "POST" and form.is_valid():
        item = form.save()
        return redirect(f"{reverse('weekly_view')}?{urlencode({'week': item.day.isoformat()})}")
    items = AgendaItem.objects.filter(project__in=projects, day__range=(start, end)).select_related("project")
    targets = Target.objects.filter(plan__cycle__project__in=projects, plan__cycle__start__lte=end,
                                    plan__cycle__end__gte=start).select_related(
        "goal", "plan__cycle__project", "plan__task",
    ).order_by("plan__cycle__project__name", "plan__cycle__sequence", "id")
    goals = [{"target": target, "actual": target_actual(target)} for target in targets]
    return render(request, "weekly/index.html", {
        "form": form, "items": items.order_by("day", "id"), "goals": goals,
        "balances": weekly_balances(projects, start, end), "start": start, "end": end, "today": today,
        "previous": start - timedelta(days=7), "next_week": start + timedelta(days=7),
    })


@login_required
@require_POST
@transaction.atomic
def log_shift(request, item_id):
    items = AgendaItem.objects.filter(project__owner=request.user, kind="shift")
    project_id = get_object_or_404(items, pk=item_id).project_id
    project = get_object_or_404(Project.objects.select_for_update(), pk=project_id, owner=request.user)
    item = get_object_or_404(items.select_for_update(), pk=item_id, project=project)
    try:
        if item.ledger_entry_id:
            raise ValidationError("This shift has already been recorded.")
        form = HoursInput(data={"work_day": item.day, "hours": request.POST.get("hours")})
        form.is_valid(raise_exception=True)
        if form.validated_data["hours"] > 24:
            raise ValidationError("Enter at most 24 hours for this shift.")
        item.ledger_entry = record_hourly_work(project, today_for(request.user), form.validated_data)
        item.save(update_fields=["ledger_entry"])
        messages.success(request, "Shift recorded.")
    except ValidationError as error:
        details = error.detail.values() if isinstance(error.detail, dict) else [error.detail]
        errors = [str(message) for value in details for message in (value if isinstance(value, list) else [value])]
        messages.error(request, " ".join(errors))
    return redirect(f"{reverse('weekly_view')}?{urlencode({'week': item.day.isoformat()})}")
