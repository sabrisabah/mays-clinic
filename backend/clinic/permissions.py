from rest_framework.permissions import BasePermission


class IsDoctor(BasePermission):
    message = "هذا الإجراء متاح للطبيب فقط"

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == "doctor")
