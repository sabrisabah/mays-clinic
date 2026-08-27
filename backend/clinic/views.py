import io
from datetime import datetime, timedelta
from urllib.parse import quote
from django.db import IntegrityError
from django.db.models import Q, ProtectedError
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework import status

from .models import (
    User, Patient, Assessment, NutritionPlan, ProgressEntry, DoctorNote, FollowUpRecord, MounjaroDose,
    MounjaroCorrectionLog, OzempicDose, OzempicCorrectionLog, HealthStatusNote, LabTestEntry,
    MedicationCategory, Medication, MedicationDose, Prescription, PrescriptionItem,
    Food, Meal, MealItem,
    Service, ServiceVariant, Invoice, InvoiceItem, AuditLogEntry,
)
from .permissions import IsDoctor, IsClinicStaff
from .export import build_patient_workbook
from .utils import (
    compute_bmi,
    compute_whr,
    compute_whr_class,
    compute_activity_level,
    next_file_number,
    normalize_height_m,
    compute_bmr,
    compute_tdee,
    next_invoice_number,
    log_action,
)
from . import serializers as sz


def issue_token_response(user, patient_id=None):
    refresh = RefreshToken.for_user(user)
    return {
        "access_token": str(refresh.access_token),
        "token_type": "bearer",
        "role": user.role,
        "full_name": user.full_name,
        "patient_id": patient_id,
        "profile_photo_url": user.profile_photo.url if user.profile_photo else None,
    }


def get_patient_or_403(request, patient_id):
    try:
        patient = Patient.objects.select_related("user").get(id=patient_id)
    except Patient.DoesNotExist:
        raise NotFound("المريض غير موجود")
    if request.user.role == "patient" and patient.user_id != request.user.id:
        raise PermissionDenied("غير مصرح لك بالوصول لهذا الملف")
    return patient


# ---------------- AUTH ----------------

