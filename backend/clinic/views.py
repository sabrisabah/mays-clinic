from datetime import datetime
from django.db import IntegrityError
from django.db.models import Q
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework import status

from .models import User, Patient, Assessment, NutritionPlan, ProgressEntry, DoctorNote, FollowUpRecord, MounjaroDose
from .permissions import IsDoctor
from .utils import (
    compute_bmi,
    compute_whr,
    compute_whr_class,
    compute_activity_level,
    next_file_number,
    normalize_height_m,
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
        visit_datetime = timezone.make_aware(datetime.combine(data["visit_date"], datetime.min.time()))
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
    permission_classes = [IsAuthenticated, IsDoctor]

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
        assessment.save()

        return Response(sz.AssessmentSerializer(assessment).data)


# ---------------- NUTRITION PLAN ----------------

class NutritionPlanView(APIView):
    def get(self, request, patient_id):
        patient = get_patient_or_403(request, patient_id)
        plan, _ = NutritionPlan.objects.get_or_create(patient=patient)
        return Response(sz.NutritionPlanSerializer(plan).data)

    def put(self, request, patient_id):
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        plan, _ = NutritionPlan.objects.get_or_create(patient=patient)

        serializer = sz.NutritionPlanSerializer(plan, data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = serializer.save(created_by=request.user)

        return Response(sz.NutritionPlanSerializer(plan).data)

    def delete(self, request, patient_id):
        # Lets a patient clear their own nutrition plan from their interface
        # (get_patient_or_403 already restricts a patient to their own record;
        # a doctor may act on any patient's plan the same way).
        patient = get_patient_or_403(request, patient_id)
        NutritionPlan.objects.filter(patient=patient).delete()
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
        if request.user.role != "doctor":
            raise PermissionDenied("هذا الإجراء متاح للطبيب فقط")
        patient = get_patient_or_403(request, patient_id)
        record, _ = FollowUpRecord.objects.get_or_create(patient=patient)

        serializer = sz.FollowUpRecordSerializer(record, data=request.data)
        serializer.is_valid(raise_exception=True)
        record = serializer.save(created_by=request.user)

        return Response(sz.FollowUpRecordSerializer(record).data)


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
