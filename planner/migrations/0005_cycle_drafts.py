from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("planner", "0004_net_income_goal")]

    operations = [
        migrations.AddField(
            model_name="cycle", name="is_draft", field=models.BooleanField(default=False),
        ),
        migrations.RemoveConstraint(model_name="cycle", name="one_open_cycle"),
        migrations.AddConstraint(
            model_name="cycle",
            constraint=models.UniqueConstraint(
                fields=["project"], condition=models.Q(closed_at__isnull=True, is_draft=False),
                name="one_open_cycle",
            ),
        ),
    ]
