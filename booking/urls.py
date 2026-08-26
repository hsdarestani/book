from django.urls import path
from . import api, mobile_api, views

app_name = 'booking'
urlpatterns = [
    path('', views.booking_page, name='home'),
    path('verwaltung/', views.dashboard, name='dashboard'),
    path('api/health/', api.health, name='health'),
    path('api/services/', api.services, name='services'),
    path('api/staff/', api.staff, name='staff'),
    path('api/availability/', api.availability, name='availability'),
    path('api/appointments/', api.appointments, name='appointments'),
    path('api/mobile/slots/', mobile_api.mobile_slots, name='mobile_slots'),
    path('api/mobile/booking/', mobile_api.mobile_booking, name='mobile_booking'),
    path('api/mobile/booking/manageable/', mobile_api.mobile_manageable_appointments, name='mobile_manageable_appointments'),
    path('api/mobile/booking/<uuid:appointment_id>/change/', mobile_api.mobile_appointment_change, name='mobile_appointment_change'),
]