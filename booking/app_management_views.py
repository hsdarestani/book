from .record_previews import file_kind
import base64
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from . import patient_portal
from .clinical_time import clinic_localtime
from .invoice_bridge import _request_bridge
from .patient_identity_review import approved_patient_groups, approved_patient_representatives, possible_duplicate_pairs
from .models import Appointment, Customer, PatientRecord, OfficeIntakeForm, WhatsAppTemplate, Service
from .intake_identity import intake_review_candidates
from .intake_forms import confirm_form_link
from .goae_treatment_cards import treatment_cards


AESTHETIC_ADMIN_API = 'https://esthetic.smarbiz.sbs/api/mobile/admin'
SECTIONS = {
    'bookings': ('Termine', 'Reservierungen und Terminstatus verwalten'),
    'patients': ('Patienten & Akten', 'Dokumente, Termine, Punkte und Kommunikation an einem Ort'),
    'reviews': ('Google Bewertungen', 'Bewertungen verifizieren und Punkte erst nach Prüfung freigeben'),
    'wallet': ('A+ Punkte', 'Punktestände suchen, prüfen und manuell korrigieren'),
    'referrals': ('Empfehlungen', 'Empfehlungen an Freunde und Punkteaktivitäten im Blick behalten'),
    'hero': ('Startseitenbilder', 'Bilder für Damen, Herren und als Standard festlegen'),
    'invoices': ('Rechnungen', 'GOÄ und Rechnungen zentral im Praxismanagement verwalten'),
    'forms': ('Aufnahmebögen', 'Digitale Aufnahmeformulare, Zuordnung und Patientenakten'),
}


class AppAdminSessionRequired(PermissionError):
    """The patient app must authenticate this staff member again."""


APP_SESSION_REQUIRED = 'Bitte öffnen Sie die Verwaltung erneut aus der A+ App.'


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
        raise AppAdminSessionRequired(APP_SESSION_REQUIRED)
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
    # A single upstream response must never erase a newer credential stored by
    # another tab. The patient app validates the bearer on every operation.
    if status == 401:
        raise AppAdminSessionRequired(APP_SESSION_REQUIRED)
    if status == 403:
        raise PermissionError('Diese Funktion erfordert eine Freigabe in der A+ App.')
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError('Ungültige Antwort der A+ API') from exc
    if not isinstance(data, dict):
        raise RuntimeError('Ungültige Antwort der A+ API')
    if status >= 400 or not data.get('ok', False):
        raise RuntimeError(data.get('error') or f'A+ API Fehler {status}')
    return data


def _billing_api(request, endpoint, method='GET', payload=None):
    """Use existing app admin session when available, else the private bridge.

    Both methods operate on the same App Invoice and InvoiceSettings tables.
    """
    if _authorization(request) and endpoint not in {'billing/goae/', 'billing/quote/'}:
        try:
            return _api(request, endpoint, method=method, payload=payload)
        except PermissionError:
            # Expired app bearer: still allow verified Booking staff via
            # the server-only credential; never redirect to another domain.
            pass
    if endpoint == 'billing/':
        operation = 'overview'
    elif endpoint == 'billing/settings/':
        operation = 'settings'
    elif endpoint == 'billing/invoices/':
        operation = 'invoices'
    elif endpoint == 'billing/goae/':
        operation = 'goae'
    elif endpoint == 'billing/quote/':
        operation = 'quote'
    elif endpoint.startswith('billing/services/') and endpoint.endswith('/'):
        number = endpoint.removeprefix('billing/services/').strip('/')
        if not number.isdecimal():
            raise ValueError('Ungültige Behandlung.')
        operation = f'services/{number}'
    elif endpoint.startswith('billing/invoices/') and endpoint.endswith('/finalize/'):
        number = endpoint.removeprefix('billing/invoices/').removesuffix('/finalize/')
        if not number.isdecimal():
            raise ValueError('Ungültige Rechnung.')
        operation = f'finalize/{number}'
    else:
        raise ValueError('Unbekannte Rechnungsfunktion.')
    return _request_bridge(request, operation, method=method, payload=payload)


def _referral_date(value):
    try:
        parsed = parse_datetime(str(value or ''))
    except ValueError:
        return ''
    return clinic_localtime(parsed).strftime('%d.%m.%Y') if parsed and timezone.is_aware(parsed) else ''


def _referral_rows(data):
    return [dict(item, invited_date=_referral_date(item.get('created_at')),
                 awarded_date=_referral_date(item.get('rewarded_at')),
                 points_awarded=item.get('status') == 'rewarded' or bool(item.get('rewarded_at')))
            for item in (data.get('referrals') or []) if isinstance(item, dict)]


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


