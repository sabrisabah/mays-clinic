"""One-time (but safe to re-run) backfill for the current_weight permanent
lock introduced in commit 5c9ddf7.

Before that change, "الوزن الحالي" in the treatment-goal section only ever
displayed a value once a doctor typed a weight — the field auto-followed
"الوزن" (anthropometrics) live in the browser, but nothing was persisted
to Assessment.current_weight until someone actually pressed save. So many
existing patients show a current_weight value on screen (mirroring their
last recorded weight) while the DB field is still 0 — meaning the new lock
never engages for them, since the lock is keyed on current_weight being
non-zero in the database.

This backfill closes that gap: any assessment that already has a real
weight recorded but never had current_weight explicitly saved gets its
current_weight set to that weight now, locking it immediately at today's
value — exactly like a first save would have, per the doctor's request
that existing patients lock "from now, at their current value" rather than
waiting for a future save that may never happen.

Idempotent: only touches rows where current_weight=0 and weight!=0; after
the first run there are none left, so re-running (e.g. on every deploy,
alongside the other seed_* commands) is a no-op.

Usage: python manage.py backfill_current_weight
"""
from django.core.management.base import BaseCommand
from clinic.models import Assessment


class Command(BaseCommand):
    help = "Locks الوزن الحالي at the existing weight for assessments that never had it explicitly saved."

    def handle(self, *args, **options):
        qs = Assessment.objects.filter(current_weight=0).exclude(weight=0)
        count = qs.count()
        for assessment in qs:
            assessment.current_weight = assessment.weight
            assessment.save(update_fields=["current_weight"])
        self.stdout.write(f"الوزن الحالي: تم تثبيته الآن لـ {count} استمارة كانت تعرضه بدون حفظ فعلي مسبق")
