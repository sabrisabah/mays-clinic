# Generated manually — data-only migration.

from django.db import migrations


def recompute_activity_level(apps, schema_editor):
    """The activity-level formula changed from 3 tiers (قليل/متوسط/عالي) to
    4 tiers driven directly by weekly exercise frequency:
    0-1 days = خامل (1.20), 2-3 = نشاط خفيف (1.375),
    4-5 = نشاط منتظم (1.55), 6+ = نشاط عالي (1.725).
    Recompute activity_level for all existing Assessment rows so the stored
    label (and therefore suggested_calories on the next read) matches the
    new formula instead of a stale pre-migration label."""
    Assessment = apps.get_model("clinic", "Assessment")

    def activity_level(days):
        try:
            days = int(days or 0)
        except (TypeError, ValueError):
            days = 0
        if days <= 1:
            return "خامل"
        elif days <= 3:
            return "نشاط خفيف"
        elif days <= 5:
            return "نشاط منتظم"
        return "نشاط عالي"

    for a in Assessment.objects.all():
        new_level = activity_level(a.sport_days_per_week)
        if a.activity_level != new_level:
            a.activity_level = new_level
            a.save(update_fields=["activity_level"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0005_mounjarodose'),
    ]

    operations = [
        migrations.RunPython(recompute_activity_level, noop_reverse),
    ]
