from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from import_export import fields, resources
from import_export.admin import ImportExportModelAdmin
from .models import User, Patient, Assessment, NutritionPlan, ProgressEntry, DoctorNote, LabTestEntry

# Custom login page (silver background) — see templates/clinic/admin_login.html
admin.site.login_template = "clinic/admin_login.html"
admin.site.site_header = "عيادة دكتورة ميس الربيعي للتغذية"
admin.site.site_title = "إدارة عيادة دكتورة ميس الربيعي"
admin.site.index_title = "لوحة التحكم"


class UserResource(resources.ModelResource):
    """Bulk import/export of clinic accounts (doctor/secretary/patient logins)
    as an Excel file, from within /admin only — no separate frontend page.

    - Matched/updated by email (the login identifier for doctor/secretary;
      patients use a generated placeholder email and log in with phone).
    - The password column is import-only and never appears in an export, so
      re-importing an exported file can't leak or corrupt password hashes.
      Leave it blank to keep a user's existing password unchanged; fill it
      in with a new plain-text value to set/reset it (it's hashed on save).
    - Creating a "patient" role row here only creates the login account —
      it does NOT create their clinic file (Patient profile/رقم الملف).
      Use the "تسجيل مريض جديد" page for that instead.
    """
    password = fields.Field(attribute=None, column_name="password", readonly=True)

    class Meta:
        model = User
        import_id_fields = ("email",)
        fields = ("id", "email", "full_name", "phone", "role", "is_active", "is_staff", "date_joined", "password")
        export_order = ("id", "email", "full_name", "phone", "role", "is_active", "is_staff", "date_joined")
        clean_model_instances = True

    def import_instance(self, instance, row, **kwargs):
        super().import_instance(instance, row, **kwargs)
        # Must happen here (before validate_instance runs full_clean()), not
        # in before_save_instance — password is a required model field, so
        # leaving it unset until save time fails validation first.
        raw_password = (row.get("password") or "").strip()
        if raw_password:
            instance.set_password(raw_password)
        elif not instance.pk:
            # New user created with no password column filled in — leave the
            # account unusable until a doctor/admin sets a real password here.
            instance.set_unusable_password()


@admin.register(User)
class UserAdmin(ImportExportModelAdmin, BaseUserAdmin):
    """Doctor accounts are created/managed here (Django admin), not via public
    sign-up. Also supports bulk import/export (Excel) of accounts — see the
    "Import" / "Export" buttons above the list."""
    resource_class = UserResource
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
