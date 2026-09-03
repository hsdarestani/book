import logging
import mimetypes
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.http import FileResponse, Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from .emails import send_customer_booking_email
from .models import Appointment, BlockedPeriod, Customer, PatientRecord, Service, StaffMember, WorkingHour

logger = logging.getLogger(__name__)

CALENDAR_START_HOUR = 8
CALENDAR_END_HOUR = 20


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


def _patient_file_path(stored_name):
    root = Path(settings.PATIENT_FILES_ROOT).resolve()
    candidate = (root / stored_name).resolve()
    if candidate != root and root not in candidate.parents:
        raise Http404('Datei nicht gefunden')
    return candidate


def _delete_patient_file(record):
    if not record.stored_name:
        return
    try:
        path = _patient_file_path(record.stored_name)
        if path.exists() and path.is_file():
            path.unlink()
        parent = path.parent
        root = Path(settings.PATIENT_FILES_ROOT).resolve()
        if parent != root and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    except (OSError, Http404):
        pass


def _calendar_position(starts_at, ends_at):
    local_start = timezone.localtime(starts_at)
    local_end = timezone.localtime(ends_at)
    start_minute = max(CALENDAR_START_HOUR * 60, local_start.hour * 60 + local_start.minute)
    end_minute = min(CALENDAR_END_HOUR * 60, local_end.hour * 60 + local_end.minute)
    total = (CALENDAR_END_HOUR - CALENDAR_START_HOUR) * 60
    top = max(0, ((start_minute - CALENDAR_START_HOUR * 60) / total) * 100)
    height = max(1.6, ((max(end_minute, start_minute + 10) - start_minute) / total) * 100)
    return round(top, 4), round(height, 4)


def _clean_calendar_reason(reason):
    value = (reason or '').strip()
    prefixes = ('[NOTE]', '[BLOCKNOTE]', '[ALL]', '[STAFF]', '[SERVICE]')
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if value.startswith(prefix):
                value = value[len(prefix):].lstrip()
                changed = True
    if value.startswith('[SERVICE:') and ']' in value:
        value = value.split(']', 1)[1].lstrip()
    return value or 'Notiz'


def _calendar_block_kind(reason):
    value = reason or ''
    if value.startswith('[NOTE]'):
        return 'note'
    if value.startswith('[BLOCKNOTE]'):
        return 'blocked-note'
    return 'blocked'


def _calendar_scope_prefix(scope, service_id=None):
    if scope == 'all':
        return '[ALL]'
    if scope == 'service' and service_id:
        return f'[SERVICE:{service_id}]'
    return '[STAFF]'


