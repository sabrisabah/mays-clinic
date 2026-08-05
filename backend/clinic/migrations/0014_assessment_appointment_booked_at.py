from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0013_assessment_appointment_booked'),
    ]

    operations = [
        migrations.AddField(
            model_name='assessment',
            name='appointment_booked_at',
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]
