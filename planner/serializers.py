from decimal import Decimal

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rest_framework import serializers as s

from .models import Profile, Reason, UNITS


class ProfileInput(s.ModelSerializer):
    currency = s.RegexField(r"^[A-Za-z]{3}$")
    interval = s.IntegerField(min_value=1, max_value=365)
    age = s.IntegerField(min_value=1, max_value=125, allow_null=True, required=False)

    class Meta:
        model = Profile
        fields = ("name", "age", "qualification", "specialization", "timezone", "currency",
                  "interval", "interval_unit", "reminder_time")

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise s.ValidationError("Use an IANA timezone such as Europe/Budapest.")
        return value

    def validate_currency(self, value):
        return value.upper()


class ReasonInput(s.ModelSerializer):
    class Meta:
        model = Reason
        fields = ("id", "label", "active")


class ProjectInput(s.Serializer):
    name = s.CharField(max_length=160)
    start = s.DateField()
    planned_end = s.DateField(required=False, allow_null=True)
    first_review = s.DateField(required=False)
    interval = s.IntegerField(min_value=1, max_value=365, required=False)
    interval_unit = s.ChoiceField(choices=UNITS, required=False)
    mode = s.ChoiceField(choices=("standard", "hourly", "monthly"), required=False)
    currency = s.RegexField(r"^[A-Za-z]{3}$", required=False)


class CycleDatesInput(s.Serializer):
    start = s.DateField(required=False)
    end = s.DateField(required=False)


class CycleDraftInput(s.Serializer):
    source_plan_ids = s.ListField(child=s.IntegerField(min_value=1), default=list, max_length=50)


class ProjectEdit(s.Serializer):
    cycle = CycleDatesInput(required=False)
    name = s.CharField(max_length=160, required=False)
    planned_end = s.DateField(required=False, allow_null=True)


class FieldInput(s.Serializer):
    key = s.RegexField(r"^[a-z][a-z0-9_]{0,29}$")
    label = s.CharField(max_length=80)
    type = s.ChoiceField(choices=("text", "number", "date", "url", "choice"))
    required = s.BooleanField(default=False)
    choices = s.ListField(child=s.CharField(max_length=100), default=list, max_length=30)

    def validate(self, attrs):
        attrs.setdefault("required", False)
        attrs.setdefault("choices", [])
        if attrs["type"] == "choice" and not attrs["choices"]:
            raise s.ValidationError("A choice field needs at least one option.")
        return attrs


class KindInput(s.Serializer):
    name = s.CharField(max_length=120)
    task_fields = FieldInput(many=True, required=False, max_length=25)
    entry_fields = FieldInput(many=True, required=False, max_length=25)

    def validate(self, attrs):
        for key in ("task_fields", "entry_fields"):
            names = [field["key"] for field in attrs.get(key, [])]
            if len(names) != len(set(names)):
                raise s.ValidationError({key: "Field keys must be unique."})
        return attrs


def target_quantity(minimum):
    return s.DecimalField(max_digits=9, decimal_places=2, min_value=Decimal(minimum),
                          max_value=Decimal("1000000"))


def validate_quantity(kind, quantity):
    if kind == "done" and quantity not in (0, 1):
        raise s.ValidationError({"quantity": "A Done goal has a target of one."})
    if kind == "count" and quantity != quantity.to_integral_value():
        raise s.ValidationError({"quantity": "A Count goal needs a whole number."})


class GoalInput(s.Serializer):
    name = s.CharField(max_length=160)
    metric = s.CharField(max_length=100, required=False)
    kind = s.ChoiceField(choices=("count", "done", "hours", "net_income"))
    quantity = target_quantity("0.01")

    def validate(self, attrs):
        kind = attrs["kind"]
        validate_quantity(kind, attrs["quantity"])
        default_metric = {"hours": "hours worked", "net_income": "net income"}.get(kind, attrs["name"][:100])
        attrs["metric"] = attrs.get("metric", default_metric).casefold()
        return attrs


PRIORITIES = ("low", "normal", "high")


class TaskInput(s.Serializer):
    kind_id = s.IntegerField(min_value=1, required=False)
    name = s.CharField(max_length=160)
    priority = s.ChoiceField(choices=PRIORITIES, default="normal")
    description = s.CharField(max_length=2000, default="", allow_blank=True)
    reference_url = s.URLField(max_length=2048, default="", allow_blank=True)
    values = s.DictField(default=dict)
    goals = GoalInput(many=True, default=list, max_length=20)


class ProjectSetupInput(ProjectInput):
    tasks = TaskInput(many=True, default=list, max_length=50)


class PlanInput(s.Serializer):
    name = s.CharField(max_length=160, required=False)
    description = s.CharField(max_length=2000, allow_blank=True, required=False)
    reference_url = s.URLField(max_length=2048, allow_blank=True, required=False)
    priority = s.ChoiceField(choices=PRIORITIES, required=False)
    targets = s.DictField(child=target_quantity("0"), required=False)


class HoursGoalInput(s.Serializer):
    quantity = target_quantity("0.01")


class EntryInput(s.Serializer):
    items = s.ListField(child=s.DictField(), max_length=500)
    reason = s.CharField(max_length=500, required=False)


class DecisionInput(s.Serializer):
    action = s.ChoiceField(choices=("complete", "carry", "partial", "discard"))
    reason_id = s.IntegerField(min_value=1, required=False)
    note = s.CharField(max_length=500, allow_blank=True, default="")


class ReviewInput(s.Serializer):
    decisions = s.DictField(child=DecisionInput(), default=dict)


class TermsInput(s.Serializer):
    effective_on = s.DateField()
    rate = s.DecimalField(max_digits=16, decimal_places=2, min_value=0)
    tax_pct = s.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100)


class HoursInput(s.Serializer):
    work_day = s.DateField()
    task_id = s.IntegerField(min_value=1, required=False)
    hours = s.DecimalField(max_digits=7, decimal_places=2, min_value=Decimal("0.01"))
    location = s.CharField(max_length=160, allow_blank=True, default="")


class MonthInput(s.Serializer):
    month = s.DateField()
    gross = s.DecimalField(max_digits=16, decimal_places=2, min_value=0)


class PaymentInput(s.Serializer):
    received_on = s.DateField()
    amount = s.DecimalField(max_digits=16, decimal_places=2, min_value=Decimal("0.01"))
