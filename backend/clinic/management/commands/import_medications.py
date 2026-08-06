"""Imports the clinic's medications/supplements reference spreadsheet into
the MedicationCategory / Medication / MedicationDose tables that power the
'🔹 العلاج أو الوصفة الطبية' picker.

The source sheet (backend/clinic/seed_data/Clinic_Nutrition_Medications_and_Supplements.xlsx)
is not a clean normalized table — it's five loosely-formatted sections, each
with its own column layout:

  1) أدوية السمنة ومقاومة الإنسولين   col0=الفئة (class)      col1=الدواء (name)
  2) التركيبات الثنائية               col0=المستحضر (brand)   col1=التركيبة (generic combo)
  3) التركيبات الثلاثية               col0=المستحضر (brand)   col1=التركيبة (generic combo)
  4) الأدوية المساعدة                 col0=الاستخدام (use)    col1=الدواء (name)
  5) المكملات الغذائية               col0=المكمل (name)      col1=المستحضر (form: tab/amp/cap)

In every section, columns from index 2 onward are repeated "الجرعة" (dose)
cells — anywhere from 0 to 6 filled in per row, mixing plain numbers (5, 10),
strings with an embedded unit ("500 mg", "50001 IU"), combo-drug ratios
("50/500"), or a bare form word ("tab", "sachets") for rows with no real
numeric dose. This command normalizes all of that into individual
MedicationDose rows, and is safe to re-run (get_or_create throughout).

Usage: python manage.py import_medications [--file /path/to/sheet.xlsx]
"""
import os
import re
import openpyxl
from django.core.management.base import BaseCommand
from clinic.models import MedicationCategory, Medication, MedicationDose

DEFAULT_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data", "Clinic_Nutrition_Medications_and_Supplements.xlsx")

# section title (as it appears verbatim in column A) -> parsing config
SECTIONS = {
    "أدوية السمنة ومقاومة الإنسولين": {"kind": "classified", "type": MedicationCategory.MEDICATION},
    "التركيبات الثنائية": {"kind": "combo", "type": MedicationCategory.MEDICATION},
    "التركيبات الثلاثية": {"kind": "combo", "type": MedicationCategory.MEDICATION},
    "الأدوية المساعدة": {"kind": "classified", "type": MedicationCategory.MEDICATION},
    "المكملات الغذائية": {"kind": "supplement", "type": MedicationCategory.SUPPLEMENT},
}

DOSE_CELL_RE = re.compile(r"^([\d./]+)\s*([A-Za-z؀-ۿ]*)$")


def parse_dose_cell(raw, inherited_unit):
    """Returns (dose_value, dose_unit, next_inherited_unit) or None if the
    cell is empty. A bare number/ratio with no unit text inherits the unit
    from the first dose cell in the same row that did specify one (falling
    back to 'mg' if none did — the overwhelming majority of doses in this
    sheet are milligrams)."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        val_str = str(int(raw)) if float(raw).is_integer() else str(raw)
        unit = inherited_unit or "mg"
        return val_str, unit, unit
    text = str(raw).strip()
    if not text:
        return None
    m = DOSE_CELL_RE.match(text)
    if m:
        num, unit = m.group(1), m.group(2).strip()
        unit = unit or inherited_unit or "mg"
        return num, unit, unit
    # No digits at all — a bare form word like "tab" / "amp" / "sachets".
    return text, "", inherited_unit


class Command(BaseCommand):
    help = "Imports MedicationCategory/Medication/MedicationDose from the clinic's Excel reference sheet."

    def add_arguments(self, parser):
        parser.add_argument("--file", default=DEFAULT_FILE, help="Path to the .xlsx reference sheet")

    def handle(self, *args, **options):
        path = options["file"]
        if not os.path.exists(path):
            self.stderr.write(self.style.ERROR(f"الملف غير موجود: {path}"))
            return

        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb.active

        current_section = None
        categories_created = medications_created = doses_created = 0
        categories_seen = medications_seen = doses_seen = 0

        for row in ws.iter_rows(values_only=True):
            cells = list(row)
            first = (str(cells[0]).strip() if cells[0] is not None else "")
            rest_filled = any(c is not None and str(c).strip() != "" for c in cells[1:])

            if not first and not rest_filled:
                continue  # blank separator row

            if first in SECTIONS and not rest_filled:
                current_section = first
                continue

            if first in ("الفئة", "المستحضر", "الاستخدام", "المكمل"):
                continue  # column-header row

            if current_section is None:
                continue  # stray row before the first recognized section

            cfg = SECTIONS[current_section]
            col0 = first
            col1 = str(cells[1]).strip() if len(cells) > 1 and cells[1] is not None else ""
            if not col0 and not col1:
                continue

            if cfg["kind"] == "classified":
                category_name, med_name, generic_name, dosage_form = col0, col1, "", ""
            elif cfg["kind"] == "combo":
                category_name, med_name, generic_name, dosage_form = current_section, col0, col1, ""
            else:  # supplement
                category_name, med_name, generic_name, dosage_form = "المكملات الغذائية", col0, "", col1

            if not med_name:
                continue

            category, created = MedicationCategory.objects.get_or_create(
                name=category_name, group=current_section, defaults={"type": cfg["type"]},
            )
            categories_seen += 1
            if created:
                categories_created += 1

            # dosage_form is part of the identity key (not just a
            # descriptive field) — e.g. "Vitamin D3" as a tablet and as an
            # injection are different prescribable items even though they
            # share a name, so they must stay separate Medication rows.
            medication, created = Medication.objects.get_or_create(
                name=med_name, category=category, dosage_form=dosage_form,
                defaults={
                    "generic_name": generic_name,
                    "medication_type": cfg["type"],
                },
            )
            medications_seen += 1
            if created:
                medications_created += 1
            elif not medication.is_custom and generic_name and medication.generic_name != generic_name:
                # Keep generic_name in sync on re-import (but never touch a
                # doctor's custom entry).
                medication.generic_name = generic_name
                medication.save(update_fields=["generic_name"])

            inherited_unit = ""
            for raw in cells[2:]:
                parsed = parse_dose_cell(raw, inherited_unit)
                if parsed is None:
                    continue
                dose_value, dose_unit, inherited_unit = parsed
                _, created = MedicationDose.objects.get_or_create(
                    medication=medication, dose_value=dose_value, dose_unit=dose_unit,
                )
                doses_seen += 1
                if created:
                    doses_created += 1

        self.stdout.write(self.style.SUCCESS(
            f"الفئات: {categories_created} جديدة من أصل {categories_seen} — "
            f"الأدوية: {medications_created} جديدة من أصل {medications_seen} — "
            f"الجرعات: {doses_created} جديدة من أصل {doses_seen}"
        ))
