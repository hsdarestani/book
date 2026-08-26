from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.utils import timezone
from .models import Appointment, Customer, Service, StaffMember


def booking_page(request):
    return render(request, 'booking/index.html')


@staff_member_required
def dashboard(request):
    now = timezone.now()
    upcoming = Appointment.objects.select_related('customer', 'service', 'staff').filter(
        starts_at__gte=now,
        status__in=['new', 'confirmed'],
    ).order_by('starts_at')[:12]
    today = timezone.localdate()
    context = {
        'today_count': Appointment.objects.filter(starts_at__date=today).exclude(status='cancelled').count(),
        'new_count': Appointment.objects.filter(status='new', starts_at__gte=now).count(),
        'customer_count': Customer.objects.count(),
        'service_count': Service.objects.filter(active=True).count(),
        'staff_count': StaffMember.objects.filter(active=True).count(),
        'upcoming': upcoming,
    }
    return render(request, 'booking/dashboard.html', context)
