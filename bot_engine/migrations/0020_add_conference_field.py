from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bot_engine", "0019_add_research_groups"),
    ]

    operations = [
        migrations.AddField(
            model_name="researchposter",
            name="conference",
            field=models.CharField(blank=True, db_index=True, default="", max_length=200),
        ),
    ]
