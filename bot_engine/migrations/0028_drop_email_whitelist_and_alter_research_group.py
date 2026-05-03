from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("bot_engine", "0027_drop_blacklist_exempt_envs"),
    ]

    operations = [
        migrations.DeleteModel(name="EmailWhitelist"),
        migrations.AlterModelOptions(
            name="researchgroup",
            options={
                "ordering": ["name"],
                "verbose_name": "Research group",
                "verbose_name_plural": "Research groups",
            },
        ),
    ]
