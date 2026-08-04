from django.urls import path
from . import views

urlpatterns = [
    path("auth/register", views.RegisterView.as_view()),
    path("auth/login", views.LoginView.as_view()),
    path("auth/me", views.MeView.as_view()),

    path("patients", views.PatientListView.as_view()),
    path("patients/<int:patient_id>", views.PatientDetailView.as_view()),
    path("patients/<int:patient_id>/assessment", views.AssessmentView.as_view()),
    path("patients/<int:patient_id>/plan", views.NutritionPlanView.as_view()),
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
]
