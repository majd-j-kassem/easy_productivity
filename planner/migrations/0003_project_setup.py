from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("planner", "0002_project_deletion")]

    operations = [
        migrations.AlterField(
            model_name="task", name="kind",
            field=models.ForeignKey("planner.taskkind", on_delete=models.RESTRICT, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="task", name="description", field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="task", name="reference_url", field=models.URLField(max_length=2048, blank=True),
        ),
        migrations.AlterField(
            model_name="goal", name="kind",
            field=models.CharField(
                max_length=5, choices=[("count", "Count"), ("done", "Done"), ("hours", "Hours worked")],
            ),
        ),
        migrations.AlterField(
            model_name="target", name="quantity",
            field=models.DecimalField(max_digits=9, decimal_places=2),
        ),
        migrations.AddConstraint(
            model_name="target",
            constraint=models.CheckConstraint(
                condition=models.Q(quantity__gte=0), name="nonnegative_target_quantity",
            ),
        ),
    ]
