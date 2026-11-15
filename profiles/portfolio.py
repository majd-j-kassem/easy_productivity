from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from planner.models import Project
from planner.rules import target_actual

from .models import ProfessionalProfile, PublishedProject

safe_url = URLValidator(schemes=["http", "https"])


def evidence_links(task, targets):
    fields = [field["key"] for field in task.entry_fields if field["type"] == "url"]
    links = [task.reference_url]
    for target in targets:
        for entry in target.entries.all():
            for item in entry.items:
                links.extend(item.get(field) for field in fields)
    evidence = []
    for link in dict.fromkeys(value for value in links if isinstance(value, str) and value):
        try:
            safe_url(link)
        except ValidationError:
            continue
        evidence.append(link)
        if len(evidence) == 10:
            break
    return evidence


def portfolio_snapshot(project):
    goals = []
    tasks = project.tasks.filter(status="completed").prefetch_related(
        "goals__targets__entries", "goals__targets__plan__cycle",
    ).order_by("pk")
    for task in tasks:
        for goal in task.goals.all():
            if goal.kind not in {"done", "count"}:
                continue
            targets = sorted((target for target in goal.targets.all() if not target.plan.cycle.is_draft),
                             key=lambda target: target.plan.cycle.sequence)
            if not targets:
                continue
            actual = sum(target_actual(target) for target in targets)
            goals.append({
                "task": task.name, "name": goal.name, "target": str(targets[0].quantity),
                "actual": str(min(actual, 1) if goal.kind == "done" else actual),
                "evidence": evidence_links(task, targets),
            })
    return {"name": project.name, "goals": goals}


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def manage_portfolio(request):
    profile = get_object_or_404(ProfessionalProfile, owner=request.user)
    projects = Project.objects.filter(owner=request.user, status="closed").order_by("name", "id")
    preview = None
    if request.method == "POST":
        try:
            project_id = int(request.POST.get("project_id", ""))
        except ValueError as error:
            raise Http404("Project not found.") from error
        if not 0 < project_id <= 2**63 - 1:
            raise Http404("Project not found.")
        project = get_object_or_404(projects, pk=project_id)
        action = request.POST.get("action")
        if action == "unpublish":
            PublishedProject.objects.filter(profile=profile, project=project).delete()
            return redirect("manage_portfolio")
        preview = portfolio_snapshot(project)
        if action == "publish":
            PublishedProject.objects.update_or_create(
                profile=profile, project=project, defaults={"snapshot": preview},
            )
            return redirect("manage_portfolio")
        preview["project_id"] = project.pk
    return render(request, "profiles/portfolio.html", {
        "projects": projects, "preview": preview,
        "published": set(profile.published_projects.values_list("project_id", flat=True)),
    })
