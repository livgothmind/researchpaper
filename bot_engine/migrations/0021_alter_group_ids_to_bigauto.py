from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bot_engine", "0020_add_conference_field"),
    ]

    operations = [
        migrations.AlterField(
            model_name="researchgroup",
            name="id",
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
        ),
        migrations.AlterField(
            model_name="usergroupmembership",
            name="id",
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
        ),
        migrations.AlterField(
            model_name="postergroupwhyuseful",
            name="id",
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
        ),
    ]
