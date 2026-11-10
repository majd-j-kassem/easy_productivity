import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("profiles", "0001_initial")]
    operations = [
        migrations.CreateModel(name="ProfileShare", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("profile", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                             to="profiles.professionalprofile")),
            ("token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
            ("visible_fields", models.JSONField(default=list)),
        ]),
    ]
