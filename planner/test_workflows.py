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


def test_net_income_goal_counts_after_tax_work_in_its_project_and_cycle(account):
    _, client = account
    goal = {"name": "Weekly income", "kind": "net_income", "quantity": "50000"}
    with patch("planner.api.today_for", return_value=date(2026, 11, 15)):
        standard = make_project(client)
        response = client.post(f"/api/v1/{standard}tasks/", {"name": "Income", "goals": [goal]}, format="json")
        assert response.status_code == 400

        path = make_project(client, start="2026-11-01", mode="hourly", currency="HUF")
        other = make_project(client, mode="hourly")
        terms = {"effective_on": "2026-11-01", "rate": "10000", "tax_pct": "20"}
        post(client, path + "terms/", terms)
        post(client, other + "terms/", terms)
        post(client, other + "ledger/hourly/", {"work_day": "2026-11-12", "hours": "3"})
        plan = post(client, path + "tasks/", {"name": "Income", "goals": [goal]})
        response = client.post(f"/api/v1/{path}tasks/", {"name": "Duplicate", "goals": [goal]}, format="json")
        assert response.status_code == 400
        item = post(client, path + "ledger/hourly/", {"work_day": "2026-11-12", "hours": "4"})
        post(client, path + f"ledger/{item['id']}/payments/", {"received_on": "2026-11-15", "amount": "1000"})
        first_cycle = client.get(f"/api/v1/{path}").data["cycles"][0]
        reason = post(client, "reasons/", {"label": "Carry income"})
        next_cycle = post(client, path + f"cycles/{first_cycle['id']}/review/", {
            "decisions": {str(plan["id"]): {"action": "carry", "reason_id": reason["id"]}},
        })["next"]

    with patch("planner.api.today_for", return_value=date(2026, 11, 17)):
        post(client, path + "ledger/hourly/", {"work_day": "2026-11-17", "hours": "1"})
        target = client.get(f"/api/v1/{path}cycles/{next_cycle['id']}/").data["plans"][0]["targets"][0]
        assert target["kind"] == "net_income"
        assert (target["previous_actual"], target["actual"], target["quantity"]) == (32000, 8000, 18000)
        response = client.put(
            f"/api/v1/{path}targets/{target['id']}/entries/2026-11-17/", {"items": [{}]}, format="json",
        )
        assert response.status_code == 400


def test_edit_plan_updates_task_details_without_changing_done_goal(account):
    _, client = account
    with patch("planner.api.today_for", return_value=date(2026, 11, 15)):
        path = make_project(client)
        plan = post(client, path + "tasks/", {
            "name": "Draft", "goals": [{"name": "Publish", "kind": "done", "quantity": 1}],
        })
        url = f"/api/v1/{path}plans/{plan['id']}/"
        details = {"name": "Updated task", "description": "Review the draft",
                   "reference_url": "https://example.org/draft", "priority": "high"}
        response = client.patch(url, details, format="json")
        assert response.status_code == 200, response.data
        assert {key: response.data[key] for key in details} == details
        assert response.data["targets"] == plan["targets"]
        target_id = plan["targets"][0]["id"]
        response = client.patch(url, {"name": "Invalid edit", "targets": {str(target_id): 2}}, format="json")
        assert response.status_code == 400
        response = client.patch(url, {}, format="json")
        assert response.data["name"] == "Updated task"


