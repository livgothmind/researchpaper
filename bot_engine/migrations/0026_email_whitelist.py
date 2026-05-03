from django.conf import settings as django_settings
from django.db import migrations, models


def seed_admin_whitelist(apps, schema_editor):
    User = apps.get_model("auth", "User")
    EmailWhitelist = apps.get_model("bot_engine", "EmailWhitelist")

    patterns = [p.strip().lower() for p in
                getattr(django_settings, "BLACKLIST_EMAIL_PATTERNS", []) or []]
    if not patterns:
        return

    for user in User.objects.filter(is_active=True):
        if not (user.is_staff or user.is_superuser):
            continue
        email = (user.email or "").strip().lower()
        if not email:
            continue
        if not any(p and p in email for p in patterns):
            continue
        if EmailWhitelist.objects.filter(email=email).exists():
            continue
        EmailWhitelist.objects.create(
            email=email,
            first_name=user.first_name or "",
            last_name=user.last_name or "",
            created_by=None,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("bot_engine", "0025_research_interest"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailWhitelist",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(max_length=254, unique=True)),
                ("first_name", models.CharField(blank=True, default="", max_length=150)),
                ("last_name", models.CharField(blank=True, default="", max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("groups", models.ManyToManyField(blank=True, related_name="whitelist_entries", to="bot_engine.researchgroup")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name="whitelist_entries_created", to=django_settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["email"]},
        ),
        migrations.RunPython(seed_admin_whitelist, migrations.RunPython.noop),
    ]
