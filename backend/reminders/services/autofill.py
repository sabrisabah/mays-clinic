"""Resolves ReminderTemplateField.auto_fill_source dot-paths (e.g.
"patient.full_name", "appointment.date", "dose.date") against a patient's
live data — pure lookups, no Meta API involved. Used to pre-fill the New
Reminder form (spec §12/§13: Smart Auto Fill); the secretary can still
review/edit anything marked `editable=True` before sending.
"""
from datetime import timedelta

from clinic.models import User


def _format_date(d):
    if not d:
        return ""
    return d.strftime("%d-%b-%Y")


def _format_time(t):
    if not t:
        return ""
    return t.strftime("%I:%M %p")


def resolve_appointment_autofill(patient):
    """Appointment/Visit/Follow-up/Test reminders all pull from the
    patient's Assessment row — this app has no standalone Appointment
    model; Assessment.visit_date IS the next booked visit (see
    AppointmentView in clinic/views.py)."""
    assessment = getattr(patient, "assessment", None)
    doctor = User.objects.filter(role="doctor", is_active=True).order_by("id").first()
    values = {
        "patient.full_name": patient.user.full_name,
        "appointment.date": "",
        "appointment.time": "",
        "appointment.doctor_name": doctor.full_name if doctor else "",
        "appointment.location": "العيادة",
        "appointment.visit_type": "",
    }
    if assessment and assessment.visit_date:
        values["appointment.date"] = _format_date(assessment.visit_date)
        values["appointment.time"] = _format_time(assessment.visit_date)
    return values


def resolve_dose_autofill(patient):
    """Dose reminders pull from the patient's most recent MounjaroDose
    entry. This app tracks doses already taken, not a future schedule, so
    the suggested NEXT dose date is last dose date + 7 days (the section
    is literally named "متابعة جرعات المونجارو الأسبوعية" — weekly
    tracking). The secretary reviews/edits this like any other auto-filled
    field before sending."""
    last_dose = patient.mounjaro_doses.order_by("-date").first()
    values = {
        "patient.full_name": patient.user.full_name,
        "dose.name": "",
        "dose.date": "",
        "dose.time": "",
        "dose.location": "العيادة",
    }
    if last_dose:
        values["dose.name"] = f"مونجارو {last_dose.dose_mg:g} ملغم"
        next_dt = last_dose.date + timedelta(days=7)
        values["dose.date"] = _format_date(next_dt)
        values["dose.time"] = _format_time(next_dt)
    return values


def resolve_custom_admin_autofill(patient):
    return {"patient.full_name": patient.user.full_name}


AUTOFILL_RESOLVERS = {
    "appointment": resolve_appointment_autofill,
    "visit": resolve_appointment_autofill,
    "followup": resolve_appointment_autofill,
    "test": resolve_appointment_autofill,
    "dose": resolve_dose_autofill,
    "custom_admin": resolve_custom_admin_autofill,
}


def resolve_autofill_values(reminder_type, patient):
    """Returns a flat {dot_path: value} dict for every known source
    relevant to `reminder_type`. A ReminderTemplateField picks out the one
    key it cares about via its own auto_fill_source."""
    resolver = AUTOFILL_RESOLVERS.get(reminder_type)
    return resolver(patient) if resolver else {"patient.full_name": patient.user.full_name}
