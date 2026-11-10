from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("planner", "0006_onboarding_templates")]
    operations = [
        migrations.CreateModel(name="HelpArticle", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("title", models.CharField(max_length=120)),
            ("body", models.TextField()),
            ("published", models.BooleanField(default=False)),
        ]),
    ]
