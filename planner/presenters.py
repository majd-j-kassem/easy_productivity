from .rules import count_items, paid, today_for


def fields_of(instance, names):
    return {name: getattr(instance, name) for name in names.split()}


def project_data(project):
    return fields_of(project, "id name start planned_end first_review interval interval_unit mode currency status work_ended closed_on")


def kind_data(kind):
    return fields_of(kind, "id name task_fields entry_fields")


def cycle_data(cycle, today):
    return fields_of(cycle, "id sequence start end closed_at") | {
        "status": "closed" if cycle.closed_at else "review" if cycle.end <= today else "open",
    }


def target_data(target):
    goal = target.goal
    targets = list(goal.targets.select_related("goal", "plan__cycle").filter(
        plan__cycle__sequence__lte=target.plan.cycle.sequence
    ).order_by("plan__cycle__sequence"))
    actuals = [count_items(item) for item in targets]
    previous = sum(actuals[:-1])
    current = actuals[-1]
    first_quantity = targets[0].quantity
    if goal.kind == "done":
        previous = min(1, previous)
    return fields_of(target, "id quantity") | {
        "goal_id": goal.pk, "name": goal.name, "metric": goal.metric, "kind": goal.kind,
        "actual": current, "previous_actual": previous, "cumulative": previous + current,
        "original_quantity": first_quantity, "remaining_original": max(0, first_quantity-previous-current),
    }


def plan_data(plan):
    task = plan.task
    return fields_of(plan, "id priority decision reason note") | {
        "task_id": task.pk, "name": task.name, "status": task.status,
        "kind": task.kind.name, "values": task.values, "entry_fields": task.entry_fields,
        "targets": [target_data(target) for target in plan.targets.select_related("goal", "plan__cycle")],
    }


def receivable_data(item):
    received = paid(item)
    remainder = item.net-received
    return fields_of(item, "id work_day month task_id hours location gross tax net") | {
        "rate": item.terms.rate, "tax_pct": item.terms.tax_pct,
        "received": received, "remaining": remainder,
        "status": "paid" if not remainder else "partial" if received else "due",
        "payments": [fields_of(payment, "id received_on amount") for payment in item.payments.all()],
    }
