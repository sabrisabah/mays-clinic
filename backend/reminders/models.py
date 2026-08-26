"""WhatsApp Reminder Center — patient reminder system, NOT a marketing tool.

Hard rule enforced throughout this app: nothing here ever sends a WhatsApp
message on its own. Every row in WhatsAppReminder is created and sent only
as the direct result of a secretary/doctor clicking "Confirm & Send" in the
UI (see reminders/views.py::ReminderSendView). There is no Django signal,
Celery task, or cron job anywhere in this app that fires a message
automatically — see reminders/apps.py and the absence of any signals.py.

Two admin-managed models (ReminderTemplate / ReminderTemplateField) hold
the Meta-approved template structure, kept deliberately separate from the
values a secretary can edit at send-time (see ReminderTemplateField.editable)
so a secretary can never change the message structure Meta approved — only
fill in the variables the admin marked as editable.
"""
import uuid

from django.conf import settings
from django.db import models

from clinic.models import Patient, User, Assessment, MounjaroDose


class ReminderTemplate(models.Model):
    APPOINTMENT = "appointment"
    DOSE = "dose"
    FOLLOWUP = "followup"
    VISIT = "visit"
    TEST = "test"
    CUSTOM_ADMIN = "custom_admin"
    TYPE_CHOICES = [
        (APPOINTMENT, "تذكير بموعد (Appointment Reminder)"),
        (DOSE, "تذكير بجرعة (Dose Reminder)"),
        (FOLLOWUP, "تذكير بمراجعة (Follow-up Reminder)"),
        (VISIT, "تذكير بزيارة (Visit Reminder)"),
        (TEST, "تذكير بفحص (Test Reminder)"),
        (CUSTOM_ADMIN, "إشعار إداري (Custom Administrative Reminder)"),
    ]

    ARABIC = "ar"
    ENGLISH = "en"
    KURDISH_SORANI = "ckb"
    LANGUAGE_CHOICES = [
        (ARABIC, "العربية"),
        (ENGLISH, "English"),
        (KURDISH_SORANI, "کوردیی ناوەندی"),
    ]

    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"
    DISABLED = "disabled"
    STATUS_CHOICES = [
        (APPROVED, "معتمد (Approved)"),
        (PENDING, "قيد المراجعة (Pending)"),
        (REJECTED, "مرفوض (Rejected)"),
        (DISABLED, "معطّل (Disabled)"),
    ]

    reminder_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    language = models.CharField(max_length=5, choices=LANGUAGE_CHOICES)
    display_name = models.CharField(max_length=150, help_text="اسم داخلي يظهر للسكرتيرة، مثال: تذكير موعد زيارة - عربي")

    # These two must exactly match what Meta approved in Business Manager —
    # never auto-generated, always entered by the admin from the approval
    # email/dashboard.
    meta_template_name = models.CharField(max_length=150, help_text="اسم القالب كما هو مسجل في Meta، مثال: appointment_reminder_ar")
    meta_template_language_code = models.CharField(max_length=20, default="ar", help_text="رمز اللغة في Meta، مثال: ar أو en_US أو ckb — يجب أن يطابق تسجيل القالب تماماً")

    description = models.TextField(blank=True, default="")

    # Literal copy of the APPROVED template body, {{1}}..{{n}} placeholders
    # intact. This is what render_preview() substitutes into for the
    # secretary's live preview — it is never sent to Meta directly (Meta is
    # called with the template `name` + ordered component values instead),
    # it exists purely so the in-app preview matches what WhatsApp will
    # actually deliver.
    body_text = models.TextField(help_text="نص القالب المعتمد حرفياً من Meta، مع بقاء {{1}} {{2}} ... كما هي")

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    is_active = models.BooleanField(default=True, help_text="تعطيل مؤقت من الإدارة — منفصل عن حالة الاعتماد لدى Meta")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("reminder_type", "language")]
        ordering = ["reminder_type", "language"]

    def __str__(self):
        return self.display_name

    @property
    def is_sendable(self):
        # `status` (approved/pending/rejected/disabled) was originally a hard
        # gate tied to Meta's official template-approval workflow — a
        # template could only be used once Meta had approved its exact
        # wording. Since sending now goes through the clinic's own WhatsApp
        # number (WhatsApp Web session via the internal bridge service, not
        # the Meta Business Cloud API), there is no external approval step
        # anymore: `status` is kept only as an informational/organizational
        # field (e.g. "we've reviewed this wording internally"), and the
        # only thing that actually blocks sending is `is_active`.
        return self.is_active


