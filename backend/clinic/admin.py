from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Patient, Assessment, NutritionPlan, ProgressEntry, DoctorNote, LabTestEntry

# Custom login page (silver background) — see templates/clinic/admin_login.html
admin.site.login_template = "clinic/admin_login.html"
admin.site.site_header = "عيادة دكتورة ميس الربيعي للتغذية"
admin.site.site_title = "إدارة عيادة دكتورة ميس الربيعي"
admin.site.index_title = "لوحة التحكم"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Doctor accounts are created/managed here (Django admin), not via public sign-up."""
    ordering = ["email"]
    list_display = ["email", "full_name", "role", "is_staff", "is_active"]
    list_filter = ["role", "is_staff", "is_active"]
    search_fields = ["email", "full_name"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("معلومات شخصية", {"fields": ("full_name", "phone", "role")}),
        ("صلاحيات", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "full_name", "role", "phone", "password1", "password2", "is_staff", "is_superuser"),
        }),
    )


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ["file_number", "user", "age", "gender", "created_at"]
    search_fields = ["file_number", "user__full_name", "user__email"]


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ["patient", "goal_type", "bmi", "bmi_class", "updated_at"]
    search_fields = ["patient__file_number", "patient__user__full_name"]


@admin.register(NutritionPlan)
class NutritionPlanAdmin(admin.ModelAdmin):
    list_display = ["patient", "daily_calories", "protein_pct", "carbs_pct", "fat_pct", "updated_at"]
    search_fields = ["patient__file_number", "patient__user__full_name"]


@admin.register(ProgressEntry)
class ProgressEntryAdmin(admin.ModelAdmin):
    list_display = ["patient", "date", "weight", "bmi", "commitment"]
    search_fields = ["patient__file_number", "patient__user__full_name"]


@admin.register(LabTestEntry)
class LabTestEntryAdmin(admin.ModelAdmin):
    list_display = ["patient", "date", "created_by"]
    search_fields = ["patient__file_number", "patient__user__full_name"]


@admin.register(DoctorNote)
class DoctorNoteAdmin(admin.ModelAdmin):
    list_display = ["patient", "created_at", "created_by"]
    search_fields = ["patient__file_number", "patient__user__full_name"]
