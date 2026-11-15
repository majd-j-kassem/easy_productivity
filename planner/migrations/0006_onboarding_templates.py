from django.db import migrations, models


def seed_templates(apps, schema_editor):
    template = apps.get_model("planner", "OnboardingTemplate")
    template.objects.using(schema_editor.connection.alias).bulk_create([
        template(title="Student", mode="standard", description="Plan study sessions and assignments.",
                 tasks="Review lecture notes\nPrepare the next assignment"),
        template(title="Hourly worker", mode="hourly", description="Plan shifts and track your income.",
                 tasks="Plan this week's shifts\nReview outstanding payments"),
        template(title="Student who works", mode="hourly", description="Plan study deadlines alongside paid work.",
                 tasks="Plan study sessions\nPrepare the next assignment\nPlan this week's shifts"),
    ])


class Migration(migrations.Migration):
    dependencies = [("planner", "0005_cycle_drafts")]
    operations = [
        migrations.CreateModel(name="OnboardingTemplate", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("title", models.CharField(max_length=120)),
            ("description", models.CharField(max_length=240)),
            ("mode", models.CharField(choices=[("standard", "Standard"), ("hourly", "Hourly"),
                                               ("monthly", "Monthly")], max_length=10)),
            ("tasks", models.TextField(help_text="One suggested task per line.")),
            ("enabled", models.BooleanField(default=True)),
        ]),
        migrations.RunPython(seed_templates, migrations.RunPython.noop),
    ]
