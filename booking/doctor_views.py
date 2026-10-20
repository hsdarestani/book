from datetime import datetime, timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import Appointment


@never_cache
@staff_member_required(login_url='/verwaltung/login/')
@require_GET
def doctor_appointments(request):
    """Patient names and appointments for exactly the signed-in clinician."""
    profile = getattr(request.user, 'aesthetic_access', None)
    if not profile or not profile.view_only or not profile.staff_id:
        return HttpResponseForbidden('Kein Arztzugang.')

    today = timezone.localdate()
    start = timezone.make_aware(
        datetime.combine(today - timedelta(days=30), datetime.min.time()),
        timezone.get_current_timezone(),
    )
    appointments = (
        Appointment.objects.filter(staff_id=profile.staff_id, starts_at__gte=start)
        .select_related('customer', 'service')
        .order_by('starts_at')[:250]
    )
    return render(request, 'booking/doctor_appointments.html', {
        'staff': profile.staff,
        'appointments': appointments,
        'today': today,
    })
