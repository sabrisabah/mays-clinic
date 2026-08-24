"""Seeds the 6 reminder types x 3 languages = 18 ReminderTemplate rows,
each with its ReminderTemplateField configuration, so the Reminder Center
is usable immediately after deploy.

IMPORTANT — these seed rows are created with status="pending", NOT
"approved". A template can never be used to send a real message until an
admin (doctor) has: (1) actually submitted the exact body_text below to
Meta Business Manager as a message template, (2) had it approved, and
(3) come back to /admin and set meta_template_name to the real approved
name and status to "approved". See the "خطوات إنشاء واعتماد Templates"
section of the delivery report for the full walkthrough.

Safe to re-run: uses get_or_create keyed on (reminder_type, language), so
it never overwrites a template an admin has already configured/approved —
only fills in ones that are missing.

Usage: python manage.py seed_reminder_templates
"""
from django.core.management.base import BaseCommand

from reminders.models import ReminderTemplate, ReminderTemplateField

# Shared {{n}} variable roles used by every "visit-shaped" template
# (appointment / followup / visit): 1=patient_name 2=date 3=time
# 4=doctor 5=location 6=note.
VISIT_FIELDS = [
    dict(variable_position=1, variable_name="patient_name", label="اسم المريض", field_type="text",
         required=True, editable=False, auto_fill_source="patient.full_name", display_order=1),
    dict(variable_position=2, variable_name="appointment_date", label="تاريخ الموعد", field_type="date",
         required=True, editable=True, auto_fill_source="appointment.date", display_order=2),
    dict(variable_position=3, variable_name="appointment_time", label="وقت الموعد", field_type="time",
         required=True, editable=True, auto_fill_source="appointment.time", display_order=3),
    dict(variable_position=4, variable_name="doctor_name", label="الطبيب", field_type="text",
         required=False, editable=True, auto_fill_source="appointment.doctor_name", display_order=4),
    dict(variable_position=5, variable_name="location", label="المكان", field_type="text",
         required=False, editable=True, auto_fill_source="appointment.location", display_order=5),
    dict(variable_position=6, variable_name="note", label="ملاحظة إضافية", field_type="text",
         required=False, editable=True, auto_fill_source="", max_length=200, display_order=6),
]

DOSE_FIELDS = [
    dict(variable_position=1, variable_name="patient_name", label="اسم المريض", field_type="text",
         required=True, editable=False, auto_fill_source="patient.full_name", display_order=1),
    dict(variable_position=2, variable_name="dose_name", label="اسم الجرعة", field_type="text",
         required=True, editable=True, auto_fill_source="dose.name", display_order=2),
    dict(variable_position=3, variable_name="dose_date", label="تاريخ الجرعة", field_type="date",
         required=True, editable=True, auto_fill_source="dose.date", display_order=3),
    dict(variable_position=4, variable_name="dose_time", label="وقت الجرعة", field_type="time",
         required=False, editable=True, auto_fill_source="dose.time", display_order=4),
    dict(variable_position=5, variable_name="location", label="المكان", field_type="text",
         required=False, editable=True, auto_fill_source="dose.location", display_order=5),
    dict(variable_position=6, variable_name="note", label="ملاحظة إضافية", field_type="text",
         required=False, editable=True, auto_fill_source="", max_length=200, display_order=6),
]

TEST_FIELDS = [
    dict(variable_position=1, variable_name="patient_name", label="اسم المريض", field_type="text",
         required=True, editable=False, auto_fill_source="patient.full_name", display_order=1),
    dict(variable_position=2, variable_name="test_name", label="اسم الفحص", field_type="text",
         required=True, editable=True, auto_fill_source="", display_order=2),
    dict(variable_position=3, variable_name="appointment_date", label="تاريخ الفحص", field_type="date",
         required=True, editable=True, auto_fill_source="appointment.date", display_order=3),
    dict(variable_position=4, variable_name="appointment_time", label="وقت الفحص", field_type="time",
         required=False, editable=True, auto_fill_source="appointment.time", display_order=4),
    dict(variable_position=5, variable_name="location", label="المكان", field_type="text",
         required=False, editable=True, auto_fill_source="appointment.location", display_order=5),
    dict(variable_position=6, variable_name="note", label="ملاحظة إضافية", field_type="text",
         required=False, editable=True, auto_fill_source="", max_length=200, display_order=6),
]