class ReminderTemplateField(models.Model):
    """One configurable {{n}} variable slot on a template. Building a new
    template type never requires a code change — just new rows here (see
    §32 of the spec this implements: Smart Field Configuration)."""

    TEXT = "text"
    DATE = "date"
    TIME = "time"
    NUMBER = "number"
    FIELD_TYPE_CHOICES = [
        (TEXT, "نص"),
        (DATE, "تاريخ"),
        (TIME, "وقت"),
        (NUMBER, "رقم"),
    ]

    template = models.ForeignKey(ReminderTemplate, on_delete=models.CASCADE, related_name="fields")
    variable_name = models.CharField(max_length=50, help_text="مثال: appointment_date")
    label = models.CharField(max_length=100, help_text="التسمية المعروضة للسكرتيرة، مثال: تاريخ الموعد")
    variable_position = models.PositiveIntegerField(help_text="رقم المتغير في القالب، مثال: 3 يعني {{3}}")
    field_type = models.CharField(max_length=10, choices=FIELD_TYPE_CHOICES, default=TEXT)

    required = models.BooleanField(default=False)
    editable = models.BooleanField(default=True, help_text="هل يستطيع السكرتير تعديل هذا الحقل قبل الإرسال")

    # Dot-path resolved by reminders/services/autofill.py against the
    # selected patient, e.g. "patient.full_name", "appointment.date",
    # "dose.date". Blank means this field is always entered manually.
    auto_fill_source = models.CharField(max_length=100, blank=True, default="")

    default_value = models.CharField(max_length=255, blank=True, default="")
    max_length = models.PositiveIntegerField(null=True, blank=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("template", "variable_position")]
        ordering = ["display_order", "variable_position"]

    def __str__(self):
        return f"{self.template.display_name} — {self.label} ({{{{{self.variable_position}}}}})"

    @property
    def is_auto_filled(self):
        return bool(self.auto_fill_source)


class WhatsAppReminder(models.Model):
    """One sent (or attempted) reminder. Created only at the moment the
    secretary/doctor presses "Confirm & Send" — see ReminderSendView. There
    is deliberately no earlier "Draft" row persisted per patient session;
    the wizard (search -> template -> fields -> preview) lives entirely in
    the frontend until confirmation, matching the spec's linear workflow."""

    DRAFT = "draft"
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (DRAFT, "مسودة"),
        (PENDING, "قيد الإرسال"),
        (SENDING, "جارِ الإرسال"),
        (SENT, "تم الإرسال"),
        (DELIVERED, "تم التوصيل"),
        (READ, "تمت القراءة"),
        (FAILED, "فشل الإرسال"),
        (CANCELLED, "أُلغي"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="whatsapp_reminders")

    # Normalized E.164 digits, needed to actually call the Meta API and to
    # resend later. NEVER returned unmasked by any serializer and NEVER
    # written to logging/print — see services/whatsapp.mask_phone() and
    # WhatsAppReminderSerializer.
    phone_number = models.CharField(max_length=20)

    template = models.ForeignKey(ReminderTemplate, on_delete=models.PROTECT, related_name="reminders")
    language = models.CharField(max_length=5, choices=ReminderTemplate.LANGUAGE_CHOICES)
    reminder_type = models.CharField(max_length=20, choices=ReminderTemplate.TYPE_CHOICES)

    # This app has no standalone Appointment model — a patient's upcoming
    # visit lives on their Assessment row (visit_date/appointment_booked).
    # "appointment" here links to that same Assessment row for audit/
    # duplicate-detection purposes. "dose" links to the specific
    # MounjaroDose entry a dose reminder relates to, when applicable.
    appointment = models.ForeignKey(Assessment, null=True, blank=True, on_delete=models.SET_NULL, related_name="whatsapp_reminders")
    dose = models.ForeignKey(MounjaroDose, null=True, blank=True, on_delete=models.SET_NULL, related_name="whatsapp_reminders")

    # Final {"1": "...", "2": "...", ...} snapshot of what was actually
    # sent — reconstructing the message later (history/detail view) never
    # depends on live patient data that may have since changed.
    message_variables = models.JSONField(default=dict, blank=True)
    additional_note = models.CharField(max_length=200, blank=True, default="")

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)
    wa_message_id = models.CharField(max_length=100, blank=True, default="")

    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="reminders_created")
    sent_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="reminders_sent")

    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    # Secretary-facing failure reason. Meta error bodies are scrubbed of any
    # token/secret before being stored here — see services/whatsapp.py.
    error_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["patient", "reminder_type", "created_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.get_reminder_type_display()} → {self.patient.user.full_name} ({self.status})"


class WhatsAppReminderEvent(models.Model):
    """Append-only timeline entries powering the message detail screen's
    "13:10 Created / 13:11 Confirmed / 13:11 Sent / ..." view (§22), and
    doubling as the audit trail for who prepared/edited/sent each message
    (§34). Never store secrets (tokens) in `detail`."""

    CREATED = "created"
    CONFIRMED = "confirmed"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EVENT_CHOICES = [
        (CREATED, "تم الإنشاء"),
        (CONFIRMED, "تم التأكيد"),
        (SENT, "تم الإرسال"),
        (DELIVERED, "تم التوصيل"),
        (READ, "تمت القراءة"),
        (FAILED, "فشل"),
        (CANCELLED, "أُلغي"),
    ]

    reminder = models.ForeignKey(WhatsAppReminder, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=12, choices=EVENT_CHOICES)
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    detail = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