class RegisterView(APIView):
    """Public sign-up — always creates a PATIENT account, identified by phone
    number + a numeric password (PIN). Doctor accounts are created by clinic
    staff via /admin or the seed_doctor command and keep using email."""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = sz.RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Django's user model still needs a technical unique "email" internally
        # (it's the USERNAME_FIELD doctors use); patients never see or use it.
        placeholder_email = f"patient-{data['phone']}@mays.local"
        full_name = " ".join(
            part for part in [data["name_first"], data["name_father"], data.get("name_grandfather", "")] if part
        ).strip()

        user = User.objects.create_user(
            email=placeholder_email,
            password=data["password"],
            full_name=full_name,
            phone=data["phone"],
            role="patient",
        )
        patient = Patient.objects.create(
            user=user,
            file_number=next_file_number(),
            name_first=data["name_first"],
            name_father=data["name_father"],
            name_grandfather=data.get("name_grandfather", ""),
            address=data.get("address", ""),
            age=data["age"],
            gender=data["gender"],
            occupation=data.get("occupation", ""),
        )
        visit_time = data.get("visit_time") or datetime.min.time()
        visit_datetime = timezone.make_aware(datetime.combine(data["visit_date"], visit_time))
        # Weight/height are optional at registration (secretary may not have
        # them yet) — accept height in cm or m like the rest of the app, and
        # compute BMI immediately if both were given so the doctor's file
        # already shows it on first open.
        weight = data.get("weight", 0) or 0
        height = normalize_height_m(data.get("height", 0))
        bmi, bmi_class = compute_bmi(weight, height)
        Assessment.objects.create(
            patient=patient, visit_date=visit_datetime,
            weight=weight, height=height, bmi=bmi, bmi_class=bmi_class,
        )

        return Response(issue_token_response(user, patient.id), status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = sz.LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data["identifier"].strip()
        password = serializer.validated_data["password"]

        # Patients log in with their phone number; doctors log in with email.
        if "@" in identifier:
            user = User.objects.filter(email__iexact=identifier).first()
        else:
            user = User.objects.filter(phone=identifier).first()

        if not user or not user.check_password(password) or not user.is_active:
            return Response({"detail": "بيانات الدخول غير صحيحة"}, status=401)

        patient_id = None
        if user.role == "patient" and hasattr(user, "patient"):
            patient_id = user.patient.id

        return Response(issue_token_response(user, patient_id))


class MeView(APIView):
    def get(self, request):
        return Response(sz.MeSerializer(request.user).data)


# ---------------- PATIENTS ----------------

class PatientListView(APIView):
    permission_classes = [IsAuthenticated, IsClinicStaff]

    def get(self, request):
        search = request.query_params.get("search")
        qs = Patient.objects.select_related("user").order_by("-id")
        if search:
            qs = qs.filter(
                Q(user__full_name__icontains=search)
                | Q(file_number__icontains=search)
                | Q(user__phone__icontains=search)
            )

        results = []
        for p in qs:
            last_entry = p.progress_entries.order_by("-date").first()
            assessment = getattr(p, "assessment", None)
            latest_weight = last_entry.weight if last_entry else (assessment.weight if assessment else None)
            latest_bmi = last_entry.bmi if last_entry else (assessment.bmi if assessment else None)
            last_visit = last_entry.date if last_entry else (assessment.visit_date if assessment else None)
            results.append({
                "patient_id": p.id,
                "full_name": p.user.full_name,
                "age": p.age,
                "gender": p.gender,
                "phone": p.user.phone,
                "file_number": p.file_number,
                "latest_weight": latest_weight,
                "latest_bmi": latest_bmi,
                "last_visit": last_visit,
                "next_visit_at": assessment.visit_date if assessment else None,
                "checked_in": assessment.checked_in if assessment else False,
                "appointment_booked": assessment.appointment_booked if assessment else False,
                "goal_type": assessment.goal_type if assessment else "",
            })

        # Newest last-visit first (doctor's "قائمة المراجعين والمواعيد" table
        # request) — last_visit is computed above, not a DB column, so this
        # has to be a Python sort rather than an order_by(). Patients with no
        # visit at all (last_visit=None) sort to the bottom, same convention
        # used for the secretary dashboard's missing-appointment handling.
        very_old = timezone.now() - timedelta(days=365000)
        results.sort(key=lambda r: r["last_visit"] or very_old, reverse=True)

        return Response(sz.PatientListItemSerializer(results, many=True).data)


class PatientDetailView(APIView):
    def get(self, request, patient_id):
        patient = get_patient_or_403(request, patient_id)
        # First time a doctor opens this file, the case moves from front-desk
        # intake to clinical care — lock the treatment-goal section against
        # further secretary edits from this point on (see AssessmentView.put).
        if request.user.role == "doctor" and patient.doctor_first_opened_at is None:
            patient.doctor_first_opened_at = timezone.now()
            patient.save(update_fields=["doctor_first_opened_at"])
        return Response(sz.PatientProfileSerializer(patient).data)

    def put(self, request, patient_id):
        patient = get_patient_or_403(request, patient_id)
        serializer = sz.PatientProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if "name_first" in data:
            patient.name_first = data["name_first"]
        if "name_father" in data:
            patient.name_father = data["name_father"]
        if "name_grandfather" in data:
            patient.name_grandfather = data["name_grandfather"]
        if "address" in data:
            patient.address = data["address"]

        # Keep the derived single-string full_name in sync (used for login
        # greeting, admin display, JWT payload, patient list, etc.)
        if any(k in data for k in ("name_first", "name_father", "name_grandfather")):
            patient.user.full_name = " ".join(
                part for part in [patient.name_first, patient.name_father, patient.name_grandfather] if part
            ).strip()

        if "phone" in data:
            new_phone = data["phone"].strip() or None
            if new_phone and User.objects.exclude(id=patient.user_id).filter(phone=new_phone).exists():
                raise ValidationError({"phone": "رقم الهاتف مستخدم مسبقاً"})
            patient.user.phone = new_phone
        try:
            patient.user.save()
        except IntegrityError:
            raise ValidationError({"phone": "رقم الهاتف مستخدم مسبقاً"})

        if "age" in data:
            patient.age = data["age"]
        if "gender" in data:
            patient.gender = data["gender"]
        if "occupation" in data:
            patient.occupation = data["occupation"]
        patient.save()

        return Response(sz.PatientProfileSerializer(patient).data)

    def delete(self, request, patient_id):
        """Permanently deletes a patient's entire file — doctor-only,
        irreversible. Deleting patient.user (not just the Patient row)
        cascades through every clinical record tied to them (assessment,
        follow-up file, progress/dose/lab logs, prescriptions, nutrition
        plans, notes — all CASCADE from Patient). Invoice.patient is
        on_delete=PROTECT on purpose (the revenue module's whole design is
        "financial records are never silently destroyed"), so this fails
        loudly with a clear message instead of quietly cascading billing
        history away — the doctor has to resolve invoices separately first.
        """
        if request.user.role != "doctor":
            raise PermissionDenied("حذف ملف المريض متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)

        summary = f"{patient.file_number} - {patient.user.full_name}"
        try:
            patient.user.delete()
        except ProtectedError:
            raise ValidationError({
                "detail": (
                    "لا يمكن حذف هذا المريض لأن لديه فواتير مسجّلة — السجلات المالية "
                    "لا تُحذف نهائياً. راجعي الفواتير من صفحة الفواتير (إلغاء/استرداد "
                    "إن لزم) قبل حذف ملف المريض."
                )
            })
        log_action(request.user, "patient_deleted", detail=f"حذف ملف المريض بالكامل: {summary}")

        return Response(status=204)


# ---------------- ASSESSMENT ----------------

# Once a doctor has opened the patient's file (Patient.doctor_first_opened_at
# set), these treatment-goal fields become doctor-only — the secretary can
# still edit every other section of the assessment freely.
GOAL_SECTION_FIELDS = ["goal_type", "current_weight", "target_weight", "goal_duration"]


class AssessmentView(APIView):
    def get(self, request, patient_id):
        patient = get_patient_or_403(request, patient_id)
        assessment, _ = Assessment.objects.get_or_create(patient=patient)
        return Response(sz.AssessmentSerializer(assessment).data)

    def put(self, request, patient_id):
        patient = get_patient_or_403(request, patient_id)
        assessment, _ = Assessment.objects.get_or_create(patient=patient)

        # Once a patient has submitted their assessment once, it locks —
        # only a doctor can make further edits.
        if request.user.role == "patient" and assessment.is_submitted:
            raise PermissionDenied(
                "تم حفظ الاستمارة مسبقاً ولا يمكن تعديلها إلا من قبل الطبيب. يرجى التواصل مع العيادة لإجراء أي تعديل."
            )

        serializer = sz.AssessmentSerializer(assessment, data=request.data, partial=False)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Treatment-goal section locks against secretary edits once a doctor
        # has opened this patient's file — the rest of the form stays open.
        if request.user.role == "secretary" and patient.doctor_first_opened_at is not None:
            changed_goal_fields = [
                f for f in GOAL_SECTION_FIELDS
                if f in data and data[f] != getattr(assessment, f)
            ]
            if changed_goal_fields:
                raise PermissionDenied(
                    "قسم الهدف العلاجي أصبح مقفلاً بعد فتح الطبيب لملف المريض — لا يمكن للسكرتيرة تعديله. "
                    "يرجى التواصل مع الطبيب لأي تعديل على الهدف أو الوزن الحالي/المستهدف."
                )

        # "الوزن الحالي" becomes a permanent baseline the moment it's first
        # saved with a non-zero value — it's the starting weight for the
        # treatment goal, so from then on NOBODY (not even the doctor) can
        # change it through this endpoint; it just displays going forward.
        if assessment.current_weight and "current_weight" in data and data["current_weight"] != assessment.current_weight:
            raise PermissionDenied(
                "الوزن الحالي أصبح ثابتاً منذ أول حفظ له ولا يمكن تعديله لاحقاً من أي مستخدم — "
                "هو وزن البداية عند تحديد الهدف العلاجي."
            )

        # Accept height typed in cm (e.g. 170) or meters (1.70); always store meters.
        if "height" in data:
            data["height"] = normalize_height_m(data.get("height", 0))

        # BMI/WHR/activity_level are derived from weight/height/waist/hip/
        # sport_days_per_week — but the frontend now saves anthropometrics+
        # goal and the rest of the assessment as two separate partial PUTs,
        # so a field not present in THIS request doesn't mean it's 0; it
        # means "unchanged", and the derived values must be recomputed from
        # the assessment's current (possibly just-updated-above) state, not
        # from this request's payload alone.
        bmi, bmi_class = compute_bmi(
            data.get("weight", assessment.weight), data.get("height", assessment.height)
        )
        whr = compute_whr(data.get("waist", assessment.waist), data.get("hip", assessment.hip))
        whr_class = compute_whr_class(whr, patient.gender)
        activity_level = compute_activity_level(data.get("sport_days_per_week", assessment.sport_days_per_week))

        for field, value in data.items():
            setattr(assessment, field, value)
        assessment.bmi = bmi
        assessment.bmi_class = bmi_class
        assessment.whr = whr
        assessment.whr_class = whr_class
        assessment.activity_level = activity_level
        if request.user.role == "patient":
            assessment.is_submitted = True
        assessment.save()

        return Response(sz.AssessmentSerializer(assessment).data)


# ---------------- NUTRITION PLAN (خطة غذائية) ----------------
# Versioned/append-only like Prescription: approving a plan (status=Active)
# locks it — further edits go through "revise" (clones a new Draft) rather
# than mutating the approved record. Doctor-only end to end, except the
# patient's own read-only access to their current Active plan.

MEAL_TYPES_ORDER = ["فطور", "سناك1", "غداء", "سناك2", "عشاء"]


def _snapshot_bmr_tdee(patient, activity_level):
    """Computes BMR/TDEE from the patient's latest assessment weight/height
    and Patient.age/gender. Returns (bmr, tdee) — both 0 if there isn't
    enough data yet (assessment not filled in)."""
    assessment = getattr(patient, "assessment", None)
    weight = assessment.weight if assessment else 0
    height = assessment.height if assessment else 0
    bmr = compute_bmr(weight, height, patient.age, patient.gender)
    tdee = compute_tdee(bmr, activity_level)
    return bmr, tdee


def _create_plan_with_meals(patient, data, created_by, version=1, parent_plan=None):
    activity_level = data.get("activity_level", "")
    bmr, tdee = _snapshot_bmr_tdee(patient, activity_level)
    plan = NutritionPlan.objects.create(
        patient=patient,
        created_by=created_by,
        version=version,
        parent_plan=parent_plan,
        bmr=bmr, tdee=tdee,
        **{k: v for k, v in data.items() if k not in ("id", "status", "version", "parent_plan", "bmr", "tdee")}
    )
    for i, meal_type in enumerate(MEAL_TYPES_ORDER):
        Meal.objects.create(plan=plan, meal_type=meal_type, order=i)
    return plan


def _get_plan_or_404(patient, plan_id):
    try:
        return patient.nutrition_plans.get(id=plan_id)
    except NutritionPlan.DoesNotExist:
        raise NotFound("الخطة الغذائية غير موجودة")


def _require_draft(plan):
    if plan.status != NutritionPlan.DRAFT:
        raise PermissionDenied("لا يمكن تعديل خطة معتمدة أو مؤرشفة — استخدم 'إنشاء نسخة معدّلة' لتعديلها")


class FoodListCreateView(APIView):
    def get(self, request):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        foods = Food.objects.filter(is_active=True)
        return Response(sz.FoodSerializer(foods, many=True).data)

    def post(self, request):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        serializer = sz.FoodSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        food = serializer.save(created_by=request.user)
        return Response(sz.FoodSerializer(food).data, status=status.HTTP_201_CREATED)


class NutritionPlanListCreateView(APIView):
    def get(self, request, patient_id):
        patient = get_patient_or_403(request, patient_id)
        if request.user.role == "patient":
            plans = patient.nutrition_plans.filter(status=NutritionPlan.ACTIVE)
        elif request.user.role == "doctor":
            plans = patient.nutrition_plans.all()
        else:
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        plans = plans.prefetch_related("meals__items")
        return Response(sz.NutritionPlanSerializer(plans, many=True, context={"request": request}).data)

    def post(self, request, patient_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)

        serializer = sz.NutritionPlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = _create_plan_with_meals(patient, serializer.validated_data, request.user)
        plan = patient.nutrition_plans.prefetch_related("meals__items").get(id=plan.id)
        return Response(sz.NutritionPlanSerializer(plan, context={"request": request}).data, status=status.HTTP_201_CREATED)


class NutritionPlanDetailView(APIView):
    def get(self, request, patient_id, plan_id):
        patient = get_patient_or_403(request, patient_id)
        plan = _get_plan_or_404(patient, plan_id)
        if request.user.role == "patient" and plan.status != NutritionPlan.ACTIVE:
            raise PermissionDenied("غير مصرح بعرض هذه الخطة")
        return Response(sz.NutritionPlanSerializer(plan, context={"request": request}).data)

    def put(self, request, patient_id, plan_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        plan = _get_plan_or_404(patient, plan_id)
        _require_draft(plan)

        serializer = sz.NutritionPlanSerializer(plan, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "activity_level" in data and data["activity_level"] != plan.activity_level:
            data["bmr"], data["tdee"] = _snapshot_bmr_tdee(patient, data["activity_level"])
        plan = serializer.save(**{k: data[k] for k in ("bmr", "tdee") if k in data})
        return Response(sz.NutritionPlanSerializer(plan).data)


class NutritionPlanActionView(APIView):
    """Handles the plan-level actions from the spec's 'Plan actions' row:
    approve (lock + auto-archive any other Active plan for this patient),
    archive, duplicate (clone as a new Draft, version resets to 1, no
    parent), and revise (clone as a new Draft version+1 with parent_plan set
    — the only way to edit an Active/Archived plan's content)."""
    def post(self, request, patient_id, plan_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        plan = _get_plan_or_404(patient, plan_id)
        action = request.data.get("action")

        if action == "approve":
            _require_draft(plan)
            serialized = sz.NutritionPlanSerializer(plan).data
            errors = {}
            if serialized["requires_target_reason"] and not (plan.target_reason or "").strip():
                errors["target_reason"] = "الفرق عن TDEE كبير — الرجاء توضيح السبب السريري قبل الاعتماد"
            if serialized["requires_special_pathway_notes"] and not (plan.special_pathway_notes or "").strip():
                errors["special_pathway_notes"] = "المريض ضمن فئة تتطلب مساراً سريرياً خاصاً (حمل/رضاعة/خطر اضطراب أكل/عدم استقرار طبي/تحت 18 سنة) — الرجاء توثيق الملاحظات قبل الاعتماد"
            if errors:
                raise ValidationError(errors)
            patient.nutrition_plans.filter(status=NutritionPlan.ACTIVE).update(status=NutritionPlan.ARCHIVED)
            plan.status = NutritionPlan.ACTIVE
            plan.approved_at = timezone.now()
            plan.save(update_fields=["status", "approved_at"])

        elif action == "archive":
            plan.status = NutritionPlan.ARCHIVED
            plan.save(update_fields=["status"])

        elif action in ("duplicate", "revise"):
            is_revise = action == "revise"
            new_plan = NutritionPlan.objects.create(
                patient=patient,
                created_by=request.user,
                version=(plan.version + 1) if is_revise else 1,
                parent_plan=plan if is_revise else None,
                name=plan.name, start_date=plan.start_date,
                duration_value=plan.duration_value, duration_unit=plan.duration_unit,
                treatment_objective=plan.treatment_objective,
                activity_level=plan.activity_level, bmr=plan.bmr, tdee=plan.tdee,
                calorie_target=plan.calorie_target, target_reason=plan.target_reason,
                protein_pct=plan.protein_pct, carbs_pct=plan.carbs_pct, fat_pct=plan.fat_pct,
                protein_grams_override=plan.protein_grams_override,
                is_pregnant=plan.is_pregnant, is_lactating=plan.is_lactating,
                eating_disorder_risk=plan.eating_disorder_risk, medically_unstable=plan.medically_unstable,
                special_pathway_notes=plan.special_pathway_notes,
                plan_notes=plan.plan_notes, patient_notes=plan.patient_notes,
            )
            for meal in plan.meals.all():
                new_meal = Meal.objects.create(plan=new_plan, meal_type=meal.meal_type, time=meal.time, order=meal.order)
                for item in meal.items.all():
                    MealItem.objects.create(
                        meal=new_meal, food=item.food, custom_food_name=item.custom_food_name,
                        quantity=item.quantity, unit=item.unit, food_state=item.food_state,
                        calories=item.calories, protein=item.protein, carbs=item.carbs, fat=item.fat,
                        alternative_text=item.alternative_text, instructions=item.instructions,
                        patient_visible=item.patient_visible, order=item.order,
                    )
            plan = new_plan
        else:
            raise ValidationError({"action": "إجراء غير معروف"})

        plan = patient.nutrition_plans.prefetch_related("meals__items").get(id=plan.id)
        return Response(sz.NutritionPlanSerializer(plan).data)


class MealDetailView(APIView):
    def put(self, request, patient_id, plan_id, meal_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        plan = _get_plan_or_404(patient, plan_id)
        _require_draft(plan)
        try:
            meal = plan.meals.get(id=meal_id)
        except Meal.DoesNotExist:
            raise NotFound("الوجبة غير موجودة")
        serializer = sz.MealSerializer(meal, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class MealItemListCreateView(APIView):
    def post(self, request, patient_id, plan_id, meal_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        plan = _get_plan_or_404(patient, plan_id)
        _require_draft(plan)
        try:
            meal = plan.meals.get(id=meal_id)
        except Meal.DoesNotExist:
            raise NotFound("الوجبة غير موجودة")
        serializer = sz.MealItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = serializer.save(meal=meal)
        return Response(sz.MealItemSerializer(item).data, status=status.HTTP_201_CREATED)


class MealItemDetailView(APIView):
    def _get_item(self, patient, plan_id, meal_id, item_id):
        plan = _get_plan_or_404(patient, plan_id)
        try:
            return plan, MealItem.objects.get(id=item_id, meal_id=meal_id, meal__plan=plan)
        except MealItem.DoesNotExist:
            raise NotFound("الصنف غير موجود")

    def put(self, request, patient_id, plan_id, meal_id, item_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        plan, item = self._get_item(patient, plan_id, meal_id, item_id)
        _require_draft(plan)
        serializer = sz.MealItemSerializer(item, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, patient_id, plan_id, meal_id, item_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        plan, item = self._get_item(patient, plan_id, meal_id, item_id)
        _require_draft(plan)
        item.delete()
        return Response({"ok": True})


# ---------------- FOLLOW-UP RECORD ----------------

class FollowUpRecordView(APIView):
    """Doctor's clinical follow-up file. Viewable by both roles (read-only
    for the patient); only a doctor may create/edit it."""

    def get(self, request, patient_id):
        patient = get_patient_or_403(request, patient_id)
        record, _ = FollowUpRecord.objects.get_or_create(patient=patient)
        return Response(sz.FollowUpRecordSerializer(record).data)

    def put(self, request, patient_id):
        if request.user.role not in ("doctor", "secretary"):
            raise PermissionDenied("هذا الإجراء متاح لطاقم العيادة فقط")
        patient = get_patient_or_403(request, patient_id)
        record, _ = FollowUpRecord.objects.get_or_create(patient=patient)

        serializer = sz.FollowUpRecordSerializer(record, data=request.data)
        serializer.is_valid(raise_exception=True)
        record = serializer.save(created_by=request.user)

        # Setting "المتابعة بعد ___ يوم/أسبوع" here is how doctors/secretaries
        # actually expect to book the next visit — not just an informational
        # estimate. So automatically (re)book the real appointment (same
        # fields the secretary's "حفظ الموعد" button sets) from today +
        # the interval, so it shows up immediately on the secretary dashboard
        # without a second manual step. Only acts when an interval was given;
        # clearing it back to 0 doesn't touch any appointment already booked.
        if record.followup_interval_value and record.followup_interval_value > 0:
            days = (
                record.followup_interval_value * 7
                if record.followup_interval_unit == "أسبوع"
                else record.followup_interval_value
            )
            assessment, _ = Assessment.objects.get_or_create(patient=patient)
            assessment.visit_date = timezone.now() + timedelta(days=days)
            assessment.checked_in = False
            assessment.appointment_booked = True
            assessment.appointment_booked_at = timezone.now()
            assessment.save(update_fields=["visit_date", "checked_in", "appointment_booked", "appointment_booked_at"])

        return Response(sz.FollowUpRecordSerializer(record).data)


# ---------------- APPOINTMENT SCHEDULING ----------------
# Doctor/secretary-only: (re)schedule a patient's next visit date+time, and
# mark them as checked-in/arrived. Powers the front-desk schedule and the
# "patient hasn't arrived" red alert on the secretary/doctor dashboards.

class AppointmentView(APIView):
    def put(self, request, patient_id):
        if request.user.role not in ("doctor", "secretary"):
            raise PermissionDenied("هذا الإجراء متاح لطاقم العيادة فقط")
        patient = get_patient_or_403(request, patient_id)
        assessment, _ = Assessment.objects.get_or_create(patient=patient)

        serializer = sz.AppointmentUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        visit_time = data.get("visit_time") or datetime.min.time()
        assessment.visit_date = timezone.make_aware(datetime.combine(data["visit_date"], visit_time))
        assessment.checked_in = False
        assessment.appointment_booked = True
        assessment.appointment_booked_at = timezone.now()
        assessment.save(update_fields=["visit_date", "checked_in", "appointment_booked", "appointment_booked_at"])

        return Response({
            "visit_date": assessment.visit_date,
            "checked_in": assessment.checked_in,
            "appointment_booked": assessment.appointment_booked,
        })

    def post(self, request, patient_id):
        # Mark the patient as arrived — dismisses the "hasn't shown up" alert.
        if request.user.role not in ("doctor", "secretary"):
            raise PermissionDenied("هذا الإجراء متاح لطاقم العيادة فقط")
        patient = get_patient_or_403(request, patient_id)
        assessment, _ = Assessment.objects.get_or_create(patient=patient)
        assessment.checked_in = True
        assessment.save(update_fields=["checked_in"])
        return Response({"visit_date": assessment.visit_date, "checked_in": assessment.checked_in})


# ---------------- PROGRESS ----------------

class ProgressListView(APIView):
    def get(self, request, patient_id):
        patient = get_patient_or_403(request, patient_id)
        entries = patient.progress_entries.order_by("date")
        return Response(sz.ProgressEntrySerializer(entries, many=True).data)

    def post(self, request, patient_id):
        # Secretary can also log a follow-up weigh-in from her consolidated
        # "ملف المتابعة" tab (متابعة وزن) — deletion stays doctor-only below.
        if request.user.role not in ("doctor", "secretary"):
            raise PermissionDenied("هذا الإجراء متاح لطاقم العيادة فقط")
        patient = get_patient_or_403(request, patient_id)

        serializer = sz.ProgressEntryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        height = patient.assessment.height if hasattr(patient, "assessment") else 0
        bmi, _ = compute_bmi(data["weight"], height)

        entry = ProgressEntry.objects.create(
            patient=patient,
            weight=data["weight"],
            bmi=bmi,
            notes=data.get("notes", ""),
            commitment=data.get("commitment", ""),
            created_by=request.user,
        )
        return Response(sz.ProgressEntrySerializer(entry).data, status=status.HTTP_201_CREATED)


class ProgressDeleteView(APIView):
    def delete(self, request, patient_id, entry_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        ProgressEntry.objects.filter(id=entry_id, patient=patient).delete()
        return Response({"ok": True})


# ---------------- MOUNJARO DOSE TRACKING ----------------
# Weekly weight + dose log for patients on Mounjaro. Both doctor and
# secretary can log entries and adjust the dose (full parity — the
# secretary is often the one doing the weekly weigh-in/injection); the
# patient can only view their own log read-only. A secretary deleting an
# entry must document why — logged to MounjaroCorrectionLog, doctor-only
# visible — a doctor's own deletions need no reason and aren't logged.

class MounjaroDoseListView(APIView):
    def get(self, request, patient_id):
        patient = get_patient_or_403(request, patient_id)
        entries = patient.mounjaro_doses.order_by("-date")  # newest first
        return Response(sz.MounjaroDoseSerializer(entries, many=True).data)

    def post(self, request, patient_id):
        if request.user.role not in ("doctor", "secretary"):
            raise PermissionDenied("هذا الإجراء متاح للطبيب أو السكرتيرة فقط")
        patient = get_patient_or_403(request, patient_id)

        serializer = sz.MounjaroDoseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        entry = MounjaroDose.objects.create(
            patient=patient,
            weight=data["weight"],
            dose_mg=data["dose_mg"],
            notes=data.get("notes", ""),
            created_by=request.user,
        )
        return Response(sz.MounjaroDoseSerializer(entry).data, status=status.HTTP_201_CREATED)


class MounjaroDoseDetailView(APIView):
    # In-place editing (weight/dose/notes on an existing entry) is doctor-only
    # — the secretary's write access stays limited to adding new entries and
    # deleting (with a documented reason); she doesn't rewrite history.
    # A doctor edit needs no reason and isn't logged, same as a doctor delete.
    def put(self, request, patient_id, entry_id):
        if request.user.role != "doctor":
            raise PermissionDenied("تعديل سجل موجود متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        try:
            entry = MounjaroDose.objects.get(id=entry_id, patient=patient)
        except MounjaroDose.DoesNotExist:
            raise NotFound("السجل غير موجود")

        serializer = sz.MounjaroDoseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        entry.weight = data["weight"]
        entry.dose_mg = data["dose_mg"]
        entry.notes = data.get("notes", "")
        entry.save(update_fields=["weight", "dose_mg", "notes"])
        return Response(sz.MounjaroDoseSerializer(entry).data)

    def delete(self, request, patient_id, entry_id):
        if request.user.role not in ("doctor", "secretary"):
            raise PermissionDenied("هذا الإجراء متاح للطبيب أو السكرتيرة فقط")
        patient = get_patient_or_403(request, patient_id)
        try:
            entry = MounjaroDose.objects.get(id=entry_id, patient=patient)
        except MounjaroDose.DoesNotExist:
            return Response({"ok": True})

        if request.user.role == "secretary":
            reason = request.data.get("reason", "").strip()
            if not reason:
                raise ValidationError({"reason": "سبب حذف/تصحيح السجل مطلوب"})
            MounjaroCorrectionLog.objects.create(
                patient=patient,
                actor=request.user,
                original_date=entry.date,
                original_weight=entry.weight,
                original_dose_mg=entry.dose_mg,
                reason=reason,
            )

        entry.delete()
        return Response({"ok": True})


class MounjaroCorrectionLogListView(APIView):
    def get(self, request, patient_id):
        if request.user.role != "doctor":
            raise PermissionDenied("سجل التصحيحات متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        logs = patient.mounjaro_corrections.select_related("actor")
        return Response(sz.MounjaroCorrectionLogSerializer(logs, many=True).data)


# ---------------- OZEMPIC DOSE TRACKING ----------------
# Exact structural mirror of MOUNJARO DOSE TRACKING above, for the
# secretary's consolidated "ملف المتابعة" tab (متابعة أوزمبك). Same
# permission model: doctor+secretary can add, only doctor can edit in
# place, secretary deletions require a documented reason logged to
# OzempicCorrectionLog (doctor-only visible), doctor deletions are
# unlogged.

class OzempicDoseListView(APIView):
    def get(self, request, patient_id):
        patient = get_patient_or_403(request, patient_id)
        entries = patient.ozempic_doses.order_by("-date")  # newest first
        return Response(sz.OzempicDoseSerializer(entries, many=True).data)

    def post(self, request, patient_id):
        if request.user.role not in ("doctor", "secretary"):
            raise PermissionDenied("هذا الإجراء متاح للطبيب أو السكرتيرة فقط")
        patient = get_patient_or_403(request, patient_id)

        serializer = sz.OzempicDoseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        entry = OzempicDose.objects.create(
            patient=patient,
            weight=data["weight"],
            dose_mg=data["dose_mg"],
            pen_strength=data.get("pen_strength", ""),
            notes=data.get("notes", ""),
            created_by=request.user,
        )
        return Response(sz.OzempicDoseSerializer(entry).data, status=status.HTTP_201_CREATED)


class OzempicDoseDetailView(APIView):
    def put(self, request, patient_id, entry_id):
        if request.user.role != "doctor":
            raise PermissionDenied("تعديل سجل موجود متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        try:
            entry = OzempicDose.objects.get(id=entry_id, patient=patient)
        except OzempicDose.DoesNotExist:
            raise NotFound("السجل غير موجود")

        serializer = sz.OzempicDoseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        entry.weight = data["weight"]
        entry.dose_mg = data["dose_mg"]
        entry.pen_strength = data.get("pen_strength", "")
        entry.notes = data.get("notes", "")
        entry.save(update_fields=["weight", "dose_mg", "pen_strength", "notes"])
        return Response(sz.OzempicDoseSerializer(entry).data)

    def delete(self, request, patient_id, entry_id):
        if request.user.role not in ("doctor", "secretary"):
            raise PermissionDenied("هذا الإجراء متاح للطبيب أو السكرتيرة فقط")
        patient = get_patient_or_403(request, patient_id)
        try:
            entry = OzempicDose.objects.get(id=entry_id, patient=patient)
        except OzempicDose.DoesNotExist:
            return Response({"ok": True})

        if request.user.role == "secretary":
            reason = request.data.get("reason", "").strip()
            if not reason:
                raise ValidationError({"reason": "سبب حذف/تصحيح السجل مطلوب"})
            OzempicCorrectionLog.objects.create(
                patient=patient,
                actor=request.user,
                original_date=entry.date,
                original_weight=entry.weight,
                original_dose_mg=entry.dose_mg,
                reason=reason,
            )

        entry.delete()
        return Response({"ok": True})


class OzempicCorrectionLogListView(APIView):
    def get(self, request, patient_id):
        if request.user.role != "doctor":
            raise PermissionDenied("سجل التصحيحات متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        logs = patient.ozempic_corrections.select_related("actor")
        return Response(sz.OzempicCorrectionLogSerializer(logs, many=True).data)


# ---------------- HEALTH STATUS NOTES ----------------
# Simple free-text log for the secretary's consolidated "ملف المتابعة" tab
# (متابعة حالة صحية) — both doctor and secretary can add/view; append-only,
# no edit/delete (same create-only spirit as ProgressEntry/LabTestEntry).

class HealthStatusNoteListView(APIView):
    def get(self, request, patient_id):
        patient = get_patient_or_403(request, patient_id)
        notes = patient.health_status_notes.select_related("created_by")
        return Response(sz.HealthStatusNoteSerializer(notes, many=True).data)

    def post(self, request, patient_id):
        if request.user.role not in ("doctor", "secretary"):
            raise PermissionDenied("هذا الإجراء متاح للطبيب أو السكرتيرة فقط")
        patient = get_patient_or_403(request, patient_id)
        note_text = request.data.get("note", "").strip()
        if not note_text:
            raise ValidationError({"note": "الملاحظة مطلوبة"})
        note = HealthStatusNote.objects.create(patient=patient, note=note_text, created_by=request.user)
        return Response(sz.HealthStatusNoteSerializer(note).data, status=status.HTTP_201_CREATED)


# ---------------- NEXT FOLLOW-UP DATE ----------------
# A simple, separate "موعد المتابعة القادمة" note field on Patient — distinct
# from Assessment.visit_date/appointment_booked (the actual appointment-
# booking mechanism used elsewhere). Secretary-managed from her
# consolidated "ملف المتابعة" tab.

class NextFollowupDateView(APIView):
    def put(self, request, patient_id):
        if request.user.role not in ("doctor", "secretary"):
            raise PermissionDenied("هذا الإجراء متاح للطبيب أو السكرتيرة فقط")
        patient = get_patient_or_403(request, patient_id)
        serializer = sz.NextFollowupDateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        patient.next_followup_date = serializer.validated_data["next_followup_date"]
        patient.save(update_fields=["next_followup_date"])
        return Response({"next_followup_date": patient.next_followup_date})


# ---------------- LAB TEST TRACKING (monthly, doctor-only) ----------------
# Labs get repeated roughly every month, so this is a historical log (like
# ProgressEntry/MounjaroDose) rather than a single overwritten snapshot.
# Unlike those, this is doctor-only end to end — not shown to the patient.

class LabTestEntryListView(APIView):
    def get(self, request, patient_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        entries = patient.lab_test_entries.order_by("date")
        return Response(sz.LabTestEntrySerializer(entries, many=True).data)

    def post(self, request, patient_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)

        serializer = sz.LabTestEntryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        entry = LabTestEntry.objects.create(
            patient=patient,
            lab_results=data.get("lab_results", {}),
            other_notes=data.get("other_notes", ""),
            created_by=request.user,
        )
        return Response(sz.LabTestEntrySerializer(entry).data, status=status.HTTP_201_CREATED)


class LabTestEntryDeleteView(APIView):
    def delete(self, request, patient_id, entry_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        LabTestEntry.objects.filter(id=entry_id, patient=patient).delete()
        return Response({"ok": True})


# ---------------- DOCTOR NOTES ----------------
# Written by the doctor, but visible (read-only) to the patient on their own
# profile. Only a doctor may create, edit, or delete a note.

class NotesListView(APIView):
    def get(self, request, patient_id):
        # get_patient_or_403 already restricts a patient to their own record;
        # a doctor may view any patient's notes.
        patient = get_patient_or_403(request, patient_id)
        notes = patient.notes.order_by("-created_at")
        return Response(sz.DoctorNoteSerializer(notes, many=True).data)

    def post(self, request, patient_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        note_text = request.data.get("note", "").strip()
        if not note_text:
            raise ValidationError({"note": "الملاحظة مطلوبة"})
        note = DoctorNote.objects.create(patient=patient, note=note_text, created_by=request.user)
        return Response(sz.DoctorNoteSerializer(note).data, status=status.HTTP_201_CREATED)


class NoteDetailView(APIView):
    def put(self, request, patient_id, note_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        note_text = request.data.get("note", "").strip()
        if not note_text:
            raise ValidationError({"note": "الملاحظة مطلوبة"})
        try:
            note = DoctorNote.objects.get(id=note_id, patient=patient)
        except DoctorNote.DoesNotExist:
            raise NotFound("الملاحظة غير موجودة")
        note.note = note_text
        note.save()
        return Response(sz.DoctorNoteSerializer(note).data)

    def delete(self, request, patient_id, note_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        DoctorNote.objects.filter(id=note_id, patient=patient).delete()
        return Response({"ok": True})


# ---------------- DOCTOR DASHBOARD — PERIOD STATS ----------------
# Powers the doctor dashboard's "إحصائيات الفترة" section: activity counts
# filterable by week / month / year, computed from whatever dated record
# best represents each metric (see comments below).

class DoctorDashboardStatsView(APIView):
    permission_classes = [IsAuthenticated, IsClinicStaff]

    PERIOD_DAYS = {"week": 7, "month": 30, "year": 365}

    def get(self, request):
        period = request.query_params.get("period", "month")
        days = self.PERIOD_DAYS.get(period, 30)
        since = timezone.now() - timedelta(days=days)

        # Patients registered within the period (Patient.created_at). This is
        # also the base population for the BMI-classification and
        # treatment-goal breakdowns below, so all of these numbers describe
        # "of the patients who joined in this period, how many are ...".
        period_patients = Patient.objects.filter(created_at__gte=since)
        total_patients = period_patients.count()

        obese = overweight = normal = underweight = 0
        goal_counts = {"نزول وزن": 0, "زيادة وزن": 0, "تثبيت": 0, "تحسين صحي": 0}
        for pt in period_patients.select_related("assessment"):
            last_entry = pt.progress_entries.order_by("-date").first()
            assessment = getattr(pt, "assessment", None)
            bmi = last_entry.bmi if last_entry else (assessment.bmi if assessment else None)
            if bmi:
                if bmi >= 30:
                    obese += 1
                elif bmi >= 25:
                    overweight += 1
                elif bmi >= 18.5:
                    normal += 1
                else:
                    underweight += 1
            if assessment and assessment.goal_type in goal_counts:
                goal_counts[assessment.goal_type] += 1

        # Appointments actually booked/rebooked in the period — uses
        # appointment_booked_at (when the booking action happened), not
        # visit_date (when the visit itself is scheduled to occur).
        bookings = Assessment.objects.filter(
            appointment_booked=True, appointment_booked_at__gte=since
        ).count()

        # Distinct patients with a follow-up weight-tracking entry in the
        # period (ProgressEntry is created every time a follow-up visit is
        # logged).
        followups = ProgressEntry.objects.filter(date__gte=since).values("patient_id").distinct().count()

        # Distinct patients with a Mounjaro dose logged in the period.
        mounjaro = MounjaroDose.objects.filter(date__gte=since).values("patient_id").distinct().count()

        # Ozempic / diet-plan / fat-dissolving patients: there's no separate
        # dated log for these (unlike Mounjaro/ProgressEntry), so we use each
        # patient's follow-up record and treat "updated_at within the period"
        # as a proxy for "seen/updated during this window". This can miss a
        # patient if their record was set up before the window and never
        # touched again, but is the best signal available without adding new
        # tracking tables.
        recent_followups = FollowUpRecord.objects.filter(updated_at__gte=since)
        ozempic = sum(1 for f in recent_followups if "أوزمبك" in (f.treatment_injections or []))
        diet = sum(1 for f in recent_followups if (f.diet_type or "").strip())
        fat_burning = sum(
            1 for f in recent_followups
            if f.treatment_fat_burning_sessions or "إبر تذويب" in (f.treatment_injections or [])
        )

        return Response({
            "period": period,
            "total_patients": total_patients,
            "obese": obese,
            "overweight": overweight,
            "normal": normal,
            "underweight": underweight,
            "goal_loss": goal_counts["نزول وزن"],
            "goal_gain": goal_counts["زيادة وزن"],
            "goal_maintain": goal_counts["تثبيت"],
            "goal_health": goal_counts["تحسين صحي"],
            "bookings": bookings,
            "followups": followups,
            "mounjaro": mounjaro,
            "ozempic": ozempic,
            "diet": diet,
            "fat_burning": fat_burning,
        })


# ---------------- MEDICATIONS / PRESCRIPTIONS (العلاج والوصفة الطبية) ----------------
# Lives inside the doctor's "ملف المتابعة" tab for a patient. Prescriptions
# are an append-only dated log (like MounjaroDose/LabTestEntry) so the full
# treatment history survives every new visit — never overwritten in place.
# Viewing is clinic-staff level (doctor + secretary); writing is doctor-only.

class MedicationCatalogView(APIView):
    """Full nested catalog (category -> medications -> doses), loaded once by
    the frontend and filtered client-side for the cascading dropdowns —
    the catalog is small enough (~90 medications) that this is simpler and
    faster than several round trips per keystroke."""
    def get(self, request):
        if request.user.role not in ("doctor", "secretary"):
            raise PermissionDenied("هذا الإجراء متاح لطاقم العيادة فقط")
        categories = (
            MedicationCategory.objects.filter(is_active=True)
            .prefetch_related("medications__doses")
            .order_by("group", "name")
        )
        return Response(sz.MedicationCategorySerializer(categories, many=True).data)


class CustomMedicationCreateView(APIView):
    """'+ إضافة دواء أو مكمل غير موجود بالقائمة' — creates an inactive,
    doctor-specific Medication row (is_custom=True) that this prescription
    can reference immediately, without appearing in other doctors' pickers
    until an admin activates it from /admin."""
    def post(self, request):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        serializer = sz.CustomMedicationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        medication = Medication.objects.create(
            name=data["name"],
            medication_type=data["medication_type"],
            is_custom=True,
            is_active=False,
            created_by=request.user,
        )
        dose = None
        if data.get("dose"):
            dose = MedicationDose.objects.create(
                medication=medication, dose_value=data["dose"], dose_unit=data.get("unit", ""),
            )
        return Response({
            "medication": sz.MedicationCatalogSerializer(medication).data,
            "dose_id": dose.id if dose else None,
        }, status=status.HTTP_201_CREATED)


class PrescriptionListCreateView(APIView):
    def get(self, request, patient_id):
        if request.user.role not in ("doctor", "secretary"):
            raise PermissionDenied("هذا الإجراء متاح لطاقم العيادة فقط")
        patient = get_patient_or_403(request, patient_id)
        prescriptions = patient.prescriptions.prefetch_related(
            "items", "items__medication", "items__medication_dose"
        )
        return Response(sz.PrescriptionSerializer(prescriptions, many=True).data)

    def post(self, request, patient_id):
        """Creates a new prescription ('visit'). With `copy_from` set to a
        previous prescription's id, its items are copied over (fresh ids,
        status reset to مستمر) so the doctor can then edit/remove/add before
        the visit is done — implements 'نسخ الوصفة السابقة'."""
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)

        prescription = Prescription.objects.create(
            patient=patient,
            general_notes=(request.data.get("general_notes") or "").strip(),
            created_by=request.user,
        )

        copy_from_id = request.data.get("copy_from")
        if copy_from_id:
            try:
                source = patient.prescriptions.get(id=copy_from_id)
            except Prescription.DoesNotExist:
                raise NotFound("الوصفة المطلوب نسخها غير موجودة")
            for item in source.items.all():
                PrescriptionItem.objects.create(
                    prescription=prescription,
                    medication=item.medication,
                    medication_dose=item.medication_dose,
                    custom_medication_name=item.custom_medication_name,
                    custom_dose=item.custom_dose,
                    route=item.route,
                    frequency=item.frequency,
                    timing=item.timing,
                    duration_value=item.duration_value,
                    duration_unit=item.duration_unit,
                    start_date=item.start_date,
                    end_date=item.end_date,
                    quantity=item.quantity,
                    instructions=item.instructions,
                    notes=item.notes,
                    treatment_status="مستمر",
                )

        prescription.refresh_from_db()
        return Response(sz.PrescriptionSerializer(prescription).data, status=status.HTTP_201_CREATED)


class PrescriptionItemListCreateView(APIView):
    def post(self, request, patient_id, prescription_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        try:
            prescription = patient.prescriptions.get(id=prescription_id)
        except Prescription.DoesNotExist:
            raise NotFound("الوصفة غير موجودة")

        serializer = sz.PrescriptionItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = serializer.save(prescription=prescription)
        return Response(sz.PrescriptionItemSerializer(item).data, status=status.HTTP_201_CREATED)


class PrescriptionItemDetailView(APIView):
    def _get_item(self, patient, prescription_id, item_id):
        try:
            return PrescriptionItem.objects.get(
                id=item_id, prescription_id=prescription_id, prescription__patient=patient
            )
        except PrescriptionItem.DoesNotExist:
            raise NotFound("العلاج غير موجود")

    def put(self, request, patient_id, prescription_id, item_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        item = self._get_item(patient, prescription_id, item_id)
        serializer = sz.PrescriptionItemSerializer(item, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, patient_id, prescription_id, item_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        item = self._get_item(patient, prescription_id, item_id)
        item.delete()
        return Response({"ok": True})


# ---------------- REVENUE / BILLING (نظام الإيرادات) ----------------
# Doctor: full access (services/prices, discount approval, cancel/refund,
# reports). Secretary: create invoices, record payments, apply a discount
# (must name a doctor who approved it), print receipts — but can never edit
# a locked (fully paid) invoice, cancel, refund, or see the reports
# dashboard. Patients have no access to this module at all.

CONSULTATION_SERVICE_NAME = "كشفية الطبيب"


class DoctorListView(APIView):
    """Minimal read-only roster of active doctor accounts — powers the
    'من وافق على الخصم' picker when a secretary applies a discount."""
    permission_classes = [IsAuthenticated, IsClinicStaff]

    def get(self, request):
        doctors = User.objects.filter(role="doctor", is_active=True).order_by("full_name")
        return Response([{"id": d.id, "full_name": d.full_name} for d in doctors])


class ServiceListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsClinicStaff]

    def get(self, request):
        services = Service.objects.prefetch_related("variants")
        if not (request.user.role == "doctor" and request.query_params.get("all")):
            services = services.filter(is_active=True)
        return Response(sz.ServiceSerializer(services, many=True).data)

    def post(self, request):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        serializer = sz.ServiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = serializer.save(created_by=request.user)
        log_action(request.user, "service_created", detail=f"إضافة خدمة: {service.name}")
        return Response(sz.ServiceSerializer(service).data, status=status.HTTP_201_CREATED)


class ServiceDetailView(APIView):
    def put(self, request, service_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        try:
            service = Service.objects.get(id=service_id)
        except Service.DoesNotExist:
            raise NotFound("الخدمة غير موجودة")
        old_price = service.price
        serializer = sz.ServiceSerializer(service, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        new_price = serializer.validated_data.get("price", old_price)
        extra = {}
        if new_price != old_price:
            extra["price_updated_at"] = timezone.now()
        service = serializer.save(**extra)
        if new_price != old_price:
            log_action(request.user, "service_price_changed", detail=f"{service.name}: {old_price} -> {new_price} د.ع")
        return Response(sz.ServiceSerializer(service).data)


class ServiceVariantListCreateView(APIView):
    def post(self, request, service_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        try:
            service = Service.objects.get(id=service_id)
        except Service.DoesNotExist:
            raise NotFound("الخدمة غير موجودة")
        serializer = sz.ServiceVariantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        variant = serializer.save(service=service)
        log_action(request.user, "service_variant_added", detail=f"{service.name} - {variant.name}")
        return Response(sz.ServiceVariantSerializer(variant).data, status=status.HTTP_201_CREATED)


class ServiceVariantDetailView(APIView):
    def put(self, request, service_id, variant_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        try:
            variant = ServiceVariant.objects.get(id=variant_id, service_id=service_id)
        except ServiceVariant.DoesNotExist:
            raise NotFound("الخيار غير موجود")
        old_price = variant.price
        serializer = sz.ServiceVariantSerializer(variant, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        variant = serializer.save()
        if variant.price != old_price:
            log_action(request.user, "service_variant_price_changed", detail=f"{variant.service.name} - {variant.name}: {old_price} -> {variant.price} د.ع")
        return Response(sz.ServiceVariantSerializer(variant).data)


def _invoice_or_404(invoice_id):
    try:
        return Invoice.objects.prefetch_related("items").get(id=invoice_id)
    except Invoice.DoesNotExist:
        raise NotFound("الفاتورة غير موجودة")


def _check_invoice_editable(request, invoice):
    """Shared gate for anything that mutates an invoice or its items.
    Cancelled/refunded invoices are terminal — nobody edits them. A locked
    (fully paid) invoice can only be touched by a doctor, and only with a
    documented reason, which is logged and stored on the invoice."""
    if invoice.payment_status in (Invoice.CANCELLED, Invoice.REFUNDED):
        raise PermissionDenied("لا يمكن تعديل فاتورة ملغاة أو مستردة")
    if invoice.is_locked:
        if request.user.role != "doctor":
            raise PermissionDenied("الفاتورة مقفلة بعد الدفع — التصحيح متاح للطبيب فقط")
        reason = (request.data.get("correction_reason") or "").strip()
        if not reason:
            raise ValidationError({"correction_reason": "التعديل على فاتورة مقفلة يتطلب توثيق سبب التصحيح"})
        invoice.last_correction_reason = reason
        invoice.last_correction_by = request.user
        invoice.save(update_fields=["last_correction_reason", "last_correction_by"])
        log_action(request.user, "invoice_corrected", invoice=invoice, detail=reason)


class InvoiceListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsClinicStaff]

    def get(self, request):
        qs = Invoice.objects.prefetch_related("items").select_related("patient__user", "created_by")

        patient_id = request.query_params.get("patient")
        if patient_id:
            qs = qs.filter(patient_id=patient_id)
        date_from = request.query_params.get("date_from")
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        date_to = request.query_params.get("date_to")
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        payment_method = request.query_params.get("payment_method")
        if payment_method:
            qs = qs.filter(payment_method=payment_method)
        payment_status = request.query_params.get("payment_status")
        if payment_status:
            qs = qs.filter(payment_status=payment_status)
        created_by = request.query_params.get("created_by")
        if created_by:
            qs = qs.filter(created_by_id=created_by)
        service_id = request.query_params.get("service")
        if service_id:
            qs = qs.filter(items__service_id=service_id).distinct()
        search = request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(invoice_number__icontains=search)
                | Q(patient__user__full_name__icontains=search)
                | Q(patient__file_number__icontains=search)
            )

        return Response(sz.InvoiceSerializer(qs, many=True).data)

    def post(self, request):
        patient_id = request.data.get("patient")
        if not patient_id:
            raise ValidationError({"patient": "اختر المريض"})
        patient = get_patient_or_403(request, patient_id)
        invoice = Invoice.objects.create(
            invoice_number=next_invoice_number(),
            patient=patient,
            notes=(request.data.get("notes") or "").strip(),
            created_by=request.user,
        )
        log_action(request.user, "invoice_created", invoice=invoice, detail=f"فاتورة #{invoice.invoice_number}")
        return Response(sz.InvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED)


class InvoiceDetailView(APIView):
    permission_classes = [IsAuthenticated, IsClinicStaff]

    def get(self, request, invoice_id):
        invoice = _invoice_or_404(invoice_id)
        return Response(sz.InvoiceSerializer(invoice).data)

    def put(self, request, invoice_id):
        invoice = _invoice_or_404(invoice_id)
        _check_invoice_editable(request, invoice)

        data = dict(request.data)
        data.pop("correction_reason", None)
        # A discount applied by a secretary must name a doctor as approver;
        # a doctor applying their own discount is auto-approved.
        if "discount_pct" in data and float(data.get("discount_pct") or 0) > 0:
            if request.user.role == "doctor" and not data.get("discount_approved_by"):
                data["discount_approved_by"] = request.user.id
            subtotal = sum(item.line_total() for item in invoice.items.all())
            if subtotal <= 0:
                raise ValidationError({"discount_pct": "لا يمكن تطبيق خصم على فاتورة بمجموع صفر (مثل المتابعة المجانية وحدها)"})

        serializer = sz.InvoiceSerializer(invoice, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        extra = {}
        if "discount_pct" in serializer.validated_data and float(serializer.validated_data["discount_pct"] or 0) > 0:
            extra["discount_entered_by"] = request.user
        invoice = serializer.save(**extra)
        return Response(sz.InvoiceSerializer(invoice).data)


class InvoiceItemListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsClinicStaff]

    def post(self, request, invoice_id):
        invoice = _invoice_or_404(invoice_id)
        _check_invoice_editable(request, invoice)
        serializer = sz.InvoiceItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = invoice.items.count()
        item = serializer.save(invoice=invoice, order=order)
        return Response(sz.InvoiceItemSerializer(item).data, status=status.HTTP_201_CREATED)


class InvoiceItemDetailView(APIView):
    permission_classes = [IsAuthenticated, IsClinicStaff]

    def _get_item(self, invoice, item_id):
        try:
            return InvoiceItem.objects.get(id=item_id, invoice=invoice)
        except InvoiceItem.DoesNotExist:
            raise NotFound("البند غير موجود")

    def put(self, request, invoice_id, item_id):
        invoice = _invoice_or_404(invoice_id)
        _check_invoice_editable(request, invoice)
        item = self._get_item(invoice, item_id)
        serializer = sz.InvoiceItemSerializer(item, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, invoice_id, item_id):
        invoice = _invoice_or_404(invoice_id)
        _check_invoice_editable(request, invoice)
        item = self._get_item(invoice, item_id)
        if item.is_free_followup:
            raise PermissionDenied("لا يمكن حذف بند المتابعة المجانية بشكل منفرد")
        item.delete()
        return Response({"ok": True})


class InvoiceActionView(APIView):
    permission_classes = [IsAuthenticated, IsClinicStaff]

    def post(self, request, invoice_id):
        invoice = _invoice_or_404(invoice_id)
        action = request.data.get("action")

        if action == "record_payment":
            _check_invoice_editable(request, invoice)
            payment_method = request.data.get("payment_method")
            if payment_method not in dict(Invoice.PAYMENT_METHOD_CHOICES):
                raise ValidationError({"payment_method": "اختر طريقة الدفع"})
            try:
                amount_paid = float(request.data.get("amount_paid", 0) or 0)
            except (TypeError, ValueError):
                raise ValidationError({"amount_paid": "قيمة غير صالحة"})
            subtotal = sum(item.line_total() for item in invoice.items.all())
            discount_amount = round(subtotal * (invoice.discount_pct or 0) / 100)
            total_due = subtotal - discount_amount

            invoice.payment_method = payment_method
            invoice.amount_paid = amount_paid
            if amount_paid >= total_due:
                invoice.payment_status = Invoice.PAID
                invoice.is_locked = True
            elif amount_paid > 0:
                invoice.payment_status = Invoice.PARTIAL
            else:
                invoice.payment_status = Invoice.UNPAID
            invoice.save(update_fields=["payment_method", "amount_paid", "payment_status", "is_locked"])
            log_action(request.user, "payment_recorded", invoice=invoice, detail=f"{amount_paid} د.ع عبر {payment_method}")

        elif action == "cancel":
            if request.user.role != "doctor":
                raise PermissionDenied("إلغاء الفاتورة متاح للطبيب فقط")
            if invoice.payment_status in (Invoice.CANCELLED, Invoice.REFUNDED):
                raise ValidationError({"action": "الفاتورة ملغاة أو مستردة مسبقاً"})
            reason = (request.data.get("reason") or "").strip()
            if not reason:
                raise ValidationError({"reason": "إلغاء الفاتورة يتطلب توثيق السبب"})
            invoice.payment_status = Invoice.CANCELLED
            invoice.cancel_refund_reason = reason
            invoice.save(update_fields=["payment_status", "cancel_refund_reason"])
            log_action(request.user, "invoice_cancelled", invoice=invoice, detail=reason)

        elif action == "refund":
            if request.user.role != "doctor":
                raise PermissionDenied("استرداد الفاتورة متاح للطبيب فقط")
            if invoice.payment_status not in (Invoice.PAID, Invoice.PARTIAL):
                raise ValidationError({"action": "لا يمكن استرداد فاتورة غير مدفوعة"})
            reason = (request.data.get("reason") or "").strip()
            if not reason:
                raise ValidationError({"reason": "استرداد الفاتورة يتطلب توثيق السبب"})
            invoice.payment_status = Invoice.REFUNDED
            invoice.cancel_refund_reason = reason
            invoice.save(update_fields=["payment_status", "cancel_refund_reason"])
            log_action(request.user, "invoice_refunded", invoice=invoice, detail=reason)

        elif action == "add_free_followup":
            _check_invoice_editable(request, invoice)
            has_paid_consultation = InvoiceItem.objects.filter(
                invoice__patient=invoice.patient,
                invoice__payment_status=Invoice.PAID,
                item_name=CONSULTATION_SERVICE_NAME,
            ).exclude(invoice=invoice).exists()
            if not has_paid_consultation:
                raise ValidationError({"action": "لا توجد كشفية سابقة مدفوعة لهذا المريض — لا يمكن اعتماد متابعة مجانية"})
            consultation_service = Service.objects.filter(name=CONSULTATION_SERVICE_NAME).first()
            order = invoice.items.count()
            InvoiceItem.objects.create(
                invoice=invoice, service=consultation_service, item_name="متابعة مجانية",
                unit_price=0, quantity=1, is_free_followup=True, order=order,
            )
            log_action(request.user, "free_followup_added", invoice=invoice)

        else:
            raise ValidationError({"action": "إجراء غير معروف"})

        invoice = _invoice_or_404(invoice_id)
        return Response(sz.InvoiceSerializer(invoice).data)


class AuditLogListView(APIView):
    def get(self, request):
        if request.user.role != "doctor":
            raise PermissionDenied("سجل التدقيق متاح للطبيب فقط")
        qs = AuditLogEntry.objects.select_related("actor", "invoice")
        invoice_id = request.query_params.get("invoice")
        if invoice_id:
            qs = qs.filter(invoice_id=invoice_id)
        return Response(sz.AuditLogEntrySerializer(qs[:200], many=True).data)


class RevenueReportView(APIView):
    """Doctor-only summary + filterable breakdowns for the revenue
    dashboard. Fixed-period totals (today/week/month/year) are always
    returned as reference points; the detailed breakdowns respect whatever
    filters were passed."""

    def get(self, request):
        if request.user.role != "doctor":
            raise PermissionDenied("التقارير متاحة للطبيب فقط")

        def revenue_since(dt):
            return sum(
                inv.amount_paid for inv in
                Invoice.objects.filter(created_at__gte=dt).exclude(payment_status__in=[Invoice.CANCELLED, Invoice.REFUNDED])
            )

        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        totals = {
            "today": revenue_since(today_start),
            "this_week": revenue_since(now - timedelta(days=7)),
            "this_month": revenue_since(now - timedelta(days=30)),
            "this_year": revenue_since(now - timedelta(days=365)),
        }

        qs = Invoice.objects.prefetch_related("items", "items__service", "items__service_variant").select_related("patient__user")
        date_from = request.query_params.get("date_from")
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        date_to = request.query_params.get("date_to")
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        payment_method = request.query_params.get("payment_method")
        if payment_method:
            qs = qs.filter(payment_method=payment_method)
        payment_status = request.query_params.get("payment_status")
        if payment_status:
            qs = qs.filter(payment_status=payment_status)
        created_by = request.query_params.get("created_by")
        if created_by:
            qs = qs.filter(created_by_id=created_by)
        service_id = request.query_params.get("service")
        if service_id:
            qs = qs.filter(items__service_id=service_id).distinct()

        by_service = {}
        by_payment_method = {}
        status_counts = {choice[0]: 0 for choice in Invoice.PAYMENT_STATUS_CHOICES}
        discount_total_count = 0
        discount_total_value = 0
        discount_by_reason = {}
        discount_by_user = {}
        mounjaro = {}

        billable = [inv for inv in qs if inv.payment_status not in (Invoice.CANCELLED, Invoice.REFUNDED)]

        for inv in qs:
            status_counts[inv.payment_status] = status_counts.get(inv.payment_status, 0) + 1

        for inv in billable:
            if inv.payment_method:
                by_payment_method[inv.payment_method] = by_payment_method.get(inv.payment_method, 0) + inv.amount_paid
            subtotal = sum(item.line_total() for item in inv.items.all())
            discount_amount = round(subtotal * (inv.discount_pct or 0) / 100)
            if inv.discount_pct:
                discount_total_count += 1
                discount_total_value += discount_amount
                reason = inv.discount_reason_key or "-"
                discount_by_reason[reason] = discount_by_reason.get(reason, 0) + discount_amount
                enterer = inv.discount_entered_by.full_name if inv.discount_entered_by_id else "-"
                discount_by_user[enterer] = discount_by_user.get(enterer, 0) + discount_amount

            for item in inv.items.all():
                name = item.item_name
                if name not in by_service:
                    by_service[name] = {"count": 0, "revenue": 0}
                by_service[name]["count"] += item.quantity
                by_service[name]["revenue"] += item.line_total()

                if item.service_id and item.service and item.service.name == "جرعات مونجارو":
                    dose = item.service_variant.name if item.service_variant_id else "غير محدد"
                    if dose not in mounjaro:
                        mounjaro[dose] = {"count": 0, "revenue": 0}
                    mounjaro[dose]["count"] += item.quantity
                    mounjaro[dose]["revenue"] += item.line_total()

        return Response({
            "totals": totals,
            "by_service": [{"name": k, **v} for k, v in sorted(by_service.items(), key=lambda x: -x[1]["revenue"])],
            "by_payment_method": [{"method": k, "revenue": v} for k, v in by_payment_method.items()],
            "status_counts": status_counts,
            "discounts": {
                "count": discount_total_count,
                "total_value": discount_total_value,
                "by_reason": [{"reason": k, "value": v} for k, v in discount_by_reason.items()],
                "by_user": [{"user": k, "value": v} for k, v in discount_by_user.items()],
            },
            "mounjaro": [{"dose": k, **v} for k, v in mounjaro.items()],
            "invoice_count": qs.count(),
        })


class PatientExportView(APIView):
    """Doctor-only: dumps every record the clinic holds on one patient
    (profile, assessment, follow-up file, progress/dose/lab logs,
    prescriptions, nutrition plans, notes, and billing) into a single
    multi-sheet .xlsx file — see clinic/export.py::build_patient_workbook
    for the actual sheet layout. Excludes the secretary from this endpoint
    on purpose since it surfaces invoice/billing data ("الحسابات")."""
    permission_classes = [IsDoctor]

    def get(self, request, patient_id):
        patient = get_patient_or_403(request, patient_id)
        wb = build_patient_workbook(patient)
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        safe_name = (patient.user.full_name or patient.file_number).strip().replace(" ", "_")
        filename = f"{patient.file_number}_{safe_name}.xlsx"
        response = HttpResponse(
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
        return response
