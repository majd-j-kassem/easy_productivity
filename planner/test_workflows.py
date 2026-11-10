from datetime import date
from io import BytesIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from openpyxl import load_workbook
from rest_framework.test import APIClient

from .models import Correction, DailyEntry, Invite, Notification, Payment, Reason, Receivable
from .rules import add_months

pytestmark = pytest.mark.django_db


@pytest.fixture
def account(django_user_model):
    user = django_user_model.objects.create_user("planner", "planner@example.org", "Fixture1-L0ng-S3cret")
    client = APIClient()
    client.force_authenticate(user)
    return user, client


def post(client, path, data):
    response = client.post("/api/v1/" + path, data, format="json")
    assert response.status_code in (200, 201), response.data
    return response.data


def make_project(client, **kwargs):
    project = post(client, "projects/", {
        "name": "QA", "start": "2026-11-09", "first_review": "2026-11-15",
        "interval": 1, "interval_unit": "weeks", **kwargs,
    })
    return f"projects/{project['id']}/"


def create_task(client, path):
    kind = post(client, path + "kinds/", {"name": "Test case",
        "entry_fields": [{"key": "scenario", "label": "Scenario", "type": "text", "required": True}]})
    return post(client, path + "tasks/", {
        "name": "Design tests", "kind_id": kind["id"], "goals": [
            {"name": "Create login tests", "metric": "Test cases", "kind": "count", "quantity": 5},
        ],
    })


def test_cycle_rule_immutable_and_user_isolation(account, django_user_model):
    _, client = account
    path = make_project(client)
    assert client.patch("/api/v1/" + path, {"interval": 2}, format="json").status_code == 400
    response = client.get("/api/v1/" + path)
    assert response.data["interval"] == 1
    other = django_user_model.objects.create_user("other")
    client.force_authenticate(other)
    assert client.get("/api/v1/" + path).status_code == 404


def test_carry_correction_and_reports(account):
    _, client = account
    with patch("planner.api.today_for", return_value=date(2026, 11, 15)):
        path = make_project(client)
        cycle = client.get("/api/v1/" + path).data["cycles"][0]
        plan = create_task(client, path)
        target = plan["targets"][0]
        url = "/api/v1/" + path + f"targets/{target['id']}/entries/2026-11-15/"
        outputs = [{"scenario": f"Test {i}"} for i in range(3)]
        assert client.put(url, {"items": outputs}, format="json").status_code == 200
        assert client.put(url, {"items": outputs}, format="json").status_code == 200
        reason = post(client, "reasons/", {"label": "Blocked"})
        review = post(client, path + f"cycles/{cycle['id']}/review/", {
            "decisions": {str(plan["id"]): {"action": "carry", "reason_id": reason["id"]}},
        })
        next_path = "/api/v1/" + path + f"cycles/{review['next']['id']}/"
        next_goal = client.get(next_path).data["plans"][0]["targets"][0]
        assert (next_goal["quantity"], next_goal["previous_actual"]) == (2, 3)
        outputs.append({"scenario": "Test 3"})
        assert client.put(url, {"items": outputs}, format="json").status_code == 400
        assert client.put(url, {"items": outputs, "reason": "Missed an output"}, format="json").status_code == 200
        next_goal = client.get(next_path).data["plans"][0]["targets"][0]
        assert (next_goal["quantity"], next_goal["previous_actual"], next_goal["remaining_original"]) == (2, 4, 1)
    with patch("planner.api.today_for", return_value=date(2026, 11, 16)):
        next_plan = client.get(next_path).data["plans"][0]
        assert client.patch("/api/v1/" + path + f"plans/{next_plan['id']}/", {
            "targets": {str(next_goal["id"]): 1},
        }, format="json").status_code == 200
        next_entry = "/api/v1/" + path + f"targets/{next_goal['id']}/entries/2026-11-16/"
        assert client.put(next_entry, {"items": [{"scenario": "Test 4"}]}, format="json").status_code == 200
        closed = post(client, path + "finish/", {"decisions": {str(next_plan["id"]): {"action": "complete"}}})
        assert closed["status"] == "closed"
    result = client.get("/api/v1/" + path + "report/").data
    assert result["metrics"] == [{"metric": "test cases", "measurement": "count", "planned": 5, "actual": 5}]
    xlsx = client.get("/api/v1/" + path + "report.xlsx")
    assert "Cycles" in load_workbook(BytesIO(xlsx.content)).sheetnames
    assert client.get("/api/v1/" + path + "report.pdf").content.startswith(b"%PDF")


def test_overdue_cycle_blocks_plan(account):
    _, client = account
    with patch("planner.api.today_for", return_value=date(2026, 11, 18)):
        path = make_project(client)
        assert client.post("/api/v1/" + path + "tasks/", {}, format="json").status_code == 400


def test_payments_follow_received_month_and_block_closure(account):
    _, client = account
    with patch("planner.api.today_for", return_value=date(2026, 11, 15)):
        path = make_project(client, mode="hourly")
        post(client, path + "terms/", {"effective_on": "2026-11-09", "rate": "3000", "tax_pct": "10"})
        item = post(client, path + "ledger/hourly/", {"work_day": "2026-11-12", "hours": "3.5"})
        assert item["net"] == 9450
        project = post(client, path + "finish/", {})
        assert project["status"] == "awaiting_payment"
    with patch("planner.api.today_for", return_value=date(2026, 12, 4)):
        payments = path + f"ledger/{item['id']}/payments/"
        assert post(client, payments, {"received_on": "2026-12-02", "amount": "6000"})["remaining"] == 3450
        assert post(client, path + "finish/", {})["status"] == "awaiting_payment"
        post(client, payments, {"received_on": "2026-12-03", "amount": "3450"})
        assert post(client, path + "finish/", {})["status"] == "closed"
    ledger = client.get("/api/v1/" + path + "ledger/").data
    assert ledger["received_by_month"] == {"2026-12": 9450}