ADMIN_FIELDS = [
    dict(variable_position=1, variable_name="patient_name", label="اسم المريض", field_type="text",
         required=True, editable=False, auto_fill_source="patient.full_name", display_order=1),
    dict(variable_position=2, variable_name="subject", label="موضوع الإشعار", field_type="text",
         required=True, editable=True, auto_fill_source="", display_order=2),
    dict(variable_position=3, variable_name="admin_date", label="التاريخ", field_type="date",
         required=False, editable=True, auto_fill_source="", display_order=3),
    dict(variable_position=4, variable_name="admin_time", label="الوقت", field_type="time",
         required=False, editable=True, auto_fill_source="", display_order=4),
    dict(variable_position=5, variable_name="location", label="المكان", field_type="text",
         required=False, editable=True, auto_fill_source="", display_order=5),
    dict(variable_position=6, variable_name="note", label="ملاحظة قصيرة", field_type="text",
         required=False, editable=True, auto_fill_source="", max_length=200, display_order=6),
]

VISIT_BODY = {
    "ar": (
        "مرحباً {{1}}،\n\n"
        "نود تذكيركم بأن لديكم موعد زيارة بتاريخ {{2}}\n"
        "الساعة {{3}}.\n\n"
        "الطبيب:\n{{4}}\n\n"
        "المكان:\n{{5}}\n\n"
        "{{6}}\n\n"
        "مع تمنياتنا لكم بالصحة والسلامة."
    ),
    "en": (
        "Hello {{1}},\n\n"
        "This is a reminder that you have an appointment on {{2}}\n"
        "at {{3}}.\n\n"
        "Doctor:\n{{4}}\n\n"
        "Location:\n{{5}}\n\n"
        "{{6}}\n\n"
        "Wishing you good health."
    ),
    "ckb": (
        "سلاو {{1}}،\n\n"
        "ئەمە بیرخستنەوەیەکە کە کاتی چاوپێکەوتنتان لە {{2}}\n"
        "کاتژمێر {{3}} دیاریکراوە.\n\n"
        "پزیشک:\n{{4}}\n\n"
        "شوێن:\n{{5}}\n\n"
        "{{6}}\n\n"
        "هیوادارین تەندروست بن."
    ),
}

FOLLOWUP_BODY = {
    "ar": (
        "مرحباً {{1}}،\n\n"
        "نود تذكيركم بموعد المراجعة بتاريخ {{2}}\n"
        "الساعة {{3}}.\n\n"
        "الطبيب:\n{{4}}\n\n"
        "المكان:\n{{5}}\n\n"
        "{{6}}\n\n"
        "مع تمنياتنا لكم بالصحة والسلامة."
    ),
    "en": (
        "Hello {{1}},\n\n"
        "This is a reminder for your follow-up visit on {{2}}\n"
        "at {{3}}.\n\n"
        "Doctor:\n{{4}}\n\n"
        "Location:\n{{5}}\n\n"
        "{{6}}\n\n"
        "Wishing you good health."
    ),
    "ckb": (
        "سلاو {{1}}،\n\n"
        "ئەمە بیرخستنەوەیەکە بۆ چاوپێکەوتنەوەی پشکنین لە {{2}}\n"
        "کاتژمێر {{3}}.\n\n"
        "پزیشک:\n{{4}}\n\n"
        "شوێن:\n{{5}}\n\n"
        "{{6}}\n\n"
        "هیوادارین تەندروست بن."
    ),
}

