import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from . import patient_portal
from .customer_identity import duplicate_customer_groups, grouped_customers_for_display
from .models import Appointment, Customer, PatientRecord, WhatsAppTemplate


AESTHETIC_ADMIN_API = 'https://esthetic.smarbiz.sbs/api/mobile/admin'
SECTIONS = {
    'bookings': ('Termine', 'Reservierungen und Terminstatus verwalten'),
    'patients': ('Patientenakten', 'Dokumente, Termine, Punkte und Kommunikation an einem Ort'),
    'reviews': ('Google Bewertungen', 'Bewertungen verifizieren und Punkte erst nach Prüfung freigeben'),
    'wallet': ('A+ Punkte', 'Punktestände suchen, prüfen und manuell korrigieren'),
    'referrals': ('Empfehlungen', 'Empfehlungen an Freunde und Punkteaktivitäten im Blick behalten'),
    'invoices': ('Rechnungen', 'Rechnungen, Preise, MwSt und Abrechnungsdaten direkt in der App verwalten'),
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
    all_customers = list(Customer.objects.order_by('last_name', 'first_name', 'pk'))
    groups = duplicate_customer_groups(all_customers)
    group_by_customer_id = {}
    for group in groups:
        ids = [item.pk for item in group]
        for item in group:
            group_by_customer_id[item.pk] = ids

    customers = grouped_customers_for_display(all_customers, query=query)[:250]

    all_ids = [item.pk for item in all_customers]
    appointment_counts = {
        row['customer_id']: row['total']
        for row in Appointment.objects.filter(customer_id__in=all_ids)
        .values('customer_id').annotate(total=Count('id'))
    }
    record_counts = {
        row['customer_id']: row['total']
        for row in PatientRecord.objects.filter(customer_id__in=all_ids)
        .values('customer_id').annotate(total=Count('id'))
    }
    for customer in customers:
        group_ids = list(getattr(customer, 'display_group_ids', [customer.pk]))
        customer.display_appointment_count = sum(appointment_counts.get(pk, 0) for pk in group_ids)
        customer.display_record_count = sum(record_counts.get(pk, 0) for pk in group_ids)

    selected = None
    selected_group = []
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
        group_ids = group_by_customer_id.get(selected.pk, [selected.pk])
        selected_group = [item for item in all_customers if item.pk in set(group_ids)]
        selected.display_profile_count = len(selected_group)

        appointments = list(
            Appointment.objects.select_related('customer', 'service', 'staff')
            .filter(customer_id__in=group_ids)
            .order_by('-starts_at')[:180]
        )
        record_qs = (
            PatientRecord.objects.select_related('customer', 'appointment', 'uploaded_by')
            .filter(customer_id__in=group_ids)
            .order_by('-created_at')[:300]
        )
        for record in record_qs:
            metadata = record.metadata if isinstance(record.metadata, dict) else {}
            patient_source = record.source in patient_portal.APP_SHARED_SOURCES
            records.append({
                'id': str(record.public_id),
                'customer_id': record.customer_id,
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
                'open_count': int(metadata.get('customer_open_count') or 0),
                'download_count': int(metadata.get('customer_download_count') or 0),
                'last_opened_at': metadata.get('customer_last_open_at') or '',
                'last_downloaded_at': metadata.get('customer_last_download_at') or '',
            })

        # Prefer the selected profile contact data, then fall back to another linked profile.
        contact_customer = selected
        if not selected.phone:
            contact_customer = next((item for item in selected_group if item.phone), selected)
        phone = _wa_phone(contact_customer.phone)
        call_url = f'tel:{contact_customer.phone}' if contact_customer.phone else ''
        whatsapp_url = f'https://wa.me/{phone}' if phone else ''
        if phone:
            for template in WhatsAppTemplate.objects.filter(active=True):
                text = template.render_for(contact_customer)
                whatsapp_templates.append({
                    'id': template.pk,
                    'name': template.name,
                    'text': text,
                    'url': f'https://wa.me/{phone}?text={quote(text)}',
                })

        # Points live in the A+ customer account service. Try every linked e-mail
        # so a legacy Book duplicate still resolves to the existing app account.
        if _authorization(request):
            try:
                for candidate in [selected, *[item for item in selected_group if item.pk != selected.pk]]:
                    email = str(candidate.email or '').strip()
                    if not email:
                        continue
                    remote = _api(request, 'customers/', query={'q': email})
                    exact = next(
                        (
                            item for item in remote.get('customers', [])
                            if str(item.get('email') or '').strip().lower() == email.lower()
                        ),
                        None,
                    )
                    if exact:
                        points = int(exact.get('coins') or 0)
                        remote_customer_id = int(exact.get('id'))
                        break
            except (PermissionError, RuntimeError, ValueError, TypeError) as exc:
                points_error = str(exc)

    return {
        'query': query,
        'patients': customers,
        'selected_customer': selected,
        'selected_customer_profiles': selected_group,
        'selected_profile_count': len(selected_group),
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

    # Rechnungen has a dedicated web Office surface. When the focused A+ app
    # bearer token is not available (for example a direct desktop browser
    # visit), send staff to the browser-native Office instead of showing the
    # misleading "Admin-Sitzung fehlt" error. Inside the A+ app, the bearer
    # token is present and the integrated Rechnungen view continues to work.
    if section == 'invoices' and not _authorization(request):
        return redirect('https://office.a-esthetic.de/office/admin/')

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
            if action == 'billing_settings':
                payload = {
                    'company_name': request.POST.get('company_name') or 'A+ Esthetic GmbH',
                    'street': request.POST.get('street') or '',
                    'postal_code': request.POST.get('postal_code') or '',
                    'city': request.POST.get('city') or '',
                    'email': request.POST.get('email') or '',
                    'phone': request.POST.get('phone') or '',
                    'tax_number': request.POST.get('tax_number') or '',
                    'vat_id': request.POST.get('vat_id') or '',
                    'bank_name': request.POST.get('bank_name') or '',
                    'iban': request.POST.get('iban') or '',
                    'bic': request.POST.get('bic') or '',
                    'invoice_prefix': request.POST.get('invoice_prefix') or 'RE',
                    'next_sequence': int(request.POST.get('next_sequence') or 1),
                }
                _api(request, 'billing/settings/', method='POST', payload=payload)
                return _redirect('invoices', 'settings')

            if action == 'billing_service':
                service_id = int(request.POST.get('service_id'))
                _api(
                    request,
                    f'billing/services/{service_id}/',
                    method='POST',
                    payload={
                        'price': request.POST.get('price') or '',
                        'vat_rate': request.POST.get('vat_rate') or '',
                    },
                )
                return _redirect('invoices', 'service')

            if action == 'billing_create':
                _api(
                    request,
                    'billing/invoices/',
                    method='POST',
                    payload={
                        'customer_id': int(request.POST.get('customer_id')),
                        'service_id': int(request.POST.get('service_id')),
                        'service_date': request.POST.get('service_date') or '',
                    },
                )
                return _redirect('invoices', 'invoice')

            if action == 'billing_finalize':
                invoice_id = int(request.POST.get('invoice_id'))
                _api(request, f'billing/invoices/{invoice_id}/finalize/', method='POST', payload={})
                return _redirect('invoices', 'finalized')

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
        elif section == 'invoices':
            data = _api(request, 'billing/')
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
        if section == 'invoices':
            return redirect('https://office.a-esthetic.de/office/admin/')
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
