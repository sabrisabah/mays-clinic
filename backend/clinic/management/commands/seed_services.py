"""Seeds the revenue module's service directory (دليل الخدمات) with the
clinic's initial price list, per the revenue system spec. All of this is
meant as a starting point only — every service, price, category and
Mounjaro dose variant is editable from the doctor's service-catalog screen
afterward (see FoodListCreateView-style admin UI pattern already used for
Food).

Safe to re-run: uses get_or_create keyed on name (services) / (service,
name) (variants), so it never overwrites a price the doctor has already
edited — only fills in ones that are missing.

Usage: python manage.py seed_services
"""
from django.core.management.base import BaseCommand
from clinic.models import Service, ServiceVariant

# (name, category, price, pricing_note)
SERVICES = [
    ("كشفية الطبيب", "كشفية ومتابعة", 25000, "تستوفى لمرة واحدة، والمتابعة مجانية"),
    ("استشارة أونلاين", "استشارات", 50000, "لكل استشارة أونلاين"),
    ("فحص جهاز InBody", "فحوصات", 15000, "لكل فحص"),
    ("إعداد النظام الغذائي", "أنظمة غذائية", 25000, "لكل نظام غذائي"),
    ("جلسة تذويب الدهون", "جلسات", 150000, "لكل إبرة؛ الكمية قابلة للتغيير"),
    ("جلسة مغذ وريدي", "جلسات", 250000, "لكل جلسة"),
    ("جلسة مضاد الشيخوخة", "جلسات", 300000, "لكل جلسة"),
    ("جلسة الحديد", "جلسات", 100000, "لكل جلسة"),
    ("جرعة أوزمبك", "أدوية", 50000, "لكل جرعة"),
]

# Priced entirely via variants — one row per dose strength.
MOUNJARO_SERVICE = ("جرعات مونجارو", "أدوية", "السعر حسب الجرعة (انظر أدناه)")
MOUNJARO_DOSES = [
    ("2.5 mg", 150000), ("5 mg", 175000), ("7.5 mg", 200000),
    ("10 mg", 225000), ("12.5 mg", 250000), ("15 mg", 275000),
]


class Command(BaseCommand):
    help = "Seeds the revenue module's service directory with the clinic's initial price list."

    def handle(self, *args, **options):
        created, skipped = 0, 0
        for name, category, price, note in SERVICES:
            _, was_created = Service.objects.get_or_create(
                name=name,
                defaults={"category": category, "price": price, "pricing_note": note},
            )
            created += was_created
            skipped += not was_created

        mounjaro_name, mounjaro_category, mounjaro_note = MOUNJARO_SERVICE
        mounjaro_service, mounjaro_was_created = Service.objects.get_or_create(
            name=mounjaro_name,
            defaults={"category": mounjaro_category, "pricing_note": mounjaro_note, "has_variants": True},
        )
        created += mounjaro_was_created
        skipped += not mounjaro_was_created

        variants_created, variants_skipped = 0, 0
        for i, (dose_name, dose_price) in enumerate(MOUNJARO_DOSES):
            _, was_created = ServiceVariant.objects.get_or_create(
                service=mounjaro_service, name=dose_name,
                defaults={"price": dose_price, "order": i},
            )
            variants_created += was_created
            variants_skipped += not was_created

        self.stdout.write(self.style.SUCCESS(
            f"الخدمات: {created} جديدة من أصل {len(SERVICES) + 1} — "
            f"جرعات مونجارو: {variants_created} جديدة من أصل {len(MOUNJARO_DOSES)}"
        ))