GENERIC_VISIT_BODY = {
    "ar": (
        "مرحباً {{1}}،\n\n"
        "نود تذكيركم بموعد زيارتكم للعيادة بتاريخ {{2}}\n"
        "الساعة {{3}}.\n\n"
        "الطبيب:\n{{4}}\n\n"
        "المكان:\n{{5}}\n\n"
        "{{6}}\n\n"
        "مع تمنياتنا لكم بالصحة والسلامة."
    ),
    "en": (
        "Hello {{1}},\n\n"
        "This is a reminder for your clinic visit on {{2}}\n"
        "at {{3}}.\n\n"
        "Doctor:\n{{4}}\n\n"
        "Location:\n{{5}}\n\n"
        "{{6}}\n\n"
        "Wishing you good health."
    ),
    "ckb": (
        "سلاو {{1}}،\n\n"
        "ئەمە بیرخستنەوەیەکە بۆ سەردانی نۆژەنخانە لە {{2}}\n"
        "کاتژمێر {{3}}.\n\n"
        "پزیشک:\n{{4}}\n\n"
        "شوێن:\n{{5}}\n\n"
        "{{6}}\n\n"
        "هیوادارین تەندروست بن."
    ),
}

DOSE_BODY = {
    "ar": (
        "مرحباً {{1}}،\n\n"
        "نود تذكيركم بأن موعد الجرعة القادمة هو:\n\n"
        "{{2}}\n\n"
        "التاريخ:\n{{3}}\n\n"
        "الوقت:\n{{4}}\n\n"
        "المكان:\n{{5}}\n\n"
        "{{6}}\n\n"
        "يرجى الالتزام بالموعد المحدد."
    ),
    "en": (
        "Hello {{1}},\n\n"
        "This is a reminder that your next dose is:\n\n"
        "{{2}}\n\n"
        "Date:\n{{3}}\n\n"
        "Time:\n{{4}}\n\n"
        "Location:\n{{5}}\n\n"
        "{{6}}\n\n"
        "Please keep your scheduled appointment."
    ),
    "ckb": (
        "سلاو {{1}}،\n\n"
        "ئەمە بیرخستنەوەیەکە کە دۆزی داهاتوو بریتییە لە:\n\n"
        "{{2}}\n\n"
        "بەروار:\n{{3}}\n\n"
        "کات:\n{{4}}\n\n"
        "شوێن:\n{{5}}\n\n"
        "{{6}}\n\n"
        "تکایە کاتی دیاریکراو بەجێبگەیەنن."
    ),
}

TEST_BODY = {
    "ar": (
        "مرحباً {{1}}،\n\n"
        "نود تذكيركم بموعد الفحص ({{2}}) بتاريخ {{3}}\n"
        "الساعة {{4}}.\n\n"
        "المكان:\n{{5}}\n\n"
        "{{6}}\n\n"
        "يرجى الحضور مع التحاليل السابقة إن وجدت."
    ),
    "en": (
        "Hello {{1}},\n\n"
        "This is a reminder for your test ({{2}}) on {{3}}\n"
        "at {{4}}.\n\n"
        "Location:\n{{5}}\n\n"
        "{{6}}\n\n"
        "Please bring any previous lab results."
    ),
    "ckb": (
        "سلاو {{1}}،\n\n"
        "ئەمە بیرخستنەوەیەکە بۆ پشکنینی ({{2}}) لە {{3}}\n"
        "کاتژمێر {{4}}.\n\n"
        "شوێن:\n{{5}}\n\n"
        "{{6}}\n\n"
        "تکایە ئەنجامی پشکنینەکانی پێشوو لەگەڵ خۆتان بهێنن."
    ),
}

