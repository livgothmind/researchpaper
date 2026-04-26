from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("bot_engine", "0022_poster_groups_m2m"),
    ]

    operations = [
        migrations.CreateModel(
            name="BotAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("platform", models.CharField(choices=[("telegram", "Telegram"), ("whatsapp", "WhatsApp")], max_length=20)),
                ("recipient", models.CharField(help_text="chat_id for Telegram, phone for WhatsApp", max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="bot_accounts", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="botaccount",
            constraint=models.UniqueConstraint(fields=("platform", "recipient"), name="unique_bot_account"),
        ),
        migrations.AddIndex(
            model_name="botaccount",
            index=models.Index(fields=["platform", "recipient"], name="bot_engine__platfor_e2b4d3_idx"),
        ),
    ]
