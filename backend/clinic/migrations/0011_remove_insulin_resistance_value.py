from django.db import migrations


def migrate_insulin_resistance_into_lab_results(apps, schema_editor):
    FollowUpRecord = apps.get_model("clinic", "FollowUpRecord")
    for record in FollowUpRecord.objects.exclude(insulin_resistance_value=0):
        results = record.lab_results or {}
        # Only fold it in if the doctor hasn't already separately recorded
        # this test in the lab_results dict.
        results.setdefault("مقاومة الانسولين (HOMA-IR)", record.insulin_resistance_value)
        record.lab_results = results
        record.save(update_fields=["lab_results"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0010_secretary_role_and_checkin'),
    ]

    operations = [
        migrations.RunPython(migrate_insulin_resistance_into_lab_results, noop_reverse),
        migrations.RemoveField(
            model_name='followuprecord',
            name='insulin_resistance_value',
        ),
    ]
