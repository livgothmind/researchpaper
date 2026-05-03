from django.db import migrations, models


def split_research_interests(apps, schema_editor):
    ResearchGroup = apps.get_model("bot_engine", "ResearchGroup")
    ResearchInterest = apps.get_model("bot_engine", "ResearchInterest")
    for g in ResearchGroup.objects.all():
        text = (g.research_interests or "").strip()
        if not text:
            continue
        lines = [ln.strip() for ln in text.splitlines()]
        lines = [ln for ln in lines if ln]
        if not lines:
            ResearchInterest.objects.create(group=g, text=text)
        else:
            for ln in lines:
                ResearchInterest.objects.create(group=g, text=ln)


def join_research_interests(apps, schema_editor):
    ResearchGroup = apps.get_model("bot_engine", "ResearchGroup")
    for g in ResearchGroup.objects.all():
        joined = "\n".join(i.text for i in g.interests.all() if i.text)
        g.research_interests = joined
        g.save(update_fields=["research_interests"])


class Migration(migrations.Migration):

    dependencies = [
        ("bot_engine", "0024_rename_bot_engine__platfor_e2b4d3_idx_bot_engine__platfor_1a4655_idx"),
    ]

    operations = [
        migrations.CreateModel(
            name="ResearchInterest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("text", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("group", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="interests", to="bot_engine.researchgroup")),
            ],
            options={"ordering": ["pk"]},
        ),
        migrations.RunPython(split_research_interests, join_research_interests),
        migrations.RemoveField(
            model_name="researchgroup",
            name="research_interests",
        ),
    ]
