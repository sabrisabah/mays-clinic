import io
from urllib.parse import quote
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.http import HttpResponse
from django.utils import timezone
from import_export import fields, resources, widgets
from import_export.admin import ImportExportModelAdmin
from .models import (
    User, Patient, Assessment, NutritionPlan, ProgressEntry, DoctorNote, LabTestEntry,
    MounjaroCorrectionLog, OzempicCorrectionLog, HealthStatusNote,
    MedicationCategory, Medication, MedicationDose, Prescription, PrescriptionItem,
    Food, Meal, MealItem,
    Service, ServiceVariant, Invoice, InvoiceItem, AuditLogEntry, NutritionAIRequestLog,
)
from reminders.models import WhatsAppReminder
from .export import build_all_patients_workbook
from .utils import compute_bmi, compute_whr, compute_whr_class, compute_activity_level, normalize_height_m, log_action

# Custom login page (silver background) — see templates/clinic/admin_login.html
admin.site.login_template = "clinic/admin_login.html"
admin.site.site_header = "عيادة دكتورة ميس الربيعي للتغذية"
admin.site.site_title = "إدارة عيادة دكتورة ميس الربيعي"
admin.site.index_title = "لوحة التحكم"


def _force_unlock_patient_deletion(patient, actor):
    """Two relations are deliberately on_delete=PROTECT against Patient,
    each for its own reason, and BOTH have to be cleared or a patient with
    either can't be deleted at all (Django's collector blocks the whole
    operation if it hits even one PROTECT anywhere in the graph):

    - clinic.Invoice.patient — "financial records are never silently
      destroyed" (see Invoice's docstring). This is what makes the
      doctor-facing delete button in the frontend correctly refuse to
      delete a patient with billing history (see clinic/views.py::
      PatientDetailView.delete).
    - reminders.WhatsAppReminder.patient — sent-message history is
      create-only/audit-only by design (WhatsAppReminderAdmin even has
      has_delete_permission return False unconditionally — see
      reminders/admin.py — which is exactly the "ليس له صلاحية حذف...
      whats app reminder" message this was built to fix).

    /admin is a different, more trusted context (Django staff/superuser
    login only, not reachable by a doctor/secretary account), and the
    clinic owner explicitly asked for an unconditional override here — so
    this deletes both before the patient/user deletion proceeds. Logs what
    it did first, since neither will exist afterward to look back at.
    """
    invoices = list(patient.invoices.all())
    reminders = list(patient.whatsapp_reminders.all())
    if not invoices and not reminders:
        return

    detail_parts = [f"حذف قسري من /admin: {patient.file_number} - {patient.user.full_name}"]
    if invoices:
        detail_parts.append(
            f"تضمّن حذف {len(invoices)} فاتورة: "
            f"{'، '.join('#' + str(i.invoice_number) for i in invoices)}"
        )
    if reminders:
        detail_parts.append(f"وحذف {len(reminders)} سجل تذكير WhatsApp")
    log_action(actor, "patient_force_deleted_admin", detail=" — ".join(detail_parts))

    if invoices:
        patient.invoices.all().delete()
    if reminders:
        patient.whatsapp_reminders.all().delete()


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
        ("معلومات شخصية", {"fields": ("full_name", "phone", "role", "profile_photo")}),
        ("صلاحيات", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "full_name", "role", "phone", "password1", "password2", "is_staff", "is_superuser"),
        }),
    )
    actions = ["force_delete_selected"]

    def force_delete_selected(self, request, queryset):
        # Django's normal delete confirmation page pre-computes the deletion
        # graph via get_deleted_objects() and refuses to even show a confirm
        # button when it hits a PROTECT relation — so overriding
        # delete_model/delete_queryset alone can't bypass this, since
        # Django never calls them in that case. An action sidesteps that
        # pre-check entirely and just does the deletes directly.
        count = 0
        for user in queryset:
            patient = getattr(user, "patient", None)
            if patient is not None:
                _force_unlock_patient_deletion(patient, request.user)
            user.delete()
            count += 1
        self.message_user(request, f"تم حذف {count} حساب نهائياً (بما في ذلك أي فواتير أو تذكيرات واتساب مرتبطة).")
    force_delete_selected.short_description = "🗑️ حذف نهائي (حتى لو مرتبط بفواتير أو أي شيء آخر)"


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ["file_number", "user", "age", "gender", "created_at"]
    search_fields = ["file_number", "user__full_name", "user__email"]
    actions = ["export_all_data", "force_delete_patients"]

    def force_delete_patients(self, request, queryset):
        # Django's normal "Delete selected patients" action pre-checks the
        # deletion graph and refuses to proceed at all once it hits a
        # PROTECT relation (Invoice.patient, WhatsAppReminder.patient) —
        # it never even reaches delete_queryset in that case, so
        # overriding that alone doesn't help. This action bypasses that
        # pre-check entirely: it clears both first (see
        # _force_unlock_patient_deletion), then deletes their login
        # account (which cascades everything else — assessment, doses,
        # notes, etc.).
        count = 0
        for patient in queryset:
            _force_unlock_patient_deletion(patient, request.user)
            patient.user.delete()
            count += 1
        self.message_user(request, f"تم حذف {count} مريض نهائياً (بما في ذلك أي فواتير أو تذكيرات واتساب مرتبطة).")
    force_delete_patients.short_description = "🗑️ حذف نهائي (حتى لو مرتبط بفواتير أو أي شيء آخر)"

    def export_all_data(self, request, queryset):
        """Bulk export (select rows above, or "تحديد كل X مريض" to grab
        everyone) — one .xlsx with 15 sheets covering every record the
        clinic holds on the selected patients: profile (incl. رقم الهاتف,
        their login identifier — actual passwords are hashed and can never
        be exported), assessment, follow-up file, progress/dose/lab logs,
        prescriptions, nutrition plans, notes, and billing. See
        clinic/export.py::build_all_patients_workbook. Only reachable here
        in /admin, which already requires Django staff/superuser login."""
        wb = build_all_patients_workbook(queryset)
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        filename = f"بيانات_المرضى_{timezone.now():%Y-%m-%d_%H%M}.xlsx"
        response = HttpResponse(
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
        return response
    export_all_data.short_description = "⬇️ تصدير كل البيانات (Excel) — كل التفاصيل + الاسم ورقم الهاتف"


class AssessmentResource(resources.ModelResource):
    """Bulk import/export of assessment forms (استمارة التقييم) as Excel,
    from within /admin only.

    - Matched/updated by the patient's رقم الملف (file_number) — the patient
      must already exist (register them first); this can't create a new
      patient/file, only fill in or bulk-edit an existing one's assessment.
    - bmi/bmi_class/whr/whr_class/activity_level are exported for reference
      but are recomputed automatically on import from
      weight/height/waist/hip/sport_days_per_week (same formulas the app
      itself uses) — editing those columns directly in the sheet has no
      effect, so the data can't drift out of sync with its inputs.
    - List-type columns (medical_history, digestive_issues, weight_loss_meds)
      are JSON arrays, e.g. ["سكري", "ضغط دم"] — keep that exact format.
    """
    file_number = fields.Field(
        column_name="file_number", attribute="patient",
        widget=widgets.ForeignKeyWidget(Patient, "file_number"),
    )
    patient_name = fields.Field(column_name="patient_name", attribute="patient__user__full_name", readonly=True)
    bmi = fields.Field(column_name="bmi", attribute="bmi", readonly=True)
    bmi_class = fields.Field(column_name="bmi_class", attribute="bmi_class", readonly=True)
    whr = fields.Field(column_name="whr", attribute="whr", readonly=True)
    whr_class = fields.Field(column_name="whr_class", attribute="whr_class", readonly=True)
    activity_level = fields.Field(column_name="activity_level", attribute="activity_level", readonly=True)

    class Meta:
        model = Assessment
        import_id_fields = ("file_number",)
        fields = (
            "id", "file_number", "patient_name", "visit_date", "checked_in", "is_submitted",
            "weight", "height", "bmi", "bmi_class", "waist", "hip", "whr", "whr_class",
            "medical_history", "medical_other", "surgeries", "food_allergy", "digestive_issues",
            "current_medications", "weight_loss_meds", "weight_loss_meds_other", "supplements",
            "activity_level", "sport_type", "sport_days_per_week", "sleep_hours", "sleep_quality", "stress_level",
            "appetite", "night_hunger", "sugar_craving", "insulin_resistance", "hormonal_symptoms",
            "meals_per_day", "snack", "eating_type", "favorite_foods", "disliked_foods",
            "water_liters", "coffee_per_day", "sugar_intake",
            "goal_type", "current_weight", "target_weight", "goal_duration", "updated_at",
        )
        export_order = fields

    def import_instance(self, instance, row, **kwargs):
        super().import_instance(instance, row, **kwargs)
        # Recompute derived fields the same way AssessmentView.put does, so a
        # bulk edit of weight/height/waist/hip can't leave stale BMI/WHR text
        # sitting in the database.
        instance.height = normalize_height_m(instance.height)
        instance.bmi, instance.bmi_class = compute_bmi(instance.weight, instance.height)
        instance.whr = compute_whr(instance.waist, instance.hip)
        instance.whr_class = compute_whr_class(instance.whr, instance.patient.gender if instance.patient_id else "")
        instance.activity_level = compute_activity_level(instance.sport_days_per_week)


@admin.register(Assessment)
class AssessmentAdmin(ImportExportModelAdmin, admin.ModelAdmin):
    resource_class = AssessmentResource
    list_display = ["patient", "goal_type", "bmi", "bmi_class", "updated_at"]
    search_fields = ["patient__file_number", "patient__user__full_name"]


@admin.register(Food)
class FoodAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "unit", "calories_per_unit", "protein_per_unit", "carbs_per_unit", "fat_per_unit", "is_active"]
    list_filter = ["category", "unit", "is_active"]
    search_fields = ["name"]


