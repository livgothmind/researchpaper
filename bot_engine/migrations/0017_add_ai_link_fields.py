from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bot_engine', '0016_add_thumbnail'),
    ]

    operations = [
        migrations.AddField(
            model_name='researchposter',
            name='ai_paper_link',
            field=models.URLField(blank=True, max_length=500, null=True),
        ),
        migrations.AddField(
            model_name='researchposter',
            name='ai_github_link',
            field=models.URLField(blank=True, max_length=500, null=True),
        ),
    ]
