from rest_framework import serializers

from .models import ReminderTemplate, ReminderTemplateField, WhatsAppReminder, WhatsAppReminderEvent
from .services.whatsapp import mask_phone


class ReminderTemplateFieldSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReminderTemplateField
        fields = [
            "id", "variable_name", "label", "variable_position", "field_type",
            "required", "editable", "auto_fill_source", "default_value",
            "max_length", "display_order",
        ]


class ReminderTemplateSerializer(serializers.ModelSerializer):
    reminder_type_display = serializers.CharField(source="get_reminder_type_display", read_only=True)
    language_display = serializers.CharField(source="get_language_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    is_sendable = serializers.BooleanField(read_only=True)
    fields_config = ReminderTemplateFieldSerializer(source="fields", many=True, read_only=True)

    class Meta:
        model = ReminderTemplate
        fields = [
            "id", "reminder_type", "reminder_type_display", "language", "language_display",
            "display_name", "meta_template_name", "description", "status", "status_display",
            "is_active", "is_sendable", "updated_at", "fields_config",
        ]


class ReminderTemplateListItemSerializer(serializers.ModelSerializer):
    """Lighter shape for the Settings > WhatsApp > Reminder Templates table
    (spec §10) — no need for the field configuration here."""
    reminder_type_display = serializers.CharField(source="get_reminder_type_display", read_only=True)
    language_display = serializers.CharField(source="get_language_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ReminderTemplate
        fields = [
            "id", "display_name", "reminder_type_display", "language_display",
            "meta_template_name", "status", "status_display", "is_active", "updated_at",
        ]


class PatientReminderSearchResultSerializer(serializers.Serializer):
    """Patient search result for step 2 of the New Reminder wizard — the
    phone number is ALWAYS masked here (spec §16/§2 example:
    964750******67); nothing in this module ever returns the full number."""
    patient_id = serializers.IntegerField()
    full_name = serializers.CharField()
    file_number = serializers.CharField()
    phone_masked = serializers.CharField()
    has_phone = serializers.BooleanField()
    preferred_language = serializers.CharField()
    upcoming_appointment = serializers.DateTimeField(allow_null=True)
    doctor_name = serializers.CharField(allow_blank=True)
    visit_type = serializers.CharField(allow_blank=True)


class WhatsAppReminderListSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.user.full_name", read_only=True)
    phone_masked = serializers.SerializerMethodField()
    template_name = serializers.CharField(source="template.display_name", read_only=True)
    reminder_type_display = serializers.CharField(source="get_reminder_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default="")
    sent_by_name = serializers.CharField(source="sent_by.full_name", read_only=True, default="")

    class Meta:
        model = WhatsAppReminder
        fields = [
            "id", "patient_name", "phone_masked", "template_name", "reminder_type",
            "reminder_type_display", "status", "status_display", "created_by_name",
            "sent_by_name", "created_at", "sent_at", "delivered_at", "read_at", "failed_at",
        ]

    def get_phone_masked(self, obj):
        return mask_phone(obj.phone_number)


class WhatsAppReminderEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.full_name", read_only=True, default="")
    event_type_display = serializers.CharField(source="get_event_type_display", read_only=True)

    class Meta:
        model = WhatsAppReminderEvent
        fields = ["event_type", "event_type_display", "actor_name", "detail", "created_at"]


class WhatsAppReminderDetailSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.user.full_name", read_only=True)
    phone_masked = serializers.SerializerMethodField()
    template_name = serializers.CharField(source="template.display_name", read_only=True)
    template_language = serializers.CharField(source="template.get_language_display", read_only=True)
    reminder_type_display = serializers.CharField(source="get_reminder_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default="")
    sent_by_name = serializers.CharField(source="sent_by.full_name", read_only=True, default="")
    message_preview = serializers.SerializerMethodField()
    events = WhatsAppReminderEventSerializer(many=True, read_only=True)

    class Meta:
        model = WhatsAppReminder
        fields = [
            "id", "patient_name", "phone_masked", "template_name", "template_language",
            "reminder_type", "reminder_type_display", "status", "status_display",
            "message_variables", "additional_note", "message_preview",
            "created_by_name", "sent_by_name", "created_at", "sent_at", "delivered_at",
            "read_at", "failed_at", "error_message", "wa_message_id", "events",
        ]

    def get_phone_masked(self, obj):
        return mask_phone(obj.phone_number)

    def get_message_preview(self, obj):
        from .services.rendering import render_preview
        return render_preview(obj.template, obj.message_variables)


class PreviewRequestSerializer(serializers.Serializer):
    patient_id = serializers.IntegerField()
    template_id = serializers.IntegerField()
    field_values = serializers.DictField(child=serializers.CharField(allow_blank=True), required=False, default=dict)
    additional_note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class SendReminderRequestSerializer(serializers.Serializer):
    patient_id = serializers.IntegerField()
    template_id = serializers.IntegerField()
    field_values = serializers.DictField(child=serializers.CharField(allow_blank=True), required=False, default=dict)
    additional_note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    appointment_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    dose_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    force_resend = serializers.BooleanField(required=False, default=False)
