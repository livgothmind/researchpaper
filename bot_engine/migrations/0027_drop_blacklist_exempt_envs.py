import os

from django.db import migrations


def migrate_exempt_emails_to_whitelist(apps, schema_editor):
    EmailWhitelist = apps.get_model("bot_engine", "EmailWhitelist")

    raw_emails = os.environ.get("BLACKLIST_EXEMPT_EMAILS", "")
    emails = [e.strip().lower() for e in raw_emails.split(",") if e.strip()]
    for email in emails:
        EmailWhitelist.objects.get_or_create(email=email)

    raw_usernames = os.environ.get("BLACKLIST_EXEMPT_USERNAMES", "")
    if any(u.strip() for u in raw_usernames.split(",")):
        raise RuntimeError(
            "BLACKLIST_EXEMPT_USERNAMES is set but no longer supported. "
            "Add the corresponding emails to EmailWhitelist via the admin "
            "UI, unset the env var, and re-run migrations."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("bot_engine", "0026_email_whitelist"),
    ]

    operations = [
        migrations.RunPython(
            migrate_exempt_emails_to_whitelist,
            migrations.RunPython.noop,
        ),
    ]
