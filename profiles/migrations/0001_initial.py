from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name="ProfessionalProfile", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("owner", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ("name", models.CharField(blank=True, max_length=120)),
            ("bio", models.TextField(blank=True)),
            ("skills", models.CharField(blank=True, max_length=500, help_text="Separate skills with commas.")),
            ("website", models.URLField(blank=True)),
            ("github", models.URLField(blank=True)),
            ("linkedin", models.URLField(blank=True)),
        ]),
    ]
