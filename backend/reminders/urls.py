from django.urls import path

from . import views

urlpatterns = [
    path("templates", views.ReminderTemplateListView.as_view()),
    path("templates/<int:template_id>", views.ReminderTemplateDetailView.as_view()),
    path("template-settings", views.ReminderTemplateSettingsListView.as_view()),

    path("patients/search", views.ReminderPatientSearchView.as_view()),
    path("patients/<int:patient_id>/autofill", views.ReminderAutoFillView.as_view()),

    path("preview", views.ReminderPreviewView.as_view()),
    path("send", views.ReminderSendView.as_view()),

    path("history", views.ReminderHistoryListView.as_view()),
    path("history/<uuid:reminder_id>", views.ReminderDetailView.as_view()),
    path("history/<uuid:reminder_id>/cancel", views.ReminderCancelView.as_view()),

    path("dashboard", views.ReminderDashboardView.as_view()),
]
