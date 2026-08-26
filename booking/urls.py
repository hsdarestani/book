from django.urls import path
from . import api, views

app_name = 'booking'
urlpatterns = [
    path('', views.booking_page, name='home'),
    path('verwaltung/', views.dashboard, name='dashboard'),
    path('api/health/', api.health, name='health'),
    path('api/services/', api.services, name='services'),
    path('api/staff/', api.staff, name='staff'),
    path('api/availability/', api.availability, name='availability'),
    path('api/appointments/', api.appointments, name='appointments'),
]
