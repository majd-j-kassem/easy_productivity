from datetime import date

import pytest
from django.urls import reverse

from planner.models import Cycle, Goal, Plan, Project, Target, Task

from .models import ProfessionalProfile, ProfileShare, PublishedProject


@pytest.mark.django_db
def test_portfolio_preview_then_publish_excludes_financial_goals(client, django_user_model):
    owner = django_user_model.objects.create_user("portfolio-owner")
    profile = ProfessionalProfile.objects.create(owner=owner)
    share = ProfileShare.objects.create(profile=profile)
    day = date(2026, 11, 10)
    project = Project.objects.create(owner=owner, name="QA project", start=day, first_review=day,
                                     interval=1, interval_unit="weeks", status="closed", closed_on=day)
    task = Task.objects.create(project=project, name="Write tests", status="completed",
                               reference_url="https://example.org/evidence")
    cycle = Cycle.objects.create(project=project, start=day, end=day, sequence=1)
    plan = Plan.objects.create(task=task, cycle=cycle)
    for name, kind in [("Test cases", "count"), ("Private earnings", "net_income")]:
        goal = Goal.objects.create(task=task, name=name, kind=kind, metric=name)
        Target.objects.create(plan=plan, goal=goal, quantity=5)
    client.force_login(owner)
    url = reverse("manage_portfolio")
    response = client.post(url, {"action": "preview", "project_id": project.pk})
    assert b"Test cases" in response.content and b"Private earnings" not in response.content
    assert not PublishedProject.objects.exists()
    assert client.post(url, {"action": "publish", "project_id": project.pk}).status_code == 302
    client.logout()
    response = client.get(reverse("shared_profile", args=[share.token]))
    assert b"QA project" in response.content and b"example.org/evidence" in response.content
    assert b"Private earnings" not in response.content
