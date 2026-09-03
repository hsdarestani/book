import calendar
import json
import os
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from booking.models import Appointment, Customer, DailyAvailabilityOverride, Service, StaffMember


LOGIN_URL = 'https://user-api.simplybook.me/login'
ADMIN_URL = 'https://user-api.simplybook.me/admin'


class RpcError(RuntimeError):
    pass


def rpc(url, method, params, headers=None, timeout=120):
    payload = json.dumps({'jsonrpc': '2.0', 'method': method, 'params': params, 'id': 1}).encode('utf-8')
    request = urllib.request.Request(
        url,
        data=payload,
        headers={'Content-Type': 'application/json', **(headers or {})},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')[:800]
        raise RpcError(f'HTTP {exc.code} calling {method}: {detail}') from exc
    except urllib.error.URLError as exc:
        raise RpcError(f'Network error calling {method}: {exc}') from exc
    if body.get('error'):
        error = body['error']
        raise RpcError(f"RPC {method} failed: {error.get('code')} {error.get('message')} {error.get('data', '')}")
    return body.get('result')


def as_bool(value):
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def split_name(value):
    parts = str(value or '').strip().split()
    if not parts:
        return 'SimplyBook', 'Kunde'
    if len(parts) == 1:
        return parts[0][:80], ''
    return ' '.join(parts[:-1])[:80], parts[-1][:80]


def parse_source_datetime(value, source_tz):
    raw = str(value or '').strip()
    if not raw:
        return None
    parsed = None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            parsed = datetime.strptime(raw, fmt)
            break
        except ValueError:
            pass
    if not parsed:
        return None
    return parsed.replace(tzinfo=source_tz).astimezone(timezone.get_current_timezone())


def parse_clock(value):
    raw = str(value or '').strip()
    if not raw:
        return None
    if raw == '24:00:00' or raw == '24:00':
        return datetime.strptime('23:59', '%H:%M').time()
    for fmt in ('%H:%M:%S', '%H:%M'):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            pass
    return None


def month_iter(start_day, end_day):
    current = date(start_day.year, start_day.month, 1)
    last = date(end_day.year, end_day.month, 1)
    while current <= last:
        yield current.year, current.month
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)


