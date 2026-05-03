from django.conf import settings as django_settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bot_engine", "0028_drop_email_whitelist_and_alter_research_group"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="PendingAssignmentDismissal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("dismissed_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.OneToOneField(
                    on_delete=models.deletion.CASCADE,
                    related_name="pending_dismissal",
                    to=django_settings.AUTH_USER_MODEL,
                )),
                ("dismissed_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=models.deletion.SET_NULL,
                    related_name="+",
                    to=django_settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ["-dismissed_at"]},
        ),
    ]
