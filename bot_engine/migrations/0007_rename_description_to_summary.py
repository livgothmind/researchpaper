from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('bot_engine', '0006_alter_activitylog_options_and_more'),
    ]

    operations = [
        migrations.RenameField(
            model_name='researchposter',
            old_name='description',
            new_name='summary',
        ),
    ]
