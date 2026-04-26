from django.db import migrations, models


def backfill_poster_groups(apps, schema_editor):
    """Link each existing poster to the groups its uploader currently belongs to."""
    ResearchPoster = apps.get_model("bot_engine", "ResearchPoster")
    UserGroupMembership = apps.get_model("bot_engine", "UserGroupMembership")

    uploader_groups = {}
    for m in UserGroupMembership.objects.all():
        uploader_groups.setdefault(m.user_id, []).append(m.group_id)

    for poster in ResearchPoster.objects.exclude(uploaded_by__isnull=True):
        group_ids = uploader_groups.get(poster.uploaded_by_id, [])
        if group_ids:
            poster.groups.set(group_ids)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("bot_engine", "0021_alter_group_ids_to_bigauto"),
    ]

    operations = [
        migrations.AddField(
            model_name="researchgroup",
            name="posters",
            field=models.ManyToManyField(blank=True, related_name="groups", to="bot_engine.researchposter"),
        ),
        migrations.RunPython(backfill_poster_groups, noop_reverse),
    ]
