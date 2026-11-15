from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("planner", "0003_project_setup")]

    operations = [
        migrations.AlterField(
            model_name="goal", name="kind",
            field=models.CharField(
                max_length=10,
                choices=[("count", "Count"), ("done", "Done"), ("hours", "Hours worked"), ("net_income", "Net income")],
            ),
        ),
    ]