class Command(BaseCommand):
    help = 'Imports SimplyBook clients, services, provider, bookings and dated work calendar. Idempotent; sends no emails.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Run the complete import and roll back database writes.')
        parser.add_argument('--backup', default='', help='Optional JSON backup path for raw SimplyBook payloads.')

    def handle(self, *args, **options):
        company = (os.environ.get('SIMPLYBOOK_COMPANY_LOGIN') or '').strip()
        user = (os.environ.get('SIMPLYBOOK_USER_LOGIN') or '').strip()
        credential = (os.environ.get('SIMPLYBOOK_API_USER_KEY') or os.environ.get('SIMPLYBOOK_USER_PASSWORD') or '').strip()
        if not company or not user or not credential:
            raise CommandError('SimplyBook credentials are missing from environment.')

        self.stdout.write('SimplyBook import: authenticating…')
        token = rpc(LOGIN_URL, 'getUserToken', [company, user, credential])
        if not token:
            raise CommandError('SimplyBook returned an empty user token.')
        headers = {'X-Company-Login': company, 'X-User-Token': token}

        company_info = rpc(ADMIN_URL, 'getCompanyInfo', [], headers=headers) or {}
        timezone_info = rpc(ADMIN_URL, 'getCompanyTimezoneOffset', [], headers=headers) or {}
        services_raw = rpc(ADMIN_URL, 'getEventList', [False, True, None, ''], headers=headers) or []
        providers_raw = rpc(ADMIN_URL, 'getUnitList', [False, True, None, ''], headers=headers) or []
        clients_raw = rpc(ADMIN_URL, 'getClientList', ['', None], headers=headers) or []
        bookings_raw = rpc(ADMIN_URL, 'getBookings', [{
            'date_from': '2000-01-01',
            'date_to': '2035-12-31',
            'booking_type': 'all',
            'order': 'date_start_asc',
        }], headers=headers) or []

        raw_backup = {
            'exported_at': timezone.now().isoformat(),
            'company': company_info,
            'timezone': timezone_info,
            'services': services_raw,
            'providers': providers_raw,
            'clients': clients_raw,
            'bookings': bookings_raw,
            'work_calendars': {},
            'extra': {},
        }

        # Preserve extra account-level datasets when the enabled SimplyBook features expose them.
        optional_calls = {
            'cancellation_policy': ('getCancellationPolicy', []),
            'categories': ('getCategoriesList', [False]),
            'locations': ('getLocationsList', [False]),
            'company_vacations': ('getCompanyVacations', []),
            'products': ('getProductList', []),
            'feedbacks': ('getFeedbacks', []),
            'plugin_list': ('getPluginList', []),
            'currency': ('getCompanyCurrency', []),
        }
        for key, (method, params) in optional_calls.items():
            try:
                raw_backup['extra'][key] = rpc(ADMIN_URL, method, params, headers=headers)
            except Exception as exc:
                raw_backup['extra'][key] = {'_unavailable': str(exc)[:400]}

        additional_fields = {}
        for item in services_raw:
            event_id = str(item.get('id') or '') if isinstance(item, dict) else ''
            if not event_id:
                continue
            try:
                additional_fields[event_id] = rpc(ADMIN_URL, 'getAdditionalFields', [int(event_id)], headers=headers)
            except Exception as exc:
                additional_fields[event_id] = {'_unavailable': str(exc)[:300]}
        raw_backup['extra']['additional_fields_by_service'] = additional_fields

        tz_name = str(timezone_info.get('timezone') or 'Europe/Berlin') if isinstance(timezone_info, dict) else 'Europe/Berlin'
        try:
            source_tz = ZoneInfo(tz_name)
        except Exception:
            source_tz = ZoneInfo('Europe/Berlin')

        booking_dates = []
        for row in bookings_raw:
            parsed = parse_source_datetime(row.get('start_date'), source_tz) if isinstance(row, dict) else None
            if parsed:
                booking_dates.append(parsed.date())
        schedule_start = min(booking_dates) if booking_dates else timezone.localdate() - timedelta(days=365)
        schedule_end = max(booking_dates) if booking_dates else timezone.localdate() + timedelta(days=365)
        schedule_end = max(schedule_end, timezone.localdate() + timedelta(days=180))

        provider_source = providers_raw[0] if providers_raw and isinstance(providers_raw[0], dict) else {}
        provider_external_id = str(provider_source.get('id') or 'source')
        for year, month in month_iter(schedule_start, schedule_end):
            try:
                raw_backup['work_calendars'][f'{year:04d}-{month:02d}'] = rpc(
                    ADMIN_URL, 'getWorkCalendar', [year, month, safe_int(provider_external_id, 0)], headers=headers
                ) or {}
            except Exception as exc:
                raw_backup['work_calendars'][f'{year:04d}-{month:02d}'] = {'_unavailable': str(exc)[:300]}

        backup_path = (options.get('backup') or '').strip()
        if backup_path:
            target = Path(backup_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(raw_backup, ensure_ascii=False, indent=2), encoding='utf-8')
            try:
                target.chmod(0o600)
            except OSError:
                pass
            self.stdout.write(f'Raw SimplyBook backup written: {target}')

        summary = {
            'source_clients': len(clients_raw),
            'source_bookings': len(bookings_raw),
            'source_services': len(services_raw),
            'source_providers': len(providers_raw),
            'customers_created': 0,
            'customers_matched': 0,
            'services_created': 0,
            'services_updated': 0,
            'appointments_created': 0,
            'appointments_updated': 0,
            'daily_schedules_written': 0,
            'skipped_bookings': 0,
        }

        with transaction.atomic():
            # Keep the source provider visible in the admin calendar but isolated from the public booking catalogue.
            archive_provider, _ = StaffMember.objects.get_or_create(
                display_name=f'A+ Esthetic (SimplyBook #{provider_external_id})',
                defaults={
                    'role': 'team',
                    'bio': 'Importierter SimplyBook-Bestand. Nicht für neue Online-Buchungen verwenden.',
                    'active': True,
                    'sort_order': 9000,
                },
            )
            archive_provider.role = 'team'
            archive_provider.active = True
            archive_provider.sort_order = 9000
            archive_provider.bio = 'Importierter SimplyBook-Bestand. Nicht für neue Online-Buchungen verwenden.'
            archive_provider.save(update_fields=['role', 'active', 'sort_order', 'bio'])

            service_map = {}
            archive_services = []
            for idx, row in enumerate(services_raw, start=1):
                if not isinstance(row, dict):
                    continue
                external_id = str(row.get('id') or '').strip()
                if not external_id:
                    continue
                duration = max(5, safe_int(row.get('duration'), 30))
                before = max(0, safe_int(row.get('buffertime_before'), 0))
                after = max(0, safe_int(row.get('buffertime_after'), 0))
                service, created = Service.objects.update_or_create(
                    slug=f'simplybook-event-{external_id}',
                    defaults={
                        'name': str(row.get('name') or f'SimplyBook Service {external_id}').strip()[:140],
                        'description': str(row.get('description') or '')[:4000],
                        'duration_minutes': duration,
                        'buffer_minutes': before + after,
                        'price_label': '',
                        'active': as_bool(row.get('is_active', True)),
                        'bookable': False,
                        'requires_confirmation': False,
                        'sort_order': 5000 + safe_int(row.get('position'), idx),
                    },
                )
                summary['services_created' if created else 'services_updated'] += 1
                service_map[external_id] = service
                archive_services.append(service)
            archive_provider.services.set(archive_services)

            customer_map = {}
            for row in clients_raw:
                if not isinstance(row, dict):
                    continue
                external_id = str(row.get('id') or '').strip()
                if not external_id:
                    continue
                source_email = str(row.get('email') or '').strip().lower()
                valid_email = '@' in source_email and len(source_email) <= 254
                email = source_email if valid_email else f'simplybook-client-{external_id}@invalid.local'
                first_name, last_name = split_name(row.get('name'))
                phone = str(row.get('phone') or '').strip()[:40]
                customer = Customer.objects.filter(email__iexact=email).order_by('pk').first()
                if customer:
                    summary['customers_matched'] += 1
                    changed = []
                    if not customer.first_name and first_name:
                        customer.first_name = first_name
                        changed.append('first_name')
                    if not customer.last_name and last_name:
                        customer.last_name = last_name
                        changed.append('last_name')
                    if not customer.phone and phone:
                        customer.phone = phone
                        changed.append('phone')
                    if changed:
                        customer.save(update_fields=changed + ['updated_at'])
                else:
                    customer = Customer.objects.create(
                        first_name=first_name,
                        last_name=last_name,
                        phone=phone,
                        email=email,
                    )
                    summary['customers_created'] += 1
                customer_map[external_id] = customer

            client_booking_counts = {}
            for row in bookings_raw:
                if isinstance(row, dict):
                    client_id = str(row.get('client_id') or '')
                    client_booking_counts[client_id] = client_booking_counts.get(client_id, 0) + 1

            for row in bookings_raw:
                if not isinstance(row, dict):
                    summary['skipped_bookings'] += 1
                    continue
                booking_id = str(row.get('id') or '').strip()
                event_id = str(row.get('event_id') or '').strip()
                client_id = str(row.get('client_id') or '').strip()
                service = service_map.get(event_id)
                starts_at = parse_source_datetime(row.get('start_date'), source_tz)
                ends_at = parse_source_datetime(row.get('end_date'), source_tz)
                if not service or not starts_at or not booking_id:
                    summary['skipped_bookings'] += 1
                    continue
                if not ends_at or ends_at <= starts_at:
                    ends_at = starts_at + timedelta(minutes=max(5, safe_int(row.get('event_duration'), service.duration_minutes)))

                customer = customer_map.get(client_id)
                if not customer:
                    source_email = str(row.get('client_email') or '').strip().lower()
                    valid_email = '@' in source_email and len(source_email) <= 254
                    email = source_email if valid_email else f'simplybook-booking-{booking_id}@invalid.local'
                    customer = Customer.objects.filter(email__iexact=email).order_by('pk').first()
                    if not customer:
                        first_name, last_name = split_name(row.get('client'))
                        customer = Customer.objects.create(
                            first_name=first_name,
                            last_name=last_name,
                            phone=str(row.get('client_phone') or '')[:40],
                            email=email,
                        )
                        summary['customers_created'] += 1
                    customer_map[client_id or f'booking:{booking_id}'] = customer

                text_parts = []
                for value in (row.get('text'), row.get('comment')):
                    value = str(value or '').strip()
                    if value and value not in text_parts:
                        text_parts.append(value)
                notes = '\n\n'.join(text_parts)[:3000]
                defaults = {
                    'customer': customer,
                    'service': service,
                    'staff': archive_provider,
                    'starts_at': starts_at,
                    'ends_at': ends_at,
                    'status': 'confirmed' if as_bool(row.get('is_confirm')) else 'cancelled',
                    'source': 'admin',
                    'notes_customer': notes,
                    'returning_customer': client_booking_counts.get(client_id, 0) > 1,
                    'marketing_opt_in': False,
                    'cancellation_terms_accepted': False,
                    'privacy_accepted': False,
                }
                appointment, created = Appointment.objects.update_or_create(
                    idempotency_key=f'simplybook-{booking_id}',
                    defaults=defaults,
                )
                summary['appointments_created' if created else 'appointments_updated'] += 1
                record_date = parse_source_datetime(row.get('record_date'), source_tz)
                if record_date:
                    Appointment.objects.filter(pk=appointment.pk).update(created_at=record_date)

            # Import the dated source work calendar as overrides on the isolated archive provider.
            # This preserves historical/future working days without changing Ariane/Qamar public availability.
            for _month, month_data in raw_backup['work_calendars'].items():
                if not isinstance(month_data, dict) or '_unavailable' in month_data:
                    continue
                for day_string, info in month_data.items():
                    if not isinstance(info, dict):
                        continue
                    try:
                        day = date.fromisoformat(str(day_string))
                    except ValueError:
                        continue
                    closed = as_bool(info.get('is_day_off'))
                    start_time = parse_clock(info.get('from'))
                    end_time = parse_clock(info.get('to'))
                    if not closed and (not start_time or not end_time or end_time <= start_time):
                        closed = True
                    DailyAvailabilityOverride.objects.update_or_create(
                        staff=archive_provider,
                        date=day,
                        defaults={
                            'is_closed': closed,
                            'start_time_1': None if closed else start_time,
                            'end_time_1': None if closed else end_time,
                            'start_time_2': None,
                            'end_time_2': None,
                        },
                    )
                    summary['daily_schedules_written'] += 1

            if options.get('dry_run'):
                transaction.set_rollback(True)

        prefix = 'SIMPLYBOOK_DRY_RUN_JSON=' if options.get('dry_run') else 'SIMPLYBOOK_IMPORT_JSON='
        self.stdout.write(prefix + json.dumps(summary, sort_keys=True))
        if summary['skipped_bookings']:
            self.stdout.write(self.style.WARNING(f"Skipped bookings: {summary['skipped_bookings']}"))
        if options.get('dry_run'):
            self.stdout.write(self.style.SUCCESS('Dry run completed; all database writes rolled back.'))
        else:
            self.stdout.write(self.style.SUCCESS('SimplyBook import completed. No customer emails were sent.'))
