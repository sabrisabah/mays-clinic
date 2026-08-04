from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0012_followuprecord_followup_purpose'),
    ]

    operations = [
        migrations.AddField(
            model_name='assessment',
            name='appointment_booked',
            field=models.BooleanField(default=False),
        ),
    ]
