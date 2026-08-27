from datetime import datetime

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, login, logout
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.http import require_http_methods
from django.utils.http import url_has_allowed_host_and_scheme

from .models import Appointment, BlockedPeriod, Customer, Service, StaffMember, WorkingHour


def booking_page(request):
    return render(request, 'booking/index.html')


@require_http_methods(['GET', 'POST'])
def admin_login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('booking:dashboard')
    error = ''
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        user = authenticate(request, username=username, password=password)
        if user and user.is_staff:
            login(request, user)
            next_url = (request.POST.get('next') or '').strip()
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                return redirect(next_url)
            return redirect('booking:dashboard')
        error = 'Anmeldung nicht möglich. Bitte prüfe deine Zugangsdaten.'
    return render(request, 'booking/admin_login.html', {'error': error, 'next': request.GET.get('next', '')})


def admin_logout(request):
    logout(request)
    return redirect('booking:admin_login')


def _local_dt(day, value):
    parsed_day = parse_date(day or '')
    parsed_time = parse_time(value or '')
    if not parsed_day or not parsed_time:
        return None
    return timezone.make_aware(datetime.combine(parsed_day, parsed_time), timezone.get_current_timezone())


@staff_member_required(login_url='/verwaltung/login/')
@require_http_methods(['GET', 'POST'])
def dashboard(request):
    staff_qs = StaffMember.objects.filter(active=True).order_by('sort_order', 'display_name')
    selected_staff = None
    selected_id = request.POST.get('staff_id') or request.GET.get('staff')
    if selected_id:
        selected_staff = staff_qs.filter(pk=selected_id).first()
    if not selected_staff:
        selected_staff = staff_qs.first()

    notice = request.GET.get('notice', '')
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'save_hours' and selected_staff:
            WorkingHour.objects.filter(staff=selected_staff).delete()
            for weekday in range(7):
                if request.POST.get(f'day_{weekday}_enabled') != 'on':
                    continue
                for period in (1, 2):
                    start = parse_time(request.POST.get(f'day_{weekday}_start_{period}', '') or '')
                    end = parse_time(request.POST.get(f'day_{weekday}_end_{period}', '') or '')
                    if start and end and end > start:
                        WorkingHour.objects.create(
                            staff=selected_staff,
                            weekday=weekday,
                            start_time=start,
                            end_time=end,
                            active=True,
                        )
            return redirect(f'/verwaltung/?staff={selected_staff.pk}&notice=hours#kalender')

        if action == 'add_block' and selected_staff:
            starts_at = _local_dt(request.POST.get('block_date'), request.POST.get('block_start'))
            ends_at = _local_dt(request.POST.get('block_date'), request.POST.get('block_end'))
            if not starts_at or not ends_at or ends_at <= starts_at:
                return redirect(f'/verwaltung/?staff={selected_staff.pk}&notice=block-error#kalender')
            BlockedPeriod.objects.create(
                staff=selected_staff,
                starts_at=starts_at,
                ends_at=ends_at,
                reason=(request.POST.get('block_reason') or '').strip()[:160],
            )
            return redirect(f'/verwaltung/?staff={selected_staff.pk}&notice=block#kalender')

        if action == 'delete_block' and selected_staff:
            BlockedPeriod.objects.filter(pk=request.POST.get('block_id'), staff=selected_staff).delete()
            return redirect(f'/verwaltung/?staff={selected_staff.pk}&notice=block-deleted#kalender')

        if action == 'appointment_status':
            appointment = get_object_or_404(Appointment, pk=request.POST.get('appointment_id'))
            status = request.POST.get('status')
            allowed = {item[0] for item in Appointment.STATUS}
            if status not in allowed:
                return HttpResponseBadRequest('Ungültiger Status')
            appointment.status = status
            appointment.save(update_fields=['status', 'updated_at'])
            suffix = f'&staff={selected_staff.pk}' if selected_staff else ''
            return redirect(f'/verwaltung/?notice=appointment{suffix}#termine')

        if action == 'save_service':
            service = get_object_or_404(Service, pk=request.POST.get('service_id'))
            service.name = (request.POST.get('name') or service.name).strip()[:140]
            service.price_label = (request.POST.get('price_label') or '').strip()[:80]
            try:
                service.duration_minutes = max(5, int(request.POST.get('duration_minutes') or service.duration_minutes))
                service.buffer_minutes = max(0, int(request.POST.get('buffer_minutes') or 0))
            except ValueError:
                return redirect('/verwaltung/?notice=service-error#behandlungen')
            service.active = request.POST.get('active') == 'on'
            service.bookable = request.POST.get('bookable') == 'on'
            service.requires_confirmation = request.POST.get('requires_confirmation') == 'on'
            service.save()
            return redirect('/verwaltung/?notice=service#behandlungen')

    now = timezone.now()
    today = timezone.localdate()
    upcoming = (
        Appointment.objects.select_related('customer', 'service', 'staff')
        .filter(starts_at__gte=now)
        .order_by('starts_at')[:80]
    )
    customers = Customer.objects.order_by('-updated_at')[:40]
    canonical_service_slugs = [
        'aesthetische-erstberatung', 'botox-neupatient', 'botox-bestandspatient', 'hyaluron',
        'laser-haarentfernung', 'rf-microneedling', 'skinbooster', 'infusionstherapie',
        'injektionslipolyse', 'kontrolltermin',
    ]
    services = Service.objects.filter(slug__in=canonical_service_slugs).order_by('sort_order', 'name')

    weekday_labels = dict(WorkingHour.WEEKDAYS)
    hour_map = {day: [] for day in range(7)}
    if selected_staff:
        for item in WorkingHour.objects.filter(staff=selected_staff, active=True).order_by('weekday', 'start_time'):
            hour_map[item.weekday].append(item)
    availability_rows = []
    for weekday in range(7):
        intervals = hour_map[weekday][:2]
        availability_rows.append({
            'weekday': weekday,
            'label': weekday_labels[weekday],
            'enabled': bool(intervals),
            'start_1': intervals[0].start_time.strftime('%H:%M') if len(intervals) > 0 else '09:00',
            'end_1': intervals[0].end_time.strftime('%H:%M') if len(intervals) > 0 else '18:00',
            'start_2': intervals[1].start_time.strftime('%H:%M') if len(intervals) > 1 else '',
            'end_2': intervals[1].end_time.strftime('%H:%M') if len(intervals) > 1 else '',
        })

    blocked = []
    if selected_staff:
        blocked = BlockedPeriod.objects.filter(staff=selected_staff, ends_at__gte=now).order_by('starts_at')[:30]

    context = {
        'today_count': Appointment.objects.filter(starts_at__date=today).exclude(status='cancelled').count(),
        'new_count': Appointment.objects.filter(status='new', starts_at__gte=now).count(),
        'customer_count': Customer.objects.count(),
        'staff_count': staff_qs.count(),
        'staff_members': staff_qs,
        'selected_staff': selected_staff,
        'availability_rows': availability_rows,
        'blocked_periods': blocked,
        'upcoming': upcoming,
        'services': services,
        'customers': customers,
        'appointment_statuses': Appointment.STATUS,
        'notice': notice,
    }
    return render(request, 'booking/dashboard.html', context)
