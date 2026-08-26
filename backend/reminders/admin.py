from django.contrib import admin

from .models import ReminderTemplate, ReminderTemplateField, WhatsAppReminder, WhatsAppReminderEvent


class ReminderTemplateFieldInline(admin.TabularInline):
    """Smart Field Configuration (spec §32/§31) — this is where the admin
    decides, per {{n}} variable: required / editable by secretary /
    auto-filled / read-only, without ever touching Python code. A new
    reminder template type can be fully configured from here."""
    model = ReminderTemplateField
    extra = 1
    fields = [
        "variable_position", "variable_name", "label", "field_type",
        "required", "editable", "auto_fill_source", "default_value",
        "max_length", "display_order",
    ]
    ordering = ["display_order", "variable_position"]


@admin.register(ReminderTemplate)
class ReminderTemplateAdmin(admin.ModelAdmin):
    """Template Management (spec §10/§31) — the ONLY place the approved
    Meta template body (with its {{n}} placeholders) and the variable
    configuration are edited. Secretaries never see this screen; they only
    ever fill in the values ReminderTemplateField.editable=True allows,
    through the app's own New Reminder page."""
    list_display = ["display_name", "reminder_type", "language", "meta_template_name", "status", "is_active", "updated_at"]
    list_filter = ["reminder_type", "language", "status", "is_active"]
    search_fields = ["display_name", "meta_template_name"]
    inlines = [ReminderTemplateFieldInline]
    readonly_fields = ["created_at", "updated_at"]
    fieldsets = (
        (None, {"fields": ("reminder_type", "language", "display_name", "description")}),
        ("نص الرسالة", {
            "fields": ("meta_template_name", "meta_template_language_code", "body_text"),
            "description": "الإرسال يتم عبر جلسة WhatsApp الخاصة بالعيادة (WhatsApp Web) — النص هنا هو ما يُرسل للمريض حرفياً بعد تعويض {{1}} {{2}} ... بالقيم. حقول meta_template_name/language_code لم تعد مستخدمة فعلياً للإرسال (كانت خاصة بربط Meta Business API سابقاً) ويمكن تركها كما هي.",
        }),
        ("الحالة", {
            "fields": ("status", "is_active"),
            "description": "status اختياري الآن (تنظيمي فقط، مثال: \"راجعناها داخلياً\") ولا يمنع الإرسال — is_active هو المفتاح الوحيد الذي يوقف قالباً عن الاستخدام.",
        }),
        ("تواريخ", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(WhatsAppReminder)
class WhatsAppReminderAdmin(admin.ModelAdmin):
    """Read-only in /admin — every reminder is create-only via the app's
    Send flow (see reminders/views.py::ReminderSendView), never through
    /admin, so this exists purely for doctor-level visibility/audit, same
    pattern as AuditLogEntry/MounjaroCorrectionLog in the clinic app."""
    list_display = ["created_at", "patient", "reminder_type", "template", "status", "created_by", "sent_at"]
    list_filter = ["status", "reminder_type", "language"]
    search_fields = ["patient__file_number", "patient__user__full_name", "wa_message_id"]
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in WhatsAppReminder._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WhatsAppReminderEvent)
class WhatsAppReminderEventAdmin(admin.ModelAdmin):
    list_display = ["created_at", "reminder", "event_type", "actor"]
    list_filter = ["event_type"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
