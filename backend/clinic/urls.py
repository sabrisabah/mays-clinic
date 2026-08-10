from django.urls import path
from . import views

urlpatterns = [
    path("auth/register", views.RegisterView.as_view()),
    path("auth/login", views.LoginView.as_view()),
    path("auth/me", views.MeView.as_view()),

    path("patients", views.PatientListView.as_view()),
    path("patients/<int:patient_id>", views.PatientDetailView.as_view()),
    path("patients/<int:patient_id>/assessment", views.AssessmentView.as_view()),
    path("patients/<int:patient_id>/followup", views.FollowUpRecordView.as_view()),
    path("patients/<int:patient_id>/progress", views.ProgressListView.as_view()),
    path("patients/<int:patient_id>/progress/<int:entry_id>", views.ProgressDeleteView.as_view()),
    path("patients/<int:patient_id>/notes", views.NotesListView.as_view()),
    path("patients/<int:patient_id>/notes/<int:note_id>", views.NoteDetailView.as_view()),
    path("patients/<int:patient_id>/mounjaro", views.MounjaroDoseListView.as_view()),
    path("patients/<int:patient_id>/mounjaro/<int:entry_id>", views.MounjaroDoseDeleteView.as_view()),
    path("patients/<int:patient_id>/lab-tests", views.LabTestEntryListView.as_view()),
    path("patients/<int:patient_id>/lab-tests/<int:entry_id>", views.LabTestEntryDeleteView.as_view()),
    path("patients/<int:patient_id>/appointment", views.AppointmentView.as_view()),

    path("dashboard/stats", views.DoctorDashboardStatsView.as_view()),

    path("medications/catalog", views.MedicationCatalogView.as_view()),
    path("medications/custom", views.CustomMedicationCreateView.as_view()),
    path("patients/<int:patient_id>/prescriptions", views.PrescriptionListCreateView.as_view()),
    path("patients/<int:patient_id>/prescriptions/<int:prescription_id>/items", views.PrescriptionItemListCreateView.as_view()),
    path("patients/<int:patient_id>/prescriptions/<int:prescription_id>/items/<int:item_id>", views.PrescriptionItemDetailView.as_view()),

    path("foods", views.FoodListCreateView.as_view()),
    path("patients/<int:patient_id>/nutrition-plans", views.NutritionPlanListCreateView.as_view()),
    path("patients/<int:patient_id>/nutrition-plans/<int:plan_id>", views.NutritionPlanDetailView.as_view()),
    path("patients/<int:patient_id>/nutrition-plans/<int:plan_id>/action", views.NutritionPlanActionView.as_view()),
    path("patients/<int:patient_id>/nutrition-plans/<int:plan_id>/meals/<int:meal_id>", views.MealDetailView.as_view()),
    path("patients/<int:patient_id>/nutrition-plans/<int:plan_id>/meals/<int:meal_id>/items", views.MealItemListCreateView.as_view()),
    path("patients/<int:patient_id>/nutrition-plans/<int:plan_id>/meals/<int:meal_id>/items/<int:item_id>", views.MealItemDetailView.as_view()),
]