@staff_member_required(login_url='/verwaltung/login/')
@require_http_methods(['GET', 'POST'])
def patient_file(request, customer_id):
    customer = get_object_or_404(Customer, pk=customer_id)
    notice = request.GET.get('notice', '')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_record':
            kind = (request.POST.get('kind') or 'document').strip()
            allowed_kinds = {value for value, _ in PatientRecord.KIND}
            if kind not in allowed_kinds:
                return redirect(f'/verwaltung/patienten/{customer.pk}/?notice=type-error')

            uploaded = request.FILES.get('file')
            note = (request.POST.get('note') or '').strip()[:6000]
            title = (request.POST.get('title') or '').strip()[:180]
            appointment = None
            appointment_id = (request.POST.get('appointment_id') or '').strip()
            if appointment_id:
                appointment = Appointment.objects.filter(pk=appointment_id, customer=customer).first()

            stored_name = ''
            original_name = ''
            mime_type = ''
            file_size = 0

            if uploaded:
                original_name = Path(uploaded.name or 'datei').name[:255]
                extension = Path(original_name).suffix.lower()
                if extension not in settings.PATIENT_FILE_ALLOWED_EXTENSIONS:
                    return redirect(f'/verwaltung/patienten/{customer.pk}/?notice=file-type')
                if uploaded.size > settings.PATIENT_FILE_MAX_BYTES:
                    return redirect(f'/verwaltung/patienten/{customer.pk}/?notice=file-size')
                if uploaded.size <= 0:
                    return redirect(f'/verwaltung/patienten/{customer.pk}/?notice=file-empty')

                root = Path(settings.PATIENT_FILES_ROOT)
                patient_dir = root / str(customer.pk)
                patient_dir.mkdir(parents=True, exist_ok=True)
                stored_name = f'{customer.pk}/{uuid.uuid4().hex}{extension}'
                destination = _patient_file_path(stored_name)
                with destination.open('wb') as handle:
                    for chunk in uploaded.chunks():
                        handle.write(chunk)
                file_size = uploaded.size
                mime_type = (uploaded.content_type or mimetypes.guess_type(original_name)[0] or 'application/octet-stream')[:120]
                if not title:
                    title = Path(original_name).stem[:180] or 'Datei'

            if not uploaded and not note:
                return redirect(f'/verwaltung/patienten/{customer.pk}/?notice=empty')
            if not title:
                title = 'Notiz'
            if not uploaded:
                kind = 'note' if kind == 'document' else kind

            PatientRecord.objects.create(
                customer=customer,
                appointment=appointment,
                kind=kind,
                title=title,
                note=note,
                stored_name=stored_name,
                original_name=original_name,
                mime_type=mime_type,
                file_size=file_size,
                uploaded_by=request.user,
            )
            return redirect(f'/verwaltung/patienten/{customer.pk}/?notice=added#akte')

        if action == 'delete_record':
            record = get_object_or_404(PatientRecord, pk=request.POST.get('record_id'), customer=customer)
            _delete_patient_file(record)
            record.delete()
            return redirect(f'/verwaltung/patienten/{customer.pk}/?notice=deleted#akte')

    appointments = (
        Appointment.objects.filter(customer=customer)
        .select_related('service', 'staff')
        .order_by('-starts_at')[:80]
    )
    records = (
        PatientRecord.objects.filter(customer=customer)
        .select_related('appointment', 'appointment__service', 'uploaded_by')
        .order_by('-created_at', '-pk')
    )
    last_appointment = next((item for item in appointments if item.status != 'cancelled'), None)
    context = {
        'customer': customer,
        'appointments': appointments,
        'records': records,
        'record_kinds': PatientRecord.KIND,
        'notice': notice,
        'last_appointment': last_appointment,
        'max_upload_mb': settings.PATIENT_FILE_MAX_BYTES // (1024 * 1024),
    }
    return render(request, 'booking/patient_file.html', context)