class MealItemInline(admin.TabularInline):
    model = MealItem
    extra = 0


class MealInline(admin.TabularInline):
    model = Meal
    extra = 0
    show_change_link = True


@admin.register(Meal)
class MealAdmin(admin.ModelAdmin):
    inlines = [MealItemInline]
    list_display = ["plan", "meal_type", "time", "order"]
    list_filter = ["meal_type"]


@admin.register(NutritionPlan)
class NutritionPlanAdmin(admin.ModelAdmin):
    inlines = [MealInline]
    list_display = ["patient", "version", "status", "calorie_target", "protein_pct", "carbs_pct", "fat_pct", "created_by", "updated_at"]
    list_filter = ["status"]
    search_fields = ["patient__file_number", "patient__user__full_name", "name"]


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


# ---------------- MEDICATIONS CATALOG (العلاج والوصفة الطبية) ----------------
# Main catalog is imported from the clinic's Excel reference sheet via
# `python manage.py import_medications` — /admin is only for reviewing that
# import, activating a doctor's custom (is_custom) entries so they join the
# shared picker, or making manual corrections.

class MedicationDoseInline(admin.TabularInline):
    model = MedicationDose
    extra = 1


@admin.register(MedicationCategory)
class MedicationCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "group", "type", "is_active"]
    list_filter = ["type", "group", "is_active"]
    search_fields = ["name", "group"]


