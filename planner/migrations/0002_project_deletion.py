from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("planner", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="task", name="kind",
            field=models.ForeignKey("planner.taskkind", on_delete=models.RESTRICT),
        ),
        migrations.AlterField(
            model_name="dailyentry", name="target",
            field=models.ForeignKey("planner.target", on_delete=models.CASCADE, related_name="entries"),
        ),
        migrations.AlterField(
            model_name="correction", name="entry",
            field=models.ForeignKey("planner.dailyentry", on_delete=models.CASCADE, related_name="corrections"),
        ),
        migrations.AlterField(
            model_name="receivable", name="terms",
            field=models.ForeignKey("planner.payterms", on_delete=models.RESTRICT),
        ),
        migrations.AlterField(
            model_name="receivable", name="task",
            field=models.ForeignKey("planner.task", on_delete=models.RESTRICT, null=True),
        ),
        migrations.AlterField(
            model_name="payment", name="receivable",
            field=models.ForeignKey("planner.receivable", on_delete=models.CASCADE, related_name="payments"),
        ),
    ]
