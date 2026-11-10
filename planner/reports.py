from collections import defaultdict
from io import BytesIO
from xml.sax.saxutils import escape

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .api import owned
from .presenters import receivable_data
from .rules import target_actual


def report_data(project):
    summary = defaultdict(lambda: {"planned": 0, "actual": 0})
    goals, cycles, task_rows = [], [], []
    tasks = project.tasks.prefetch_related("goals__targets__entries", "goals__targets__plan__cycle")
    for task in tasks.order_by("id"):
        task_rows.append({"task_id": task.pk, "task": task.name, "status": task.status})
        for goal in task.goals.all():
            targets = sorted(goal.targets.all(), key=lambda target: target.plan.cycle.sequence)
            actuals = [target_actual(target) for target in targets]
            actual = min(sum(actuals), 1) if goal.kind == "done" else sum(actuals)
            original = targets[0].quantity
            reason = task.closed_reason if actual < original else ""
            goals.append({"task_id": task.pk, "goal_id": goal.pk, "task": task.name,
                          "goal": goal.name, "metric": goal.metric, "measurement": goal.kind,
                          "planned": original, "actual": actual, "gap": max(0, original-actual),
                          "status": task.status, "reason": reason})
            group = summary[(goal.metric, goal.kind)]
            group["planned"] += original
            group["actual"] += actual
            for target, result in zip(targets, actuals):
                plan = target.plan
                cycle = plan.cycle
                cycles.append({"cycle_id": cycle.pk, "cycle": cycle.sequence, "start": cycle.start,
                               "end": cycle.end, "task_id": task.pk, "goal_id": goal.pk, "task": task.name,
                               "goal": goal.name, "metric": goal.metric, "measurement": goal.kind,
                               "planned": target.quantity, "actual": result,
                               "gap": max(0, target.quantity-result), "decision": plan.decision,
                               "reason_id": plan.reason_ref_id, "reason": plan.reason, "note": plan.note})
    income = [receivable_data(item) for item in project.receivables.select_related("terms").order_by("work_day")]
    return {"project": project.name, "project_id": project.pk, "closed_on": project.closed_on,
            "currency": project.currency,
            "metrics": [{"metric": key[0], "measurement": key[1]} | values
                        for key, values in sorted(summary.items())],
            "tasks": task_rows, "goals": goals, "cycles": cycles, "income": income}


def xlsx_report(data):
    workbook = Workbook()
    workbook.remove(workbook.active)
    finance = [{key: value for key, value in row.items() if key != "payments"} for row in data["income"]]
    payments = [{"receivable_id": row["id"]} | payment
                for row in data["income"] for payment in row["payments"]]
    sheets = {"Project": [{key: data[key] for key in ("project_id", "project", "closed_on", "currency")}],
              "Tasks": data["tasks"], "Metrics": data["metrics"], "Goals": data["goals"], "Cycles": data["cycles"],
              "Receivables": finance, "Payments": payments}
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        if not rows:
            continue
        keys = list(rows[0])
        if name != "Project":
            keys = ["project_id"] + keys
        sheet.append(keys)
        for row in rows:
            values = [row.get(key, data["project_id"] if key == "project_id" else None) for key in keys]
            sheet.append([ILLEGAL_CHARACTERS_RE.sub("", value) if isinstance(value, str) else value
                          for value in values])
            for cell in sheet[sheet.max_row]:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        for cell in sheet[1]:
            cell.fill = PatternFill("solid", fgColor="153B40")
            cell.font = Font(bold=True, color="FFFFFF")
        for index, key in enumerate(keys, 1):
            sheet.column_dimensions[get_column_letter(index)].width = min(
                46, max(13, len(key) + 2, *(len(str(row.get(key) or "")) + 2 for row in rows))
            )
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
    result = BytesIO()
    workbook.save(result)
    return result.getvalue()


def pdf_report(data):
    result = BytesIO()
    styles = getSampleStyleSheet()

    def paragraph(value, style="BodyText"):
        return Paragraph(escape(str(value if value is not None else "")), styles[style])

    content = [paragraph("Project performance report", "Title"),
               paragraph(data["project"], "Heading2"),
               paragraph(f"Closed on {data['closed_on']} · Project {data['project_id']}"),
               Spacer(1, 12)]

    def add_table(title, header, rows, widths):
        if not rows:
            return
        content.append(paragraph(title, "Heading2"))
        table = Table([[paragraph(label) for label in header]]
                      + [[paragraph(value) for value in row] for row in rows],
                      colWidths=widths, repeatRows=1, splitInRow=1)
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDEDEA")),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#497975")),
                                   ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                                    [colors.white, colors.HexColor("#F2F6F5")])]))
        content.extend([table, Spacer(1, 12)])

    add_table("Tasks", ["Task", "Status"],
              [(row["task"], row["status"]) for row in data["tasks"]], [345, 105])
    add_table("Project totals", ["Metric", "Initial target", "Actual"],
              [(row["metric"], row["planned"], row["actual"]) for row in data["metrics"]],
              [270, 90, 90])
    add_table("Goals", ["Task / goal", "Planned", "Actual", "Gap", "Status / reason"],
              [(f"{row['task']} / {row['goal']}", row["planned"], row["actual"], row["gap"],
                f"{row['status']} {row['reason']}") for row in data["goals"]], [170, 60, 48, 35, 137])
    add_table("Cycle history", ["Cycle", "Goal", "Planned", "Actual", "Decision / reason"],
              [(row["cycle"], row["goal"], row["planned"], row["actual"],
                f"{row['decision']} {row['reason']}") for row in data["cycles"]], [45, 160, 60, 48, 137])
    add_table(f"Receivables ({data['currency']})", ["Work date", "Gross", "Tax", "Net", "Received"],
              [(row["work_day"], row["gross"], row["tax"], row["net"], row["received"])
               for row in data["income"]], [100, 90, 80, 90, 90])
    SimpleDocTemplate(result).build(content)
    return result.getvalue()


@api_view(["GET"])
def report(request, pk, file_type=None):
    project = owned(request, pk)
    if project.status != "closed":
        raise ValidationError("The final report is available after project closure.")
    data = report_data(project)
    if file_type == "xlsx":
        response = HttpResponse(xlsx_report(data), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    elif file_type == "pdf":
        response = HttpResponse(pdf_report(data), content_type="application/pdf")
    else:
        return Response(data)
    response["Content-Disposition"] = f'attachment; filename="project-{project.pk}.{file_type}"'
    return response
