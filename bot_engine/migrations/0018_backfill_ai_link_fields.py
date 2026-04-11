from django.db import migrations
from django.db.models import F


def backfill_ai_links(apps, schema_editor):
    ResearchPoster = apps.get_model('bot_engine', 'ResearchPoster')
    ResearchPoster.objects.filter(ai_paper_link__isnull=True).update(ai_paper_link=F('paper_link'))
    ResearchPoster.objects.filter(ai_github_link__isnull=True).update(ai_github_link=F('github_link'))


class Migration(migrations.Migration):

    dependencies = [
        ('bot_engine', '0017_add_ai_link_fields'),
    ]

    operations = [
        migrations.RunPython(backfill_ai_links, migrations.RunPython.noop),
    ]
