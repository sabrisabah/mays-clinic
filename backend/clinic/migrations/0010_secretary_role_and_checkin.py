from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0009_labtestentry_and_treatment_split'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[('patient', 'patient'), ('doctor', 'doctor'), ('secretary', 'secretary')],
                default='patient', max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='assessment',
            name='checked_in',
            field=models.BooleanField(default=False),
        ),
    ]