def _forms_context(request):
    q=str(request.GET.get('q') or '').strip()[:120]
    status=str(request.GET.get('status') or '').strip()
    since=str(request.GET.get('from') or '').strip()
    until=str(request.GET.get('to') or '').strip()
    qs=OfficeIntakeForm.objects.select_related('customer','record','reviewed_by')
    if q:
        qs=qs.filter(
            Q(customer__first_name__icontains=q)|Q(customer__last_name__icontains=q)
            |Q(customer__email__icontains=q)|Q(customer__phone__icontains=q)
            |Q(payload__identity__first_name__icontains=q)
            |Q(payload__identity__last_name__icontains=q)
            |Q(payload__identity__email__icontains=q)
            |Q(payload__identity__phone__icontains=q))
    if status in {'linked','review'}:qs=qs.filter(status=status)
    else:status=''
    from datetime import datetime
    from django.utils.dateparse import parse_date
    def filter_date(value):
        if not value:
            return None
        try:
            return datetime.strptime(value, '%d.%m.%Y').date() if '.' in value else parse_date(value)
        except ValueError:
            return None
    start=filter_date(since)
    end=filter_date(until)
    if start:qs=qs.filter(submitted_at__date__gte=start)
    if end:qs=qs.filter(submitted_at__date__lte=end)
    results=list(qs.order_by('-submitted_at')[:250])
    raw_id=str(request.GET.get('form') or '')
    selected=OfficeIntakeForm.objects.select_related('customer','record').filter(pk=int(raw_id)).first() if raw_id.isdigit() else None
    return {'intake_forms':results,'selected_intake_form':selected,
        'form_query':q,'form_status':status,'form_from':start.strftime('%d.%m.%Y') if start else since[:10],
        'form_to':end.strftime('%d.%m.%Y') if end else until[:10],
        'form_date_error':bool((since and not start) or (until and not end)),
        'form_total':OfficeIntakeForm.objects.count(),
        'form_open':OfficeIntakeForm.objects.filter(status='review').count(),
        'link_candidates': intake_review_candidates(selected.payload.get('identity') or {})
                            if selected and selected.status == 'review' else []}


