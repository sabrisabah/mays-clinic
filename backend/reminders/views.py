"""Views for the WhatsApp Reminder Center.

Hard rule (see models.py docstring): a WhatsAppReminder row is only ever
created inside ReminderSendView.post(), and only as the direct result of
an authenticated secretary/doctor request that already passed
prepare_variables()/validate_template(). There is no other code path in
this app that creates or sends one — no signal, no scheduled task.

All Meta API logic lives in services/whatsapp.py — views only orchestrate:
look up data, call the service, persist the result, log an audit event.
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from clinic.models import Assessment, MounjaroDose, Patient, User

from . import serializers as sz
from .models import ReminderTemplate, WhatsAppReminder, WhatsAppReminderEvent
from .permissions import (
    can_create_reminder,
    can_manage_reminder_templates,
    can_send_reminder,
    can_view_reminder_history,
    can_view_reminders,
)
from .services import whatsapp
from .services.autofill import resolve_autofill_values
from .services.rendering import render_preview

DUPLICATE_WINDOW_HOURS = 24


def _require(check, request):
    if not check(request.user):
        raise PermissionDenied("لا تملك صلاحية الوصول لهذا الإجراء")


def _get_patient(patient_id):
    try:
        return Patient.objects.select_related("user", "assessment").get(id=patient_id)
    except Patient.DoesNotExist:
        raise NotFound("المريض غير موجود")


def _get_template(template_id):
    try:
        return ReminderTemplate.objects.prefetch_related("fields").get(id=template_id)
    except ReminderTemplate.DoesNotExist:
        raise NotFound("القالب غير موجود")


def _find_recent_duplicate(patient, reminder_type, appointment_id, dose_id):
    """Duplicate-send guard (spec §23): same patient + same reminder type +
    same underlying appointment/dose, already sent (not failed/cancelled)
    within the last 24h."""
    qs = WhatsAppReminder.objects.filter(
        patient=patient,
        reminder_type=reminder_type,
        created_at__gte=timezone.now() - timedelta(hours=DUPLICATE_WINDOW_HOURS),
    ).exclude(status__in=[WhatsAppReminder.FAILED, WhatsAppReminder.CANCELLED, WhatsAppReminder.DRAFT])
    if appointment_id:
        qs = qs.filter(appointment_id=appointment_id)
    if dose_id:
        qs = qs.filter(dose_id=dose_id)
    if not appointment_id and not dose_id:
        # Custom/admin reminders with no linked record — still guard on
        # patient+type+day so a slipped double-click doesn't double-send.
        qs = qs.filter(created_at__date=timezone.now().date())
    return qs.order_by("-created_at").first()


# ---------------- TEMPLATES ----------------

class ReminderTemplateListView(APIView):
    def get(self, request):
        _require(can_view_reminders, request)
        qs = ReminderTemplate.objects.prefetch_related("fields")
        reminder_type = request.query_params.get("reminder_type")
        language = request.query_params.get("language")
        if reminder_type:
            qs = qs.filter(reminder_type=reminder_type)
        if language:
            qs = qs.filter(language=language)
        # Secretaries only ever see templates that are actually sendable —
        # a disabled template should not even appear as an option in the
        # New Reminder wizard. Doctors can pass ?all=1 to see everything
        # (used by the Settings > Reminder Templates page). Approval
        # `status` is no longer a hard gate (see ReminderTemplate.is_sendable)
        # so it's intentionally not part of this filter anymore.
        if not (request.user.role == "doctor" and request.query_params.get("all")):
            qs = qs.filter(is_active=True)
        return Response(sz.ReminderTemplateSerializer(qs, many=True).data)


class ReminderTemplateDetailView(APIView):
    def get(self, request, template_id):
        _require(can_view_reminders, request)
        template = _get_template(template_id)
        return Response(sz.ReminderTemplateSerializer(template).data)


class ReminderTemplateSettingsListView(APIView):
    """Settings > WhatsApp > Reminder Templates (spec §10) — every
    template regardless of status, for visibility. Editing still only
    happens in Django Admin (see reminders/admin.py) — this is read-only,
    available to both doctor and secretary."""

    def get(self, request):
        _require(can_view_reminders, request)
        qs = ReminderTemplate.objects.all()
        return Response(sz.ReminderTemplateListItemSerializer(qs, many=True).data)


# ---------------- PATIENT SEARCH ----------------

class ReminderPatientSearchView(APIView):
    def get(self, request):
        _require(can_view_reminders, request)
        search = (request.query_params.get("q") or "").strip()
        qs = Patient.objects.select_related("user", "assessment")
        if search:
            # Spec §2: search by name, patient ID (file number), phone, or
            # "appointment number" — this app has no separate appointment
            # numbering system, so file_number doubles as that reference.
            qs = qs.filter(
                Q(user__full_name__icontains=search)
                | Q(file_number__icontains=search)
                | Q(user__phone__icontains=search)
            )
        qs = qs.order_by("-id")[:25]

        doctor = User.objects.filter(role="doctor", is_active=True).order_by("id").first()
        results = []
        for p in qs:
            assessment = getattr(p, "assessment", None)
            results.append({
                "patient_id": p.id,
                "full_name": p.user.full_name,
                "file_number": p.file_number,
                "phone_masked": whatsapp.mask_phone(p.user.phone),
                "has_phone": bool(p.user.phone),
                "preferred_language": p.preferred_language,
                "upcoming_appointment": assessment.visit_date if (assessment and assessment.appointment_booked) else None,
                "doctor_name": doctor.full_name if doctor else "",
                "visit_type": "",
            })
        return Response(sz.PatientReminderSearchResultSerializer(results, many=True).data)


class ReminderAutoFillView(APIView):
    def get(self, request, patient_id):
        _require(can_view_reminders, request)
        patient = _get_patient(patient_id)
        reminder_type = request.query_params.get("reminder_type", "appointment")
        values = resolve_autofill_values(reminder_type, patient)
        return Response(values)


# ---------------- PREVIEW / SEND ----------------

class ReminderPreviewView(APIView):
    def post(self, request):
        _require(can_create_reminder, request)
        serializer = sz.PreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        patient = _get_patient(data["patient_id"])
        template = _get_template(data["template_id"])

        field_values = dict(data["field_values"])
        if data.get("additional_note"):
            # Whichever field the template designates for the free-text
            # note (usually variable_name="note") gets the value too, so
            # admins can point any template's note slot at this shared input.
            note_field = template.fields.filter(field_type="text", variable_name__icontains="note").first()
            if note_field:
                field_values.setdefault(note_field.variable_name, data["additional_note"])

        try:
            whatsapp.validate_template(template)
            variables = whatsapp.prepare_variables(template, field_values)
        except whatsapp.WhatsAppServiceError as e:
            raise ValidationError({"detail": e.user_message})

        preview_text = render_preview(template, variables)

        duplicate = _find_recent_duplicate(
            patient, template.reminder_type,
            appointment_id=getattr(getattr(patient, "assessment", None), "id", None) if template.reminder_type != "dose" else None,
            dose_id=None,
        )
        duplicate_payload = None
        if duplicate:
            duplicate_payload = {
                "reminder_id": str(duplicate.id),
                "sent_at": duplicate.sent_at,
                "status": duplicate.status,
                "status_display": duplicate.get_status_display(),
            }

        return Response({
            "preview": preview_text,
            "variables": variables,
            "phone_masked": whatsapp.mask_phone(patient.user.phone),
            "ready_to_send": patient.user.phone is not None and template.is_sendable,
            "duplicate_warning": duplicate_payload,
        })


class ReminderSendView(APIView):
    def post(self, request):
        _require(can_send_reminder, request)
        serializer = sz.SendReminderRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        patient = _get_patient(data["patient_id"])
        template = _get_template(data["template_id"])

        if not patient.user.phone:
            raise ValidationError({"detail": "لا يوجد رقم WhatsApp مسجّل لهذا المريض"})

        field_values = dict(data["field_values"])
        if data.get("additional_note"):
            note_field = template.fields.filter(field_type="text", variable_name__icontains="note").first()
            if note_field:
                field_values.setdefault(note_field.variable_name, data["additional_note"])

        appointment = None
        if data.get("appointment_id"):
            appointment = Assessment.objects.filter(id=data["appointment_id"], patient=patient).first()
        dose = None
        if data.get("dose_id"):
            dose = MounjaroDose.objects.filter(id=data["dose_id"], patient=patient).first()

        if not data["force_resend"]:
            duplicate = _find_recent_duplicate(
                patient, template.reminder_type,
                appointment_id=appointment.id if appointment else None,
                dose_id=dose.id if dose else None,
            )
            if duplicate:
                return Response({
                    "duplicate": True,
                    "detail": "⚠ تم إرسال هذا التذكير مسبقاً",
                    "reminder_id": str(duplicate.id),
                    "sent_at": duplicate.sent_at,
                    "status": duplicate.status,
                    "status_display": duplicate.get_status_display(),
                }, status=409)

        try:
            whatsapp.validate_template(template)
            variables = whatsapp.prepare_variables(template, field_values)
        except whatsapp.WhatsAppServiceError as e:
            raise ValidationError({"detail": e.user_message})

        reminder = WhatsAppReminder.objects.create(
            patient=patient,
            phone_number=whatsapp.normalize_phone(patient.user.phone),
            template=template,
            language=template.language,
            reminder_type=template.reminder_type,
            appointment=appointment,
            dose=dose,
            message_variables=variables,
            additional_note=data.get("additional_note", ""),
            status=WhatsAppReminder.PENDING,
            created_by=request.user,
            sent_by=request.user,
        )
        WhatsAppReminderEvent.objects.create(reminder=reminder, event_type=WhatsAppReminderEvent.CREATED, actor=request.user)
        WhatsAppReminderEvent.objects.create(reminder=reminder, event_type=WhatsAppReminderEvent.CONFIRMED, actor=request.user)

        try:
            whatsapp.send_reminder(reminder)
        except whatsapp.WhatsAppServiceError as e:
            reminder.save()
            WhatsAppReminderEvent.objects.create(
                reminder=reminder, event_type=WhatsAppReminderEvent.FAILED,
                actor=request.user, detail=e.user_message,
            )
            return Response({"detail": e.user_message, "reminder_id": str(reminder.id), "status": reminder.status}, status=502)

        reminder.save()
        WhatsAppReminderEvent.objects.create(reminder=reminder, event_type=WhatsAppReminderEvent.SENT, actor=request.user)
        return Response(sz.WhatsAppReminderDetailSerializer(reminder).data, status=201)


# ---------------- HISTORY ----------------

class ReminderHistoryListView(APIView):
    def get(self, request):
        _require(can_view_reminder_history, request)
        qs = WhatsAppReminder.objects.select_related("patient__user", "template", "created_by", "sent_by")
        patient_id = request.query_params.get("patient_id")
        status_filter = request.query_params.get("status")
        reminder_type = request.query_params.get("reminder_type")
        if patient_id:
            qs = qs.filter(patient_id=patient_id)
        if status_filter:
            qs = qs.filter(status=status_filter)
        if reminder_type:
            qs = qs.filter(reminder_type=reminder_type)
        qs = qs[:200]
        return Response(sz.WhatsAppReminderListSerializer(qs, many=True).data)


class ReminderDetailView(APIView):
    def get(self, request, reminder_id):
        _require(can_view_reminder_history, request)
        try:
            reminder = WhatsAppReminder.objects.select_related("patient__user", "template").prefetch_related("events").get(id=reminder_id)
        except (WhatsAppReminder.DoesNotExist, ValueError):
            raise NotFound("السجل غير موجود")
        return Response(sz.WhatsAppReminderDetailSerializer(reminder).data)


class ReminderCancelView(APIView):
    def post(self, request, reminder_id):
        _require(can_send_reminder, request)
        try:
            reminder = WhatsAppReminder.objects.get(id=reminder_id)
        except (WhatsAppReminder.DoesNotExist, ValueError):
            raise NotFound("السجل غير موجود")
        if reminder.status not in (WhatsAppReminder.DRAFT, WhatsAppReminder.PENDING):
            raise ValidationError({"detail": "لا يمكن إلغاء رسالة أُرسلت بالفعل"})
        reminder.status = WhatsAppReminder.CANCELLED
        reminder.save(update_fields=["status"])
        WhatsAppReminderEvent.objects.create(reminder=reminder, event_type=WhatsAppReminderEvent.CANCELLED, actor=request.user)
        return Response({"ok": True})


# ---------------- WHATSAPP CONNECTION (bridge status/QR) ----------------
# Thin proxies over reminders/services/whatsapp.py's bridge helpers — the
# frontend connection page polls these instead of talking to the bridge
# service directly (the bridge has no public domain; it's only reachable
# from this Django service over Railway's private network).

class WhatsAppConnectionStatusView(APIView):
    def get(self, request):
        _require(can_manage_reminder_templates, request)
        return Response(whatsapp.get_bridge_status())


class WhatsAppConnectionQrView(APIView):
    def get(self, request):
        _require(can_manage_reminder_templates, request)
        from django.http import HttpResponse
        png, reason = whatsapp.get_bridge_qr_png()
        if png is None:
            return Response({"detail": reason}, status=404)
        return HttpResponse(png, content_type="image/png")


class WhatsAppConnectionLogoutView(APIView):
    def post(self, request):
        _require(can_manage_reminder_templates, request)
        try:
            whatsapp.logout_bridge()
        except whatsapp.WhatsAppServiceError as e:
            return Response({"detail": e.user_message}, status=502)
        return Response({"ok": True})


# ---------------- DASHBOARD ----------------

class ReminderDashboardView(APIView):
    def get(self, request):
        _require(can_view_reminders, request)
        today = timezone.localdate()
        today_qs = WhatsAppReminder.objects.filter(created_at__date=today)

        upcoming_cutoff = timezone.now() + timedelta(days=2)
        upcoming_appointments = list(
            Assessment.objects.select_related("patient__user")
            .filter(appointment_booked=True, visit_date__gte=timezone.now(), visit_date__lte=upcoming_cutoff)
            .order_by("visit_date")[:20]
        )
        upcoming_appointments_payload = [{
            "patient_id": a.patient_id,
            "patient_name": a.patient.user.full_name,
            "date": a.visit_date,
            "phone_masked": whatsapp.mask_phone(a.patient.user.phone),
            "reminder_sent_today": WhatsAppReminder.objects.filter(
                patient_id=a.patient_id, reminder_type__in=["appointment", "visit"],
                appointment_id=a.id, created_at__date=today,
            ).exclude(status__in=[WhatsAppReminder.FAILED, WhatsAppReminder.CANCELLED]).exists(),
        } for a in upcoming_appointments]

        # Upcoming doses: this app has no future-dose schedule table (see
        # services/autofill.resolve_dose_autofill) — "upcoming" here means
        # any patient whose last MounjaroDose + 7 days falls in the same
        # [now, now+2 days] window as appointments above.
        upcoming_doses_payload = []
        patients_with_doses = Patient.objects.filter(mounjaro_doses__isnull=False).distinct().select_related("user")
        for p in patients_with_doses:
            last_dose = p.mounjaro_doses.order_by("-date").first()
            if not last_dose:
                continue
            next_dose_date = last_dose.date + timedelta(days=7)
            if not (timezone.now() <= next_dose_date <= upcoming_cutoff):
                continue
            upcoming_doses_payload.append({
                "patient_id": p.id,
                "patient_name": p.user.full_name,
                "dose_name": f"مونجارو {last_dose.dose_mg:g} ملغم",
                "date": next_dose_date,
                "phone_masked": whatsapp.mask_phone(p.user.phone),
                "reminder_sent_today": WhatsAppReminder.objects.filter(
                    patient_id=p.id, reminder_type="dose", created_at__date=today,
                ).exclude(status__in=[WhatsAppReminder.FAILED, WhatsAppReminder.CANCELLED]).exists(),
            })
        upcoming_doses_payload.sort(key=lambda d: d["date"])

        return Response({
            "today_sent": today_qs.exclude(status__in=[WhatsAppReminder.DRAFT, WhatsAppReminder.FAILED, WhatsAppReminder.CANCELLED]).count(),
            "today_delivered": today_qs.filter(status__in=[WhatsAppReminder.DELIVERED, WhatsAppReminder.READ]).count(),
            "today_read": today_qs.filter(status=WhatsAppReminder.READ).count(),
            "today_failed": today_qs.filter(status=WhatsAppReminder.FAILED).count(),
            "upcoming_appointments_count": len(upcoming_appointments_payload),
            "upcoming_appointments": upcoming_appointments_payload,
            "upcoming_doses_count": len(upcoming_doses_payload),
            "upcoming_doses": upcoming_doses_payload,
        })
