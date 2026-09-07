import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from . import patient_portal
from .models import Appointment, Customer, WhatsAppTemplate


AESTHETIC_ADMIN_API = 'https://esthetic.smarbiz.sbs/api/mobile/admin'
SECTIONS = {
    'bookings': ('Termine', 'Reservierungen und Terminstatus verwalten'),
    'patients': ('Patientenakten', 'Dokumente, Termine, Punkte und Kommunikation an einem Ort'),
    'reviews': ('Google Bewertungen', 'Bewertungen verifizieren und Punkte erst nach Prüfung freigeben'),
    'wallet': ('A+ Punkte', 'Punktestände suchen, prüfen und manuell korrigieren'),
    'referrals': ('Empfehlungen', 'Empfehlungen an Freunde und Punkteaktivitäten im Blick behalten'),
}


def _authorization(request):
    value = str(request.session.get('aplus_admin_authorization') or '').strip()
    return value if value.startswith('Bearer ') else ''


def _local_view_only(request):
    try:
        profile = request.user.aesthetic_access
    except Exception:
        profile = None
    return bool(profile and profile.view_only)


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
    headers = {'Authorization': authorization, 'Accept': 'application/json', 'User-Agent': 'A-Esthetic-Book-Focused-Admin/4.0'}
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


def _wa_phone(value):
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    if digits.startswith('00'):
        digits = digits[2:]
    elif digits.startswith('0'):
        digits = '49' + digits[1:]
    return digits


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
    return {
        'query': query,
        'status_filter': status,
        'status_choices': Appointment.STATUS,
        'upcoming': list(qs.filter(starts_at__gte=now).exclude(status='cancelled').order_by('starts_at')[:120]),
        'history': list(qs.filter(Q(starts_at__lt=now) | Q(status='cancelled')).order_by('-starts_at')[:180]),
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
    points = None
    remote_customer_id = None
    points_error = ''
    whatsapp_templates = []
    whatsapp_url = ''
    call_url = ''
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

        phone = _wa_phone(selected.phone)
        call_url = f'tel:{selected.phone}' if selected.phone else ''
        whatsapp_url = f'https://wa.me/{phone}' if phone else ''
        if phone:
            for template in WhatsAppTemplate.objects.filter(active=True):
                text = template.render_for(selected)
                whatsapp_templates.append({
                    'id': template.pk,
                    'name': template.name,
                    'text': text,
                    'url': f'https://wa.me/{phone}?text={quote(text)}',
                })

        # Points live in the A+ customer account service. A local view-only doctor
        # can still open the complete Book record without a remote bearer token.
        if _authorization(request):
            try:
                remote = _api(request, 'customers/', query={'q': selected.email})
                exact = next(
                    (item for item in remote.get('customers', []) if str(item.get('email') or '').strip().lower() == selected.email.strip().lower()),
                    None,
                )
                if exact:
                    points = int(exact.get('coins') or 0)
                    remote_customer_id = int(exact.get('id'))
            except (PermissionError, RuntimeError, ValueError, TypeError) as exc:
                points_error = str(exc)

    return {
        'query': query,
        'patients': customers,
        'selected_customer': selected,
        'patient_records': records,
        'patient_appointments': appointments,
        'selected_points': points,
        'remote_customer_id': remote_customer_id,
        'points_error': points_error,
        'call_url': call_url,
        'whatsapp_url': whatsapp_url,
        'whatsapp_templates': whatsapp_templates,
        'salutation_choices': Customer.SALUTATION,
        'view_only': _local_view_only(request),
    }


@never_cache
@staff_member_required(login_url='/verwaltung/login/')
@require_http_methods(['GET', 'POST'])
def app_management(request, section='bookings'):
    if section == 'bookings':
        return redirect('/verwaltung/kalender/')
    if section not in SECTIONS:
        section = 'patients'

    local_view_only = _local_view_only(request)
    if not request.session.get('aplus_app_admin') and not local_view_only:
        return HttpResponseForbidden('A+ App Management ist nur über eine bestätigte A+ Admin-Sitzung verfügbar.')
    if local_view_only and not request.session.get('aplus_app_admin') and section != 'patients':
        return redirect('/verwaltung/app/patients/')

    try:
        if request.method == 'POST':
            if local_view_only:
                return HttpResponseForbidden('Dieser Zugang ist nur zum Ansehen freigeschaltet.')
            action = str(request.POST.get('action') or '')
            if action == 'patient_upload':
                return patient_portal.staff_add_record(request, int(request.POST.get('customer_id')))
            if action == 'patient_salutation':
                customer = Customer.objects.get(pk=int(request.POST.get('customer_id')))
                value = str(request.POST.get('salutation') or '')
                if value not in {key for key, _ in Customer.SALUTATION}:
                    raise ValueError('Ungültige Anrede.')
                customer.salutation = value
                customer.save(update_fields=['salutation', 'updated_at'])
                return redirect(f'/verwaltung/app/patients/?customer={customer.pk}&notice=profile')
            if action == 'patient_points_adjust':
                remote_id = int(request.POST.get('remote_customer_id'))
                delta = int(request.POST.get('point_delta') or 0)
                if not delta:
                    raise ValueError('Bitte eine Punktzahl größer oder kleiner als 0 eingeben.')
                _api(request, f'customers/{remote_id}/', method='POST', payload={'coin_delta': delta})
                local_id = int(request.POST.get('customer_id'))
                return redirect(f'/verwaltung/app/patients/?customer={local_id}&notice=points')
            if action == 'wallet_adjust':
                customer_id = int(request.POST.get('customer_id'))
                delta = int(request.POST.get('point_delta') or 0)
                if not delta:
                    raise ValueError('Bitte eine Punktzahl größer oder kleiner als 0 eingeben.')
                _api(request, f'customers/{customer_id}/', method='POST', payload={'coin_delta': delta})
                return _redirect('wallet', 'points')
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
        if section == 'patients':
            context.update(_patient_context(request))
        elif section == 'wallet':
            data = _api(request, 'customers/', query={'q': query})
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
            'view_only': local_view_only,
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
            'view_only': local_view_only,
        }, status=403)
    except (RuntimeError, ValueError, TypeError, Customer.DoesNotExist) as exc:
        return render(request, 'booking/app_management.html', {
            'section': section,
            'section_title': SECTIONS[section][0],
            'section_subtitle': SECTIONS[section][1],
            'sections': SECTIONS,
            'data': {},
            'error': str(exc),
            'view_only': local_view_only,
        }, status=502)
