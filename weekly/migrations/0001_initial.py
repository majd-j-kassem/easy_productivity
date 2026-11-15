from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [("planner", "0005_cycle_drafts")]
    operations = [
        migrations.CreateModel(name="AgendaItem", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="planner.project")),
            ("kind", models.CharField(choices=[("deadline", "Deadline"), ("shift", "Shift")], max_length=8)),
            ("name", models.CharField(max_length=160)),
            ("day", models.DateField()),
            ("ledger_entry", models.OneToOneField(blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL, to="planner.receivable")),
            ("hours", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
        ]),
    ]