def test_signup_uses_one_invite(client):
    invite = Invite.objects.create(email="friend@example.org")
    path = f"/signup/{invite.token}/"
    response = client.post(path, {"username": "friend", "password1": "Fixture1-L0ng-S3cret",
                                  "password2": "Fixture1-L0ng-S3cret"})
    assert response.status_code == 302
    assert client.get(path).status_code == 404


def test_reminder_generation_is_repeatable(account, mailoutbox):
    _, client = account
    make_project(client, start="2020-01-01", first_review="2020-01-07")
    call_command("process_planner")
    call_command("process_planner")
    assert Notification.objects.count() == 1
    assert len(mailoutbox) == 1


def test_monthly_anchor_does_not_drift():
    january = date(2026, 1, 31)
    assert add_months(january, 1) == date(2026, 2, 28)
    assert add_months(january, 2) == date(2026, 3, 31)



def test_delete_project_removes_owned_records_only(account, django_user_model):
    user, client = account
    with patch("planner.api.today_for", return_value=date(2026, 11, 15)):
        path = make_project(client, mode="hourly")
        plan = create_task(client, path)
        target = plan["targets"][0]
        entry_url = "/api/v1/" + path + f"targets/{target['id']}/entries/2026-11-15/"
        assert client.put(entry_url, {"items": [{"scenario": "Login"}]}, format="json").status_code == 200
        reason = post(client, "reasons/", {"label": "Blocked"})
        cycle = client.get("/api/v1/" + path).data["cycles"][0]
        post(client, path + f"cycles/{cycle['id']}/review/", {
            "decisions": {str(plan["id"]): {"action": "carry", "reason_id": reason["id"]}},
        })
        correction = {"items": [{"scenario": "Login page"}], "reason": "Clarify scenario"}
        assert client.put(entry_url, correction, format="json").status_code == 200
        post(client, path + "terms/", {"effective_on": "2026-11-09", "rate": "3000", "tax_pct": "10"})
        item = post(client, path + "ledger/hourly/", {
            "work_day": "2026-11-12", "hours": "1", "task_id": plan["task_id"],
        })
        post(client, path + f"ledger/{item['id']}/payments/", {"received_on": "2026-11-15", "amount": "1000"})
    other_project = make_project(client, name="Keep this project")
    url = "/api/v1/" + path
    client.force_authenticate(django_user_model.objects.create_user("other"))
    assert client.delete(url).status_code == 404
    client.force_authenticate(user)
    assert client.get(url).status_code == 200
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
    assert client.get("/api/v1/" + other_project).status_code == 200
    assert Reason.objects.filter(pk=reason["id"]).exists()
    assert not any(model.objects.exists() for model in (DailyEntry, Correction, Receivable, Payment))


def test_project_setup_is_atomic_and_task_type_is_optional(account):
    _, client = account
    request = {
        "name": "New project", "start": "2026-11-09", "first_review": "2026-11-15",
        "tasks": [
            {"name": "Set up repository", "description": "Initialize Git",
             "reference_url": "https://example.org/repository"},
            {"name": "Work this week", "goals": [
                {"name": "Paid work", "kind": "hours", "quantity": "25"},
            ]},
        ],
    }
    assert client.post("/api/v1/projects/", request, format="json").status_code == 400
    assert client.get("/api/v1/projects/").data == []

    project = post(client, "projects/", request | {"mode": "hourly"})
    path = f"/api/v1/projects/{project['id']}/"
    cycle = client.get(path).data["cycles"][0]
    first, second = client.get(path + f"cycles/{cycle['id']}/").data["plans"]
    assert first["kind"] == "" and first["targets"] == []
    assert first["description"] == "Initialize Git"
    assert first["reference_url"] == "https://example.org/repository"
    assert second["targets"][0]["quantity"] == 25


def test_convert_existing_goal_uses_linked_hours_and_protects_ledger(account):
    _, client = account
    with patch("planner.api.today_for", return_value=date(2026, 11, 15)):
        path = make_project(client, mode="hourly")
        plan = create_task(client, path)
        used = post(client, path + "terms/", {"effective_on": "2026-11-09", "rate": "2000", "tax_pct": "0"})
        post(client, path + "ledger/hourly/", {
            "work_day": "2026-11-12", "hours": "12.50", "task_id": plan["task_id"],
        })
        post(client, path + "ledger/hourly/", {"work_day": "2026-11-12", "hours": "1"})
        unused = post(client, path + "terms/", {"effective_on": "2026-11-13", "rate": "2100", "tax_pct": "0"})
        goal_url = f"/api/v1/{path}goals/{plan['targets'][0]['goal_id']}/"
        response = client.patch(goal_url, {"quantity": "25"}, format="json")
        assert response.status_code == 200, response.data
        goal = response.data["targets"][0]
        assert goal["kind"] == "hours" and float(goal["actual"]) == 12.5 and goal["quantity"] == 25

        assert client.delete(f"/api/v1/{path}terms/{used['id']}/").status_code == 400
        assert client.delete(f"/api/v1/{path}terms/{unused['id']}/").status_code == 204
        assert client.delete(f"/api/v1/{path}tasks/{plan['task_id']}/").status_code == 400
        assert client.delete(goal_url).status_code == 204
        assert len(client.get(f"/api/v1/{path}ledger/").data["items"]) == 2
