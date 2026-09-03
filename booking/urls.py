from django.urls import path
from . import api, calendar, internal_api, mobile_api, views

app_name = 'booking'
urlpatterns = [
    path('', views.booking_page, name='home'),
    path('termin/<uuid:appointment_id>/kalender.ics', calendar.appointment_calendar, name='appointment_calendar'),
    path('verwaltung/', views.dashboard, name='dashboard'),
    path('verwaltung/login/', views.admin_login, name='admin_login'),
    path('verwaltung/logout/', views.admin_logout, name='admin_logout'),
    path('verwaltung/patienten/<int:customer_id>/', views.patient_file, name='patient_file'),
    path('verwaltung/patienten/<int:customer_id>/datei/<uuid:record_id>/', views.patient_record_file, name='patient_record_file'),
    path('api/health/', api.health, name='health'),
    path('api/services/', api.services, name='services'),
    path('api/staff/', api.staff, name='staff'),
    path('api/availability/', api.availability, name='availability'),
    path('api/availability/overview/', api.availability_overview, name='availability_overview'),
    path('api/appointments/', api.appointments, name='appointments'),
    path('api/internal/patient-records/ingest/', internal_api.ingest_patient_record, name='patient_record_ingest'),
    path('api/mobile/slots/', mobile_api.mobile_slots, name='mobile_slots'),
    path('api/mobile/booking/', mobile_api.mobile_booking, name='mobile_booking'),
    path('api/mobile/booking/manageable/', mobile_api.mobile_manageable_appointments, name='mobile_manageable_appointments'),
    path('api/mobile/booking/<uuid:appointment_id>/change/', mobile_api.mobile_appointment_change, name='mobile_appointment_change'),
]