ADMIN_BODY = {
    "ar": (
        "مرحباً {{1}}،\n\n"
        "{{2}}\n\n"
        "التاريخ: {{3}}\n"
        "الوقت: {{4}}\n"
        "المكان: {{5}}\n\n"
        "{{6}}\n\n"
        "مع تحيات عيادة دكتورة ميس الربيعي."
    ),
    "en": (
        "Hello {{1}},\n\n"
        "{{2}}\n\n"
        "Date: {{3}}\n"
        "Time: {{4}}\n"
        "Location: {{5}}\n\n"
        "{{6}}\n\n"
        "Best regards, Dr. Mais Al-Rubaie Clinic."
    ),
    "ckb": (
        "سلاو {{1}}،\n\n"
        "{{2}}\n\n"
        "بەروار: {{3}}\n"
        "کات: {{4}}\n"
        "شوێن: {{5}}\n\n"
        "{{6}}\n\n"
        "لەگەڵ ڕێزمان، نۆژەنخانەی دکتۆر میس ڕەبیعی."
    ),
}

DISPLAY_NAMES = {
    ReminderTemplate.APPOINTMENT: "تذكير موعد زيارة",
    ReminderTemplate.DOSE: "تذكير موعد جرعة",
    ReminderTemplate.FOLLOWUP: "تذكير مراجعة",
    ReminderTemplate.VISIT: "تذكير زيارة عيادة",
    ReminderTemplate.TEST: "تذكير فحص",
    ReminderTemplate.CUSTOM_ADMIN: "إشعار إداري",
}

LANG_SUFFIX = {"ar": "عربي", "en": "English", "ckb": "کوردی"}

TYPE_DEFS = [
    (ReminderTemplate.APPOINTMENT, VISIT_BODY, VISIT_FIELDS, "appointment_reminder"),
    (ReminderTemplate.DOSE, DOSE_BODY, DOSE_FIELDS, "dose_reminder"),
    (ReminderTemplate.FOLLOWUP, FOLLOWUP_BODY, VISIT_FIELDS, "followup_reminder"),
    (ReminderTemplate.VISIT, GENERIC_VISIT_BODY, VISIT_FIELDS, "visit_reminder"),
    (ReminderTemplate.TEST, TEST_BODY, TEST_FIELDS, "test_reminder"),
    (ReminderTemplate.CUSTOM_ADMIN, ADMIN_BODY, ADMIN_FIELDS, "custom_admin_reminder"),
]

META_LANGUAGE_CODE = {"ar": "ar", "en": "en_US", "ckb": "ckb"}


class Command(BaseCommand):
    help = "Seeds the 6x3 WhatsApp reminder templates (pending approval) with their field configuration."

    def handle(self, *args, **options):
        created_count, skipped_count, fields_created = 0, 0, 0
        for reminder_type, bodies, fields_def, meta_prefix in TYPE_DEFS:
            for lang in ["ar", "en", "ckb"]:
                template, was_created = ReminderTemplate.objects.get_or_create(
                    reminder_type=reminder_type,
                    language=lang,
                    defaults=dict(
                        display_name=f"{DISPLAY_NAMES[reminder_type]} - {LANG_SUFFIX[lang]}",
                        meta_template_name=f"{meta_prefix}_{lang}",
                        meta_template_language_code=META_LANGUAGE_CODE[lang],
                        description="تم إنشاؤه تلقائياً — يحتاج اعتماد Meta قبل الاستخدام الفعلي (راجع /admin).",
                        body_text=bodies[lang],
                        status=ReminderTemplate.PENDING,
                        is_active=True,
                    ),
                )
                if was_created:
                    created_count += 1
                    for field_kwargs in fields_def:
                        ReminderTemplateField.objects.create(template=template, **field_kwargs)
                        fields_created += 1
                else:
                    skipped_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"قوالب التذكيرات: {created_count} جديدة ({fields_created} حقل) من أصل {created_count + skipped_count} "
            f"— بحالة 'قيد المراجعة' حتى يتم اعتمادها فعلياً في Meta وتحديثها من /admin."
        ))
