# Generated manually.

from django.db import migrations, models


def recompute_bmi_class(apps, schema_editor):
    """The BMI classification changed from 4 tiers to the full WHO obesity
    grading table (6 tiers, splitting obesity into Class I/II/III).
    Recompute bmi_class for all existing Assessment rows so stored labels
    match the new table instead of a stale pre-migration label."""
    Assessment = apps.get_model("clinic", "Assessment")

    def bmi_class(bmi):
        if not bmi:
            return ""
        if bmi < 18.5:
            return "نقص الوزن"
        elif bmi < 25:
            return "وزن طبيعي"
        elif bmi < 30:
            return "زيادة الوزن"
        elif bmi < 35:
            return "السمنة – الدرجة الأولى"
        elif bmi < 40:
            return "السمنة – الدرجة الثانية"
        return "السمنة – الدرجة الثالثة"

    for a in Assessment.objects.all():
        new_class = bmi_class(a.bmi)
        if a.bmi_class != new_class:
            a.bmi_class = new_class
            a.save(update_fields=["bmi_class"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0006_recompute_activity_level'),
    ]

    operations = [
        migrations.AlterField(
            model_name='assessment',
            name='bmi_class',
            field=models.CharField(blank=True, default='', max_length=40),
        ),
        migrations.RunPython(recompute_bmi_class, noop_reverse),
    ]
