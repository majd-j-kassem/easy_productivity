from django.db import models


class AgendaItem(models.Model):
    KINDS = [("deadline", "Deadline"), ("shift", "Shift")]
    project = models.ForeignKey("planner.Project", on_delete=models.CASCADE)
    kind = models.CharField(max_length=8, choices=KINDS)
    name = models.CharField(max_length=160)
    day = models.DateField()
    hours = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    ledger_entry = models.OneToOneField("planner.Receivable", on_delete=models.SET_NULL, null=True, blank=True)
