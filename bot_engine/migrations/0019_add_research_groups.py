from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("bot_engine", "0018_backfill_ai_link_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="ResearchGroup",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=150, unique=True)),
                ("research_interests", models.TextField(blank=True, default="", help_text="Brief description of the group's research activity")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="UserGroupMembership",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_primary", models.BooleanField(default=False)),
                ("joined_at", models.DateTimeField(auto_now_add=True)),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="bot_engine.researchgroup")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="group_memberships", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-is_primary", "joined_at"],
            },
        ),
        migrations.AddField(
            model_name="researchgroup",
            name="members",
            field=models.ManyToManyField(related_name="research_groups", through="bot_engine.UserGroupMembership", to=settings.AUTH_USER_MODEL),
        ),
        migrations.CreateModel(
            name="PosterGroupWhyUseful",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("why_useful", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="poster_why_useful_entries", to="bot_engine.researchgroup")),
                ("poster", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="group_why_useful_entries", to="bot_engine.researchposter")),
            ],
        ),
        migrations.AddConstraint(
            model_name="usergroupmembership",
            constraint=models.UniqueConstraint(fields=("user", "group"), name="unique_user_group_membership"),
        ),
        migrations.AddConstraint(
            model_name="postergroupwhyuseful",
            constraint=models.UniqueConstraint(fields=("poster", "group"), name="unique_poster_group_why_useful"),
        ),
    ]