@staff_member_required(login_url='/verwaltung/login/')
@require_http_methods(['GET'])
def patient_record_file(request, customer_id, record_id):
    record = get_object_or_404(PatientRecord, public_id=record_id, customer_id=customer_id)
    if not record.stored_name:
        raise Http404('Keine Datei vorhanden')
    path = _patient_file_path(record.stored_name)
    if not path.exists() or not path.is_file():
        raise Http404('Datei nicht gefunden')
    response = FileResponse(
        path.open('rb'),
        content_type=record.mime_type or 'application/octet-stream',
        as_attachment=request.GET.get('download') == '1',
        filename=record.original_name or path.name,
    )
    response['Cache-Control'] = 'private, no-store, max-age=0'
    response['Pragma'] = 'no-cache'
    return response


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

    calendar_date = parse_date(request.GET.get('date') or '') or timezone.localdate()
    calendar_view = request.GET.get('cal_view') or 'day'
    if calendar_view not in {'day', 'week'}:
        calendar_view = 'day'

    notice = request.GET.get('notice', '')
    if request.method == 'POST':
        action = request.POST.get('action')
        return_date = request.POST.get('return_date') or calendar_date.isoformat()
        return_view = request.POST.get('return_view') or calendar_view
        staff_suffix = f'&staff={selected_staff.pk}' if selected_staff else ''
        calendar_return = f'/verwaltung/?date={return_date}&cal_view={return_view}{staff_suffix}#kalender'

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
            return redirect(f'/verwaltung/?staff={selected_staff.pk}&notice=hours#einstellungen')

        if action == 'add_block' and selected_staff:
            starts_at = _local_dt(request.POST.get('block_date'), request.POST.get('block_start'))
            ends_at = _local_dt(request.POST.get('block_date'), request.POST.get('block_end'))
            if not starts_at or not ends_at or ends_at <= starts_at:
                return redirect(f'/verwaltung/?staff={selected_staff.pk}&notice=block-error#einstellungen')
            BlockedPeriod.objects.create(
                staff=selected_staff,
                starts_at=starts_at,
                ends_at=ends_at,
                reason=(request.POST.get('block_reason') or '').strip()[:160],
            )
            return redirect(f'/verwaltung/?staff={selected_staff.pk}&notice=block#einstellungen')

        if action == 'delete_block' and selected_staff:
            BlockedPeriod.objects.filter(pk=request.POST.get('block_id'), staff=selected_staff).delete()
            return redirect(f'/verwaltung/?staff={selected_staff.pk}&notice=block-deleted#einstellungen')

        if action == 'add_calendar_note' and selected_staff:
            starts_at = _local_dt(request.POST.get('note_date'), request.POST.get('note_start'))
            ends_at = _local_dt(request.POST.get('note_date'), request.POST.get('note_end'))
            if not starts_at or not ends_at or ends_at <= starts_at:
                return redirect(f'{calendar_return}&notice=note-error')
            text = (request.POST.get('note_text') or '').strip()[:120]
            scope = request.POST.get('note_scope') or 'all'
            service_id = request.POST.get('note_service_id') or None
            is_blocked = request.POST.get('note_blocked') == 'on'
            prefix = '[BLOCKNOTE]' if is_blocked else '[NOTE]'
            scope_prefix = _calendar_scope_prefix(scope, service_id)
            reason = f'{prefix}{scope_prefix} {text or "Notiz"}'[:160]

            targets = staff_qs
            if scope == 'staff':
                targets = staff_qs.filter(pk=selected_staff.pk)
            elif scope == 'service' and service_id:
                targets = staff_qs.filter(services__pk=service_id).distinct()
            created = 0
            for member in targets:
                BlockedPeriod.objects.create(staff=member, starts_at=starts_at, ends_at=ends_at, reason=reason)
                created += 1
            if not created:
                return redirect(f'{calendar_return}&notice=note-error')
            return redirect(f'{calendar_return}&notice=note')

        if action == 'delete_calendar_item':
            item = BlockedPeriod.objects.filter(pk=request.POST.get('block_id')).first()
            if item:
                item.delete()
            return redirect(calendar_return)

        if action == 'add_customer':
            first_name = (request.POST.get('first_name') or '').strip()[:80]
            last_name = (request.POST.get('last_name') or '').strip()[:80]
            email = (request.POST.get('email') or '').strip().lower()
            phone = (request.POST.get('phone') or '').strip()[:40]
            if not first_name or not email or '@' not in email:
                return redirect('/verwaltung/?notice=customer-error#kunden')
            customer = Customer.objects.filter(email__iexact=email).order_by('pk').first()
            if customer:
                customer.first_name = first_name
                customer.last_name = last_name or customer.last_name
                customer.phone = phone or customer.phone
                customer.save(update_fields=['first_name', 'last_name', 'phone', 'updated_at'])
            else:
                customer = Customer.objects.create(first_name=first_name, last_name=last_name, email=email, phone=phone)
            destination = request.POST.get('return_to') or 'kunden'
            return redirect(f'/verwaltung/?notice=customer#{destination}')

        if action == 'add_appointment':
            service = Service.objects.filter(pk=request.POST.get('service_id'), active=True).first()
            staff = staff_qs.filter(pk=request.POST.get('appointment_staff_id') or (selected_staff.pk if selected_staff else None)).first()
            customer = Customer.objects.filter(pk=request.POST.get('customer_id')).first()
            starts_at = _local_dt(request.POST.get('appointment_date'), request.POST.get('appointment_time'))
            if not service or not staff or not customer or not starts_at:
                return redirect(f'{calendar_return}&notice=booking-error')
            if not staff.services.filter(pk=service.pk).exists():
                return redirect(f'{calendar_return}&notice=booking-service-error')
            ends_at = starts_at + timedelta(minutes=service.duration_minutes + service.buffer_minutes)
            conflict = Appointment.objects.filter(
                staff=staff,
                status__in=['new', 'confirmed'],
                starts_at__lt=ends_at,
                ends_at__gt=starts_at,
            ).exists()
            blocked = BlockedPeriod.objects.filter(
                staff=staff,
                starts_at__lt=ends_at,
                ends_at__gt=starts_at,
            ).exclude(reason__startswith='[NOTE]').exists()
            if conflict or blocked:
                return redirect(f'{calendar_return}&notice=booking-conflict')
            appointment = Appointment(
                customer=customer,
                service=service,
                staff=staff,
                starts_at=starts_at,
                ends_at=ends_at,
                status='confirmed',
                source='admin',
                returning_customer=Appointment.objects.filter(customer=customer).exists(),
                marketing_opt_in=False,
            )
            try:
                appointment.full_clean()
                appointment.save()
            except ValidationError:
                return redirect(f'{calendar_return}&notice=booking-conflict')
            try:
                send_customer_booking_email(appointment)
            except Exception:
                logger.exception('Admin-Termin gespeichert, Bestätigungs-E-Mail konnte nicht versendet werden')
            return redirect(f'{calendar_return}&notice=booking')

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
    customers = (
        Customer.objects.annotate(
            record_count=Count('patient_records', distinct=True),
            appointment_count=Count('appointments', distinct=True),
        )
        .order_by('last_name', 'first_name')[:250]
    )
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

    if calendar_view == 'week':
        range_start = calendar_date - timedelta(days=calendar_date.weekday())
        range_end = range_start + timedelta(days=7)
        previous_date = range_start - timedelta(days=7)
        next_date = range_start + timedelta(days=7)
    else:
        range_start = calendar_date
        range_end = range_start + timedelta(days=1)
        previous_date = range_start - timedelta(days=1)
        next_date = range_start + timedelta(days=1)

    calendar_appointments = Appointment.objects.none()
    calendar_blocks = BlockedPeriod.objects.none()
    if selected_staff:
        start_dt = timezone.make_aware(datetime.combine(range_start, datetime.min.time()), timezone.get_current_timezone())
        end_dt = timezone.make_aware(datetime.combine(range_end, datetime.min.time()), timezone.get_current_timezone())
        calendar_appointments = (
            Appointment.objects.filter(
                staff=selected_staff,
                starts_at__lt=end_dt,
                ends_at__gt=start_dt,
            )
            .exclude(status='cancelled')
            .select_related('customer', 'service', 'staff')
            .order_by('starts_at')
        )
        calendar_blocks = BlockedPeriod.objects.filter(
            staff=selected_staff,
            starts_at__lt=end_dt,
            ends_at__gt=start_dt,
        ).order_by('starts_at')

    day_names = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
    calendar_days = []
    day_cursor = range_start
    while day_cursor < range_end:
        working_segments = []
        for working in hour_map.get(day_cursor.weekday(), []):
            start = timezone.make_aware(datetime.combine(day_cursor, working.start_time), timezone.get_current_timezone())
            end = timezone.make_aware(datetime.combine(day_cursor, working.end_time), timezone.get_current_timezone())
            top, height = _calendar_position(start, end)
            working_segments.append({'top': top, 'height': height, 'label': f'{working.start_time:%H:%M}–{working.end_time:%H:%M}'})

        appointments_for_day = []
        for item in calendar_appointments:
            if timezone.localtime(item.starts_at).date() != day_cursor:
                continue
            top, height = _calendar_position(item.starts_at, item.ends_at)
            appointments_for_day.append({'item': item, 'top': top, 'height': height})

        blocks_for_day = []
        for block in calendar_blocks:
            if timezone.localtime(block.starts_at).date() != day_cursor:
                continue
            top, height = _calendar_position(block.starts_at, block.ends_at)
            blocks_for_day.append({
                'item': block,
                'top': top,
                'height': height,
                'kind': _calendar_block_kind(block.reason),
                'label': _clean_calendar_reason(block.reason),
            })

        calendar_days.append({
            'date': day_cursor,
            'day_name': day_names[day_cursor.weekday()],
            'working_segments': working_segments,
            'appointments': appointments_for_day,
            'blocks': blocks_for_day,
            'is_today': day_cursor == today,
        })
        day_cursor += timedelta(days=1)

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
        'calendar_date': calendar_date,
        'calendar_view': calendar_view,
        'calendar_days': calendar_days,
        'calendar_hour_labels': [f'{hour:02d}:00' for hour in range(CALENDAR_START_HOUR, CALENDAR_END_HOUR + 1)],
        'calendar_start_hour': CALENDAR_START_HOUR,
        'calendar_end_hour': CALENDAR_END_HOUR,
        'previous_date': previous_date,
        'next_date': next_date,
        'range_start': range_start,
        'range_end_display': range_end - timedelta(days=1),
    }
    return render(request, 'booking/dashboard.html', context)
