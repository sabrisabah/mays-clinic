# Generated manually.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def migrate_treatments_data(apps, schema_editor):
    """Move the old flat `treatments` list into the new split fields:
    مونجارو/أوزمبك/إبر تذويب -> treatment_injections,
    جلسات تكسير الشحوم -> treatment_fat_burning_sessions."""
    FollowUpRecord = apps.get_model("clinic", "FollowUpRecord")
    injection_names = {"مونجارو", "أوزمبك", "إبر تذويب"}
    for record in FollowUpRecord.objects.all():
        old_list = record.treatments or []
        record.treatment_injections = [t for t in old_list if t in injection_names]
        record.treatment_fat_burning_sessions = "جلسات تكسير الشحوم" in old_list
        record.save(update_fields=["treatment_injections", "treatment_fat_burning_sessions"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('clinic', '0008_assessment_is_submitted'),
    ]

    operations = [
        migrations.CreateModel(
            name='LabTestEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateTimeField(auto_now_add=True)),
                ('lab_results', models.JSONField(blank=True, default=dict)),
                ('other_notes', models.TextField(blank=True, default='')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lab_test_entries', to='clinic.patient')),
            ],
            options={
                'ordering': ['date'],
            },
        ),
        migrations.AddField(
            model_name='followuprecord',
            name='treatment_injections',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='followuprecord',
            name='treatment_medications',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='followuprecord',
            name='treatment_fat_burning_sessions',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(migrate_treatments_data, noop_reverse),
        migrations.RemoveField(
            model_name='followuprecord',
            name='treatments',
        ),
    ]
