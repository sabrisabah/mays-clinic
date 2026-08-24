"""Named permission concepts for the Reminder Center (spec §18):
reminder.view / reminder.create / reminder.send / reminder.view_history /
reminder.manage_templates.

Implemented as plain role checks — consistent with how every other module
in this codebase does authorization (clinic/views.py uses
`if request.user.role != "x": raise PermissionDenied(...)` throughout,
not Django's Group/Permission framework). Keeping the same pattern here
means the doctor never has to learn a second, inconsistent permission
system in /admin for this one module.

Secretary: view, create, send, view_history.
Doctor: all five (implicit superset — doctor is also the only one who can
manage_templates, i.e. edit ReminderTemplate/ReminderTemplateField, done
via Django Admin — see reminders/admin.py).
Patient: none — patients have no access to this module at all.
"""


def can_view_reminders(user):
    return bool(user and user.is_authenticated and user.role in ("doctor", "secretary"))


def can_create_reminder(user):
    return bool(user and user.is_authenticated and user.role in ("doctor", "secretary"))


def can_send_reminder(user):
    return bool(user and user.is_authenticated and user.role in ("doctor", "secretary"))


def can_view_reminder_history(user):
    return bool(user and user.is_authenticated and user.role in ("doctor", "secretary"))


def can_manage_reminder_templates(user):
    return bool(user and user.is_authenticated and user.role == "doctor")
