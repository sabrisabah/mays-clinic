from datetime import datetime, timedelta
from django.db import IntegrityError
from django.db.models import Q
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework import status

from .models import (
    User, Patient, Assessment, NutritionPlan, ProgressEntry, DoctorNote, FollowUpRecord, MounjaroDose, LabTestEntry,
    MedicationCategory, Medication, MedicationDose, Prescription, PrescriptionItem,
    Food, Meal, MealItem,
)
from .permissions import IsDoctor, IsClinicStaff
from .utils import (
    compute_bmi,
    compute_whr,
    compute_whr_class,
    compute_activity_level,
    next_file_number,
    normalize_height_m,
    compute_bmr,
    compute_tdee,
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
        Assessment.objects.create(patient=patient, visit_date=visit_datetime)

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
        return Response(sz.PatientListItemSerializer(results, many=True).data)


class PatientDetailView(APIView):
    def get(self, request, patient_id):
        patient = get_patient_or_403(request, patient_id)
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


# ---------------- ASSESSMENT ----------------

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

        # Accept height typed in cm (e.g. 170) or meters (1.70); always store meters.
        if "height" in data:
            data["height"] = normalize_height_m(data.get("height", 0))

        bmi, bmi_class = compute_bmi(data.get("weight", 0), data.get("height", 0))
        whr = compute_whr(data.get("waist", 0), data.get("hip", 0))
        whr_class = compute_whr_class(whr, patient.gender)
        activity_level = compute_activity_level(data.get("sport_days_per_week", 0))

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
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
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
# Weekly weight + dose log for patients on Mounjaro, entered by the doctor
# at each clinic visit; the patient can view their own log read-only.

class MounjaroDoseListView(APIView):
    def get(self, request, patient_id):
        patient = get_patient_or_403(request, patient_id)
        entries = patient.mounjaro_doses.order_by("date")
        return Response(sz.MounjaroDoseSerializer(entries, many=True).data)

    def post(self, request, patient_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
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


class MounjaroDoseDeleteView(APIView):
    def delete(self, request, patient_id, entry_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        MounjaroDose.objects.filter(id=entry_id, patient=patient).delete()
        return Response({"ok": True})


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

        obese = overweight = normal = 0
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
