import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from . import patient_portal
from .models import Appointment, Customer


AESTHETIC_ADMIN_API = 'https://esthetic.smarbiz.sbs/api/mobile/admin'
SECTIONS = {
    'bookings': ('Termine', 'Reservierungen und Terminstatus verwalten'),
    'patients': ('Patientenakten', 'Dokumente, Fotos und Notizen chronologisch verwalten'),
    'reviews': ('Google Bewertungen', 'Bewertungsaktivitäten prüfen und dokumentieren'),
    'wallet': ('A+ Wallet', 'A+ Guthaben der Patienten aufladen oder korrigieren'),
    'referrals': ('Empfehlungen', 'Empfehlungen an Freunde im Blick behalten'),
}


def _authorization(request):
    value = str(request.session.get('aplus_admin_authorization') or '').strip()
    return value if value.startswith('Bearer ') else ''


def _api(request, endpoint, method='GET', payload=None, query=None):
    authorization = _authorization(request)
    if not authorization:
        raise PermissionError('A+ Admin-Sitzung fehlt')
    url = f"{AESTHETIC_ADMIN_API}/{endpoint.lstrip('/')}"
    if query:
        encoded = urlencode({key: value for key, value in query.items() if value not in (None, '')})
        if encoded:
            url += f'?{encoded}'
    body = None
    headers = {
        'Authorization': authorization,
        'Accept': 'application/json',
        'User-Agent': 'A-Esthetic-Book-Focused-Admin/3.0',
    }
    if payload is not None:
        body = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    remote = Request(url, data=body, method=method, headers=headers)
    try:
        with urlopen(remote, timeout=20) as response:
            raw = response.read().decode('utf-8')
            status = response.status
    except HTTPError as exc:
        raw = exc.read().decode('utf-8', 'replace')
        status = exc.code
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f'A+ API nicht erreichbar: {exc}') from exc
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError('Ungültige Antwort der A+ API') from exc
    if status in {401, 403}:
        request.session.pop('aplus_admin_authorization', None)
        raise PermissionError(data.get('error') or 'Admin-Sitzung abgelaufen')
    if status >= 400 or not data.get('ok', False):
        raise RuntimeError(data.get('error') or f'A+ API Fehler {status}')
    return data


def _redirect(section, notice='saved', extra=None):
    query = {}
    if notice:
        query['notice'] = notice
    if extra:
        query.update({key: value for key, value in extra.items() if value not in (None, '')})
    suffix = f"?{urlencode(query)}" if query else ''
    return redirect(f'/verwaltung/app/{section}/{suffix}')


@never_cache
@staff_member_required(login_url='/verwaltung/login/')
def focused_calendar_entry(request):
    """A+ app admins stay inside the five-feature management surface.

    Normal Book staff keep the existing calendar route and experience.
    """
    if request.session.get('aplus_app_admin'):
        return redirect('/verwaltung/app/bookings/')
    from . import admin_views
    return admin_views.dashboard_proxy(request)


def _booking_context(request):
    query = str(request.GET.get('q') or '').strip()
    status = str(request.GET.get('status') or '').strip()
    qs = Appointment.objects.select_related('customer', 'service', 'staff')
    if query:
        qs = qs.filter(
            Q(customer__first_name__icontains=query)
            | Q(customer__last_name__icontains=query)
            | Q(customer__email__icontains=query)
            | Q(customer__phone__icontains=query)
            | Q(service__name__icontains=query)
            | Q(staff__display_name__icontains=query)
        )
    allowed_statuses = {value for value, _ in Appointment.STATUS}
    if status in allowed_statuses:
        qs = qs.filter(status=status)
    else:
        status = ''

    now = timezone.now()
    upcoming = list(qs.filter(starts_at__gte=now).exclude(status='cancelled').order_by('starts_at')[:120])
    history = list(qs.filter(Q(starts_at__lt=now) | Q(status='cancelled')).order_by('-starts_at')[:180])
    return {
        'query': query,
        'status_filter': status,
        'status_choices': Appointment.STATUS,
        'upcoming': upcoming,
        'history': history,
        'today_count': Appointment.objects.filter(starts_at__date=timezone.localdate()).exclude(status='cancelled').count(),
        'new_count': Appointment.objects.filter(status='new', starts_at__gte=now).count(),
    }