def test_delete_ledger_payment_then_income_entry(account, django_user_model):
    owner, client = account
    with patch("planner.api.today_for", return_value=date(2026, 11, 15)):
        path = make_project(client, mode="hourly")
        post(client, path + "terms/", {"effective_on": "2026-11-09", "rate": "2000", "tax_pct": "0"})
        plan = post(client, path + "tasks/", {
            "name": "Income", "goals": [{"name": "Cycle income", "kind": "net_income", "quantity": 5000}],
        })
        item = post(client, path + "ledger/hourly/", {"work_day": "2026-11-12", "hours": "2"})
        item_url = f"/api/v1/{path}ledger/{item['id']}/"
        paid_item = post(client, path + f"ledger/{item['id']}/payments/", {
            "received_on": "2026-11-15", "amount": "1000",
        })
        payment_url = item_url + f"payments/{paid_item['payments'][0]['id']}/"
        assert client.delete(item_url).status_code == 400
        client.force_authenticate(django_user_model.objects.create_user("ledger-other"))
        assert client.delete(payment_url).status_code == 404
        assert client.delete(item_url).status_code == 404
        client.force_authenticate(owner)
        assert client.delete(payment_url).status_code == 204
        ledger = client.get(f"/api/v1/{path}ledger/").data
        assert ledger["received_by_month"] == {} and ledger["remaining"] == 4000
        assert client.delete(item_url).status_code == 204
        assert client.get(f"/api/v1/{path}ledger/").data["items"] == []
        cycle = client.get(f"/api/v1/{path}").data["cycles"][0]
        updated = client.get(f"/api/v1/{path}cycles/{cycle['id']}/").data["plans"][0]
        assert updated["id"] == plan["id"] and updated["targets"][0]["actual"] == 0

        needed = post(client, path + "ledger/hourly/", {"work_day": "2026-11-12", "hours": "3"})
        post(client, path + f"plans/{plan['id']}/complete/", {})
        assert client.delete(f"/api/v1/{path}ledger/{needed['id']}/").status_code == 400


def test_cycle_drafts_shift_and_activate_one_at_a_time(account):
    _, client = account
    with patch("planner.api.today_for", return_value=date(2026, 11, 17)):
        path = make_project(client)
        url = f"/api/v1/{path}"
        current = client.get(url).data["cycles"][0]
        response = client.patch(url, {"cycle": {"start": "2026-11-08", "end": "2026-11-17"}}, format="json")
        assert response.status_code == 200, response.data
        assert response.data["start"].isoformat() == "2026-11-08"
        plan = post(client, path + "tasks/", {
            "name": "Practice", "goals": [{"name": "Solve exercises", "kind": "count", "quantity": 2}],
        })
        draft = post(client, path + "cycles/", {"source_plan_ids": [plan["id"]]})
        later = post(client, path + "cycles/", {})
        assert (draft["status"], later["status"]) == ("draft", "draft")
        response = client.patch(url, {"cycle": {"end": "2026-11-16"}}, format="json")
        assert response.status_code == 200, response.data
        upcoming = client.get(url + f"cycles/{draft['id']}/").data
        assert upcoming["start"] == date(2026, 11, 17)
        copied = upcoming["plans"][0]
        assert copied["name"] == plan["name"] and copied["task_id"] != plan["task_id"]
        target_id = copied["targets"][0]["id"]
        entry_url = url + f"targets/{target_id}/entries/2026-11-17/"
        assert client.put(entry_url, {"items": [{}]}, format="json").status_code == 400
        assert client.post(url + f"plans/{copied['id']}/complete/", {}, format="json").status_code == 404
        assert client.post(url + f"cycles/{draft['id']}/review/", {}, format="json").status_code == 400

        reason = post(client, "reasons/", {"label": "Continue next week"})
        review = post(client, path + f"cycles/{current['id']}/review/", {
            "decisions": {str(plan["id"]): {"action": "carry", "reason_id": reason["id"]}},
        })
        assert review["next"]["id"] == draft["id"]
        assert client.get(url + f"cycles/{later['id']}/").data["status"] == "draft"
        assert client.put(entry_url, {"items": [{}]}, format="json").status_code == 200
        assert client.patch(url + f"cycles/{current['id']}/", {"end": "2026-11-17"}, format="json").status_code == 400


def test_cycle_dates_keep_existing_daily_entries(account):
    _, client = account
    with patch("planner.api.today_for", return_value=date(2026, 11, 15)):
        path = make_project(client)
        plan = post(client, path + "tasks/", {
            "name": "Practice", "goals": [{"name": "Solve exercises", "kind": "count", "quantity": 2}],
        })
        target_id = plan["targets"][0]["id"]
        url = f"/api/v1/{path}"
        assert client.put(url + f"targets/{target_id}/entries/2026-11-15/",
                          {"items": [{}]}, format="json").status_code == 200
        response = client.patch(url, {"cycle": {"end": "2026-11-14"}}, format="json")
        assert response.status_code == 400
        assert client.get(url).data["cycles"][0]["end"] == date(2026, 11, 15)