@admin.register(Medication)
class MedicationAdmin(admin.ModelAdmin):
    inlines = [MedicationDoseInline]
    list_display = ["name", "category", "medication_type", "is_custom", "is_active", "created_by"]
    list_filter = ["medication_type", "is_custom", "is_active", "category"]
    search_fields = ["name", "generic_name", "brand_name"]
    # Custom (doctor-entered) medications land here inactive — flip
    # is_active on once reviewed so they appear in the shared picker for
    # every doctor, not just the one who typed it in.
    actions = ["activate_medications"]

    def activate_medications(self, request, queryset):
        queryset.update(is_active=True)
    activate_medications.short_description = "تفعيل الأدوية المحددة (إظهارها للجميع)"


class PrescriptionItemInline(admin.TabularInline):
    model = PrescriptionItem
    extra = 0
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    inlines = [PrescriptionItemInline]
    list_display = ["patient", "prescription_date", "created_by"]
    search_fields = ["patient__file_number", "patient__user__full_name"]
    date_hierarchy = "prescription_date"


# ---------------- REVENUE / BILLING ----------------

class ServiceVariantInline(admin.TabularInline):
    model = ServiceVariant
    extra = 0


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    inlines = [ServiceVariantInline]
    list_display = ["name", "category", "price", "has_variants", "is_active", "price_updated_at"]
    list_filter = ["category", "has_variants", "is_active"]
    search_fields = ["name"]


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    inlines = [InvoiceItemInline]
    list_display = ["invoice_number", "patient", "payment_status", "payment_method", "discount_pct", "is_locked", "created_by", "created_at"]
    list_filter = ["payment_status", "payment_method", "is_locked"]
    search_fields = ["invoice_number", "patient__file_number", "patient__user__full_name"]
    date_hierarchy = "created_at"
    readonly_fields = ["invoice_number", "created_at", "updated_at"]


@admin.register(AuditLogEntry)
class AuditLogEntryAdmin(admin.ModelAdmin):
    """Read-only in /admin — audit entries are create-only by design."""
    list_display = ["created_at", "action", "actor", "invoice"]
    list_filter = ["action"]
    search_fields = ["detail"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(NutritionAIRequestLog)
class NutritionAIRequestLogAdmin(admin.ModelAdmin):
    """Read-only in /admin — create-only audit trail for every "إنشاء خطة
    بالذكاء الاصطناعي" request. Deliberately has nothing sensitive to show
    (no raw prompt, no patient-identifying free text — see
    clinic/services/nutrition_ai/context.py) so it's safe to browse."""
    list_display = ["created_at", "patient", "doctor", "status", "provider", "model", "warning_count", "error_category"]
    list_filter = ["status", "provider", "error_category"]
    search_fields = ["patient__file_number", "patient__user__full_name"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MounjaroCorrectionLog)
class MounjaroCorrectionLogAdmin(admin.ModelAdmin):
    """Read-only in /admin — same create-only pattern as AuditLogEntry."""
    list_display = ["created_at", "patient", "actor", "original_dose_mg", "reason"]
    search_fields = ["patient__file_number", "patient__user__full_name", "reason"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OzempicCorrectionLog)
class OzempicCorrectionLogAdmin(admin.ModelAdmin):
    """Read-only in /admin — exact mirror of MounjaroCorrectionLogAdmin."""
    list_display = ["created_at", "patient", "actor", "original_dose_mg", "reason"]
    search_fields = ["patient__file_number", "patient__user__full_name", "reason"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(HealthStatusNote)
class HealthStatusNoteAdmin(admin.ModelAdmin):
    """Read-only in /admin — created only via the app (doctor/secretary
    "متابعة حالة صحية" section)."""
    list_display = ["created_at", "patient", "created_by"]
    search_fields = ["patient__file_number", "patient__user__full_name", "note"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