def _patient_context(request):
    query = str(request.GET.get('q') or '').strip()
    customer_qs = Customer.objects.order_by('last_name', 'first_name')
    if query:
        customer_qs = customer_qs.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(phone__icontains=query)
        )
    customers = list(customer_qs[:250])

    selected = None
    records = []
    appointments = []
    raw_customer = str(request.GET.get('customer') or '').strip()
    if raw_customer.isdigit():
        selected = Customer.objects.filter(pk=int(raw_customer)).first()
    if selected:
        appointments = list(selected.appointments.select_related('service', 'staff').order_by('-starts_at')[:80])
        for record in selected.patient_records.select_related('appointment', 'uploaded_by').order_by('-created_at')[:180]:
            metadata = record.metadata if isinstance(record.metadata, dict) else {}
            patient_source = record.source in patient_portal.APP_SHARED_SOURCES
            records.append({
                'id': str(record.public_id),
                'kind': record.kind,
                'kind_label': record.get_kind_display(),
                'title': record.title,
                'note': record.note,
                'has_file': record.has_file,
                'original_name': record.original_name,
                'source_label': 'Patient' if patient_source else 'Praxis',
                'shared': patient_source or metadata.get('shared_with_customer') is True,
                'created_at': record.captured_at or record.created_at,
                'appointment': record.appointment,
            })
    return {
        'query': query,
        'patients': customers,
        'selected_customer': selected,
        'patient_records': records,
        'patient_appointments': appointments,
    }


@never_cache
@staff_member_required(login_url='/verwaltung/login/')
@require_http_methods(['GET', 'POST'])
def app_management(request, section='bookings'):
    if section not in SECTIONS:
        section = 'bookings'
    if not request.session.get('aplus_app_admin'):
        return HttpResponseForbidden('A+ App Management ist nur über eine bestätigte A+ Admin-Sitzung verfügbar.')

    try:
        if request.method == 'POST':
            action = str(request.POST.get('action') or '')
            if action == 'booking_status':
                appointment_id = int(request.POST.get('appointment_id'))
                status = str(request.POST.get('status') or '').strip()
                allowed = {value for value, _ in Appointment.STATUS}
                if status not in allowed:
                    raise ValueError('Ungültiger Terminstatus.')
                appointment = Appointment.objects.filter(pk=appointment_id).first()
                if not appointment:
                    raise ValueError('Termin wurde nicht gefunden.')
                appointment.status = status
                appointment.save(update_fields=['status', 'updated_at'])
                return _redirect('bookings', 'booking', {'q': request.POST.get('q') or '', 'status': request.POST.get('status_filter') or ''})

            if action == 'patient_upload':
                customer_id = int(request.POST.get('customer_id'))
                return patient_portal.staff_add_record(request, customer_id)

            if action == 'wallet_adjust':
                customer_id = int(request.POST.get('customer_id'))
                credit_text = str(request.POST.get('credit_delta_eur') or '').replace(',', '.').strip()
                credit_cents = int(round(float(credit_text) * 100)) if credit_text else 0
                if not credit_cents:
                    raise ValueError('Bitte einen Betrag größer oder kleiner als 0 eingeben.')
                _api(request, f'customers/{customer_id}/', method='POST', payload={'credit_delta_cents': credit_cents})
                return _redirect('wallet', 'wallet')

            if action == 'review_verify':
                review_id = int(request.POST.get('review_id'))
                rating_text = str(request.POST.get('rating') or '').strip()
                payload = {'action': 'verify', 'google_review_url': request.POST.get('google_review_url') or ''}
                if rating_text:
                    payload['rating'] = int(rating_text)
                _api(request, f'reviews/{review_id}/', method='POST', payload=payload)
                return _redirect('reviews', 'review')

        data = {}
        context = {}
        query = str(request.GET.get('q') or '').strip()
        if section == 'bookings':
            context.update(_booking_context(request))
        elif section == 'patients':
            context.update(_patient_context(request))
        elif section == 'wallet':
            data = _api(request, 'customers/', query={'q': query})
            for customer in data.get('customers', []):
                cents = int(customer.get('credit_cents') or 0)
                customer['credit_eur'] = f'{cents / 100:.2f}'.replace('.', ',')
            context['query'] = query
        elif section == 'reviews':
            data = _api(request, 'reviews/')
        else:
            data = _api(request, 'referrals/')

        title, subtitle = SECTIONS[section]
        context.update({
            'section': section,
            'section_title': title,
            'section_subtitle': subtitle,
            'sections': SECTIONS,
            'data': data,
            'notice': request.GET.get('notice') or '',
        })
        return render(request, 'booking/app_management.html', context)
    except PermissionError as exc:
        return render(request, 'booking/app_management.html', {
            'section': section,
            'section_title': SECTIONS[section][0],
            'section_subtitle': SECTIONS[section][1],
            'sections': SECTIONS,
            'data': {},
            'error': str(exc),
            'needs_reauth': True,
        }, status=403)
    except (RuntimeError, ValueError, TypeError) as exc:
        return render(request, 'booking/app_management.html', {
            'section': section,
            'section_title': SECTIONS[section][0],
            'section_subtitle': SECTIONS[section][1],
            'sections': SECTIONS,
            'data': {},
            'error': str(exc),
        }, status=502)
