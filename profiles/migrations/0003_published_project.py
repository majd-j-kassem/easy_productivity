from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("profiles", "0002_profile_share"), ("planner", "0005_cycle_drafts")]
    operations = [
        migrations.CreateModel(name="PublishedProject", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                          related_name="published_projects", to="profiles.professionalprofile")),
            ("project", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to="planner.project")),
            ("snapshot", models.JSONField()),
        ]),
    ]
