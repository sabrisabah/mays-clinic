from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0011_remove_insulin_resistance_value'),
    ]

    operations = [
        migrations.AddField(
            model_name='followuprecord',
            name='followup_purpose',
            field=models.JSONField(default=list, blank=True),
        ),
    ]
