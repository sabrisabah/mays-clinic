from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0014_assessment_appointment_booked_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='profile_photo',
            field=models.ImageField(blank=True, null=True, upload_to='profile_photos/'),
        ),
    ]