def _patient_context(request):
    from .doctor_views import _doctor_staff, _own_customer_ids
    query = str(request.GET.get('q') or '').strip()
    doctor_staff = _doctor_staff(request)
    qs = Customer.objects.order_by('last_name', 'first_name', 'pk')
    if doctor_staff:
        qs = qs.filter(pk__in=_own_customer_ids(doctor_staff))
    all_customers = list(qs)
    groups = approved_patient_groups(all_customers)
    group_by_customer_id = {}
    for group in groups:
        ids = [item.pk for item in group]
        for item in group:
            group_by_customer_id[item.pk] = ids

    matching_customers = approved_patient_representatives(all_customers, query=query)
    customers = matching_customers[:250]

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
    patient_forms = []
    appointments = []
    points = None
    remote_customer_id = None
    points_error = ''
    whatsapp_templates = []
    whatsapp_url = ''
    call_url = ''
    raw_customer = str(request.GET.get('customer') or '').strip()
    if raw_customer.isdigit():
        selected = next((c for c in all_customers if c.pk == int(raw_customer)), None)
        if selected is None and doctor_staff:
            raise PermissionError('Patient ist diesem Arzt nicht zugeordnet.')
    if selected:
        group_ids = group_by_customer_id.get(selected.pk, [selected.pk])
        selected_group = [item for item in all_customers if item.pk in set(group_ids)]
        selected.display_profile_count = len(selected_group)
        selected.identity_sources = []
        for linked in sorted(selected_group, key=lambda item: item.pk):
            selected.identity_sources.append({
                'id': linked.pk,
                'email': linked.email,
                'phone': linked.phone,
                'name': linked.full_name,
                'appointments': appointment_counts.get(linked.pk, 0),
                'documents': record_counts.get(linked.pk, 0),
                'is_current': linked.pk == selected.pk,
            })

        appointments = list(
            Appointment.objects.select_related('customer', 'service', 'staff')
            .filter(customer_id__in=group_ids)
            .order_by('-starts_at')[:180]
        )
        patient_forms = list(OfficeIntakeForm.objects.filter(customer_id__in=group_ids).order_by('-submitted_at')[:150])
        record_qs = (
            PatientRecord.objects.select_related('customer', 'appointment', 'uploaded_by')
            .filter(customer_id__in=group_ids)
            .order_by('-created_at')[:300]
        )
        for record in record_qs:
            metadata = record.metadata if isinstance(record.metadata, dict) else {}
            patient_source = record.source in patient_portal.APP_SHARED_SOURCES
            preview_kind = file_kind(record)
            records.append({
                'id': str(record.public_id),
                'customer_id': record.customer_id,
                'kind': record.kind,
                'kind_label': record.get_kind_display(),
                'title': record.title,
                'note': record.note,
                'has_file': record.has_file,
                'preview_kind': preview_kind,
                'preview_label': {'pdf': 'PDF', 'image': 'BILD', 'text': 'TEXT', 'document': 'DATEI'}[preview_kind],
                'file_size': record.file_size,
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
        if not selected.contact_phone and selected.contact_phone_override is None:
            contact_customer = next((item for item in selected_group if item.contact_phone), selected)
        phone = _wa_phone(contact_customer.contact_phone)
        call_url = f'tel:{contact_customer.contact_phone}' if contact_customer.contact_phone else ''
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
        'matching_patient_count': len(matching_customers),
        'selected_customer': selected,
        'selected_customer_profiles': selected_group,
        'selected_profile_count': len(selected_group),
        'patient_records': records,
        'patient_forms': patient_forms,
        'patient_appointments': appointments,
        'selected_points': points,
        'remote_customer_id': remote_customer_id,
        'points_error': points_error,
        'call_url': call_url,
        'whatsapp_url': whatsapp_url,
        'whatsapp_templates': whatsapp_templates,
        'salutation_choices': Customer.SALUTATION,
        'view_only': _local_view_only(request),
        'can_review_patient_links': bool(request.session.get('aplus_app_admin') is True and not _local_view_only(request)),
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

    # Rechnungen is a first-party Booking admin page for authenticated staff,
    # even without a mobile-app bearer token. The server performs the billing
    # API request; invoice credentials never reach the browser.
    if section in {'invoices','forms'} and local_view_only:
        return HttpResponseForbidden('Dieses Arztkonto hat keinen Rechnungszugriff.')
    if section not in {'invoices','forms'} and not request.session.get('aplus_app_admin') and not local_view_only:
        if section == 'referrals':
            return render(request, 'booking/app_management.html', {
                'section': section, 'section_title': SECTIONS[section][0],
                'section_subtitle': SECTIONS[section][1], 'error': APP_SESSION_REQUIRED,
            }, status=403)
        return HttpResponseForbidden('A+ App Management ist nur über eine bestätigte A+ Admin-Sitzung verfügbar.')
    if section not in {'invoices','forms'} and local_view_only and not request.session.get('aplus_app_admin') and section != 'patients':
        return redirect('/verwaltung/app/patients/')

    if section == 'patients' and request.method == 'GET' and 'export' in request.GET:
        if local_view_only or request.session.get('aplus_app_admin') is not True:
            return HttpResponseForbidden('Kundenexport nur für bestätigte Administratoren.')
        from .customer_export import customer_csv_export
        return customer_csv_export(request)

    goae_draft_json = (
        section == 'invoices' and request.method == 'POST'
        and request.headers.get('Accept') == 'application/json'
        and request.POST.get('action') == 'billing_create_goae_full'
    )
    try:
        if request.method == 'POST':
            action = str(request.POST.get('action') or '')
            if local_view_only:
                from .doctor_views import _doctor_staff, _own_customer_ids
                doctor_staff = _doctor_staff(request)
                selected_id = str(request.POST.get('customer_id') or '')
                if not (doctor_staff and section == 'patients' and action == 'patient_upload'
                        and selected_id.isdigit() and int(selected_id) in _own_customer_ids(doctor_staff)):
                    return HttpResponseForbidden('Aktion für dieses Arztkonto nicht erlaubt.')
                return patient_portal.staff_add_record(request, int(selected_id))
            if section == 'hero' and action in {'hero_upload', 'hero_clear'}:
                variant = str(request.POST.get('variant') or '')
                if variant not in {'frau', 'herr', 'default'}:
                    raise ValueError('Bitte eine gültige Bildkategorie auswählen.')
                payload = {'variant': variant, 'action': 'clear' if action == 'hero_clear' else 'save'}
                if action == 'hero_upload':
                    upload = request.FILES.get('hero_image')
                    if upload is None:
                        raise ValueError('Bitte zuerst ein Bild auswählen.')
                    if upload.size > 6 * 1024 * 1024 or upload.size <= 0:
                        raise ValueError('Das Bild darf maximal 6 MB groß sein.')
                    mime = (upload.content_type or '').lower()
                    if mime not in {'image/jpeg', 'image/png', 'image/webp'}:
                        raise ValueError('Bitte ein JPG, PNG oder WebP Bild verwenden.')
                    payload['image_type'] = mime
                    payload['image_data'] = base64.b64encode(upload.read()).decode('ascii')
                _api(request, 'dashboard-hero/', method='POST', payload=payload)
                return _redirect('hero', 'image')
            if section == 'forms' and action == 'link_form':
                if request.POST.get('confirmed_same_patient') != 'on':
                    raise ValueError('Bitte die Identität vor der Zuordnung bestätigen.')
                confirmed=confirm_form_link(int(request.POST.get('form_id')),int(request.POST.get('customer_id')),request.user)
                return _redirect('forms','linked',{'form':confirmed.pk})
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
            if action == 'patient_goae_draft':
                customer = Customer.objects.get(pk=int(request.POST.get('customer_id')))
                response = _api(request, 'customers/', query={'q': customer.email})
                customer_row = next((item for item in response.get('customers', [])
                                     if str(item.get('email') or '').lower() == customer.email.lower()), None)
                if not customer_row:
                    raise ValueError('Patient ist noch keinem App-Konto zugeordnet.')
                payload = {
                    'billing_method': 'goae',
                    'customer_id': customer_row['id'],
                    'service_date': request.POST.get('service_date') or '',
                    'goae_number': request.POST.get('goae_number') or '',
                    'goae_description': request.POST.get('goae_description') or '',
                    'goae_base_eur': request.POST.get('goae_base_eur') or '',
                    'goae_factor': request.POST.get('goae_factor') or '',
                    'goae_vat_rate': request.POST.get('goae_vat_rate'),
                    'goae_justification': request.POST.get('goae_justification') or '',
                }
                _api(request, 'billing/invoices/', method='POST', payload=payload)
                return redirect(f'/verwaltung/app/patients/?customer={customer.pk}&notice=goae_draft#records')
            if action == 'patient_points_adjust':
                remote_id = int(request.POST.get('remote_customer_id'))
                delta = int(request.POST.get('point_delta') or 0)
                if not delta:
                    raise ValueError('Bitte eine Punktzahl größer oder kleiner als 0 eingeben.')
                _api(request, f'customers/{remote_id}/', method='POST', payload={'coin_delta': delta})
                local_id = int(request.POST.get('customer_id'))
                return redirect(f'/verwaltung/app/patients/?customer={local_id}&notice=points#points')
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
                _billing_api(request, 'billing/settings/', method='POST', payload=payload)
                return _redirect('invoices', 'settings')

            if action == 'billing_service':
                service_id = int(request.POST.get('service_id'))
                _billing_api(
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
                _billing_api(
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

            if action == 'billing_create_goae_full':
                lines=json.loads(request.POST.get('goae_lines_json') or '[]')
                if not isinstance(lines,list) or not 1 <= len(lines) <= 50:
                    raise ValueError('Bitte eine bis 50 GOÄ Positionen angeben.')
                payload = {
                    'billing_method': 'goae', 'customer_id': int(request.POST.get('customer_id')),
                    'service_date': str(request.POST.get('service_date') or ''), 'lines': lines,
                    **({'target_total_cents': int(request.POST['goae_target_cents'])}
                       if request.POST.get('goae_target_cents') else {}),
                }
                if request.POST.get('book_preview'):
                    payload['book_preview'] = json.loads(request.POST['book_preview'])
                request_id = request.POST.get('draft_request_id')
                if request_id or goae_draft_json:
                    if not request_id:
                        raise ValueError('Entwurfsanfrage fehlt. Bitte Seite neu laden.')
                    payload['draft_request_id'] = request_id
                    _request_bridge(request, 'draft', method='POST', payload=payload)
                else:
                    _billing_api(request, 'billing/invoices/', method='POST', payload=payload)
                result = _redirect('invoices', 'goae_draft')
                if goae_draft_json:
                    return JsonResponse({'ok': True, 'location': result.url})
                return result
            if action == 'billing_create_goae':
                payload = {
                    'billing_method': 'goae',
                    'customer_id': int(request.POST.get('customer_id')),
                    'service_date': str(request.POST.get('service_date') or ''),
                    'goae_number': str(request.POST.get('goae_number') or '').strip(),
                    'goae_description': str(request.POST.get('goae_description') or '').strip(),
                    'goae_base_eur': str(request.POST.get('goae_base_eur') or '').strip(),
                    'goae_factor': str(request.POST.get('goae_factor') or '').strip(),
                    'goae_vat_rate': str(request.POST.get('goae_vat_rate') or '').strip(),
                    'goae_justification': str(request.POST.get('goae_justification') or '').strip(),
                }
                _billing_api(request, 'billing/invoices/', method='POST', payload=payload)
                return _redirect('invoices', 'goae_draft')

            if action == 'billing_finalize':
                invoice_id = int(request.POST.get('invoice_id'))
                _billing_api(request, f'billing/invoices/{invoice_id}/finalize/', method='POST', payload={})
                return _redirect('invoices', 'finalized')

        data = {}
        context = {}
        query = str(request.GET.get('q') or '').strip()
        if section == 'patients':
            # Render exactly one patient tab on the server, not four sections
            # whose visibility depends on JS/CSS loading in the browser.
            allowed_tabs = {'overview', 'appointments', 'records', 'forms', 'points'}
            tab = str(request.GET.get('tab') or '').strip().lower()
            context['customer_tab'] = tab if tab in allowed_tabs else 'overview'
            context['max_upload_mb'] = max(1, settings.PATIENT_FILE_MAX_BYTES // (1024 * 1024))
            context.update(_patient_context(request))
        elif section == 'wallet':
            data = _api(request, 'customers/', query={'q': query})
            context['query'] = query
        elif section == 'hero':
            data = _api(request, 'dashboard-hero/')
            context['hero_images'] = data.get('hero_images') or []
        elif section == 'reviews':
            data = _api(request, 'reviews/')
        elif section == 'forms':
            context.update(_forms_context(request))
        elif section == 'invoices':
            data = _billing_api(request, 'billing/')
            clinic_services = list(Service.objects.filter(active=True).order_by('name').values('name', 'slug'))
            context['goae_invoices'] = [inv for inv in (data.get('invoices') or [])
                if inv.get('billing_method') == 'goae']
            try:
                catalog_data = _billing_api(request,'billing/goae/')
                context['goae_catalog'] = catalog_data.get('catalog',[])
                context['goae_treatments'] = catalog_data.get('treatments',{})
                context['goae_quick_templates'] = catalog_data.get('quick_templates', {})
                context['goae_quick_date'] = clinic_localtime().date().isoformat()
            except (RuntimeError,ValueError,PermissionError):
                context['goae_catalog'] = []
                context['goae_treatments'] = {}
            quick_templates = context.get('goae_quick_templates', {})
            context['goae_quick_choices'] = [
                {'key': item['slug'], 'label': item['name'],
                 'version': quick_templates.get(item['slug'], {}).get('version', '')}
                for item in clinic_services
            ]
            context['goae_quick_date'] = clinic_localtime().date().isoformat()
            context['goae_treatment_cards'] = treatment_cards(clinic_services, context['goae_treatments'])
        else:
            data = _api(request, 'referrals/')
            context['referrals'] = _referral_rows(data)
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
        if goae_draft_json:
            return JsonResponse({'ok': False, 'message': str(exc)}, status=403)
        return render(request, 'booking/app_management.html', {
            'section': section,
            'section_title': SECTIONS[section][0],
            'section_subtitle': SECTIONS[section][1],
            'sections': SECTIONS,
            'data': {},
            'error': str(exc),
            'view_only': local_view_only,
        }, status=403)
    except (RuntimeError, ValueError, TypeError, Customer.DoesNotExist) as exc:
        if goae_draft_json:
            if isinstance(exc, (ValueError, TypeError)):
                return JsonResponse({'ok': False, 'message': str(exc)}, status=400)
            return JsonResponse({'ok': False, 'message': 'Speicherung konnte nicht bestätigt werden. Bitte erneut versuchen.'}, status=502)
        hero_slots = []
        if section == 'hero' and isinstance(exc, ValueError):
            # Input errors stay on the editable form, instead of a generic 502.
            try:
                hero_slots = _api(request, 'dashboard-hero/').get('hero_images') or []
            except (PermissionError, RuntimeError):
                pass
        return render(request, 'booking/app_management.html', {
            'section': section,
            'section_title': SECTIONS[section][0],
            'section_subtitle': SECTIONS[section][1],
            'sections': SECTIONS,
            'data': {},
            'error': str(exc),
            'view_only': local_view_only,
            'hero_images': hero_slots,
        }, status=400 if section in {'hero', 'invoices'} and isinstance(exc, ValueError) else 502)
