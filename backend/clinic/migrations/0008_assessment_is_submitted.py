# Generated manually.

from django.db import migrations, models


def mark_existing_filled_assessments_submitted(apps, schema_editor):
    """Assessments that already have real data (weight entered) predate this
    lock feature — treat them as already-submitted so behavior stays
    consistent going forward. Blank/unfilled assessments (new patients who
    haven't filled the form yet) stay unlocked."""
    Assessment = apps.get_model("clinic", "Assessment")
    Assessment.objects.filter(weight__gt=0).update(is_submitted=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0007_bmi_class_who_grading'),
    ]

    operations = [
        migrations.AddField(
            model_name='assessment',
            name='is_submitted',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(mark_existing_filled_assessments_submitted, noop_reverse),
    ]
