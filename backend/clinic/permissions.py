from rest_framework.permissions import BasePermission


class IsDoctor(BasePermission):
    message = "هذا الإجراء متاح للطبيب فقط"

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == "doctor")


class IsClinicStaff(BasePermission):
    """Doctor or secretary — front-desk/clinic-staff-level access (patient
    registration & list, assessment form, follow-up file, appointment
    scheduling). Medical-only areas (nutrition plan, lab tests, Mounjaro
    doses, doctor notes) stay behind IsDoctor."""
    message = "هذا الإجراء متاح لطاقم العيادة فقط"

    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated
            and request.user.role in ("doctor", "secretary")
        )
