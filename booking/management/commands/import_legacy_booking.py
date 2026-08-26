import sqlite3
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from booking.models import Appointment, BlockedPeriod, Customer, Service, StaffMember, WorkingHour


class Command(BaseCommand):
    help = 'Importiert die bestehende A+esthetic-Buchung einmalig aus der Customer-Club-SQLite-Datenbank.'

    def add_arguments(self, parser):
        parser.add_argument('--sqlite', required=True, help='Pfad zur bisherigen A+esthetic SQLite-Datenbank')

    @staticmethod
    def _aware(value):
        if not value:
            return None
        parsed = parse_datetime(str(value))
        if parsed and timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed

    @staticmethod
    def _table_exists(conn, name):
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (name,),
        ).fetchone()
        return bool(row)

    def handle(self, *args, **options):
        path = Path(options['sqlite'])
        if not path.is_file():
            raise CommandError(f'Legacy-Datenbank nicht gefunden: {path}')

        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        required = ['platform_app_service', 'platform_app_staffmember', 'platform_app_appointment', 'auth_user']
        missing = [name for name in required if not self._table_exists(conn, name)]
        if missing:
            raise CommandError(f'Legacy-Datenbank ist unvollständig: {", ".join(missing)}')

        service_map = {}
        staff_map = {}
        imported_service_slugs = set()
        imported_staff_names = set()

        services = conn.execute(
            '''SELECT id, name, slug, description, duration_minutes, buffer_minutes,
                      price_label, active, bookable_in_app, requires_medical_confirmation
               FROM platform_app_service ORDER BY id'''
        ).fetchall()
        for row in services:
            service, _ = Service.objects.update_or_create(
                slug=row['slug'],
                defaults={
                    'name': row['name'],
                    'description': row['description'] or '',
                    'duration_minutes': row['duration_minutes'] or 30,
                    'buffer_minutes': row['buffer_minutes'] or 0,
                    'price_label': row['price_label'] or '',
                    'active': bool(row['active']),
                    'bookable': bool(row['bookable_in_app']),
                    'requires_confirmation': bool(row['requires_medical_confirmation']),
                    'sort_order': int(row['id']) * 10,
                },
            )
            service_map[row['id']] = service
            imported_service_slugs.add(service.slug)

        staff_rows = conn.execute(
            'SELECT id, display_name, role, active FROM platform_app_staffmember ORDER BY id'
        ).fetchall()
        role_map = {'doctor': 'doctor', 'specialist': 'specialist', 'reception': 'team'}
        for row in staff_rows:
            staff = StaffMember.objects.filter(display_name=row['display_name']).order_by('pk').first()
            if not staff:
                staff = StaffMember(display_name=row['display_name'])
            staff.role = role_map.get(row['role'], 'specialist')
            staff.active = bool(row['active'])
            staff.sort_order = int(row['id']) * 10
            staff.save()
            staff_map[row['id']] = staff
            imported_staff_names.add(staff.display_name)

        assignments = {}
        if self._table_exists(conn, 'platform_app_staffmember_services'):
            for row in conn.execute(
                'SELECT staffmember_id, service_id FROM platform_app_staffmember_services'
            ).fetchall():
                assignments.setdefault(row['staffmember_id'], []).append(row['service_id'])
        for legacy_staff_id, staff in staff_map.items():
            mapped = [service_map[sid] for sid in assignments.get(legacy_staff_id, []) if sid in service_map]
            staff.services.set(mapped)

        if self._table_exists(conn, 'platform_app_workinghour'):
            for row in conn.execute(
                'SELECT staff_id, weekday, start_time, end_time, active FROM platform_app_workinghour'
            ).fetchall():
                staff = staff_map.get(row['staff_id'])
                if not staff:
                    continue
                WorkingHour.objects.update_or_create(
                    staff=staff,
                    weekday=row['weekday'],
                    start_time=row['start_time'],
                    defaults={'end_time': row['end_time'], 'active': bool(row['active'])},
                )

        if self._table_exists(conn, 'platform_app_blockedperiod'):
            for row in conn.execute(
                'SELECT staff_id, starts_at, ends_at, reason FROM platform_app_blockedperiod'
            ).fetchall():
                staff = staff_map.get(row['staff_id'])
                starts_at = self._aware(row['starts_at'])
                ends_at = self._aware(row['ends_at'])
                if not staff or not starts_at or not ends_at:
                    continue
                BlockedPeriod.objects.get_or_create(
                    staff=staff,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    defaults={'reason': row['reason'] or ''},
                )

        profile_join = ''
        phone_select = "'' AS phone"
        if self._table_exists(conn, 'platform_app_userprofile'):
            profile_join = 'LEFT JOIN platform_app_userprofile p ON p.user_id = a.user_id'
            phone_select = "COALESCE(p.phone, '') AS phone"

        appointment_rows = conn.execute(
            f'''SELECT a.id, a.user_id, a.service_id, a.staff_id, a.starts_at, a.ends_at,
                       a.status, a.source, a.notes_customer,
                       u.email, u.username, u.first_name, u.last_name, {phone_select}
                FROM platform_app_appointment a
                JOIN auth_user u ON u.id = a.user_id
                {profile_join}
                ORDER BY a.id'''
        ).fetchall()

        status_map = {
            'requested': 'new',
            'confirmed': 'confirmed',
            'completed': 'completed',
            'cancelled': 'cancelled',
            'no_show': 'no_show',
        }
        imported_appointments = 0
        skipped_appointments = 0
        for row in appointment_rows:
            service = service_map.get(row['service_id'])
            starts_at = self._aware(row['starts_at'])
            ends_at = self._aware(row['ends_at'])
            if not service or not starts_at or not ends_at:
                skipped_appointments += 1
                continue

            email = (row['email'] or '').strip().lower()
            if not email or '@' not in email:
                email = f"legacy-{row['user_id']}@invalid.local"
            first_name = (row['first_name'] or '').strip()
            last_name = (row['last_name'] or '').strip()
            username = (row['username'] or '').strip()
            if not first_name and not last_name:
                first_name = username or 'A+esthetic'
                last_name = 'Kunde'
            customer = Customer.objects.filter(email__iexact=email).order_by('pk').first()
            if not customer:
                customer = Customer(email=email)
            customer.first_name = (first_name or last_name or 'A+esthetic')[:80]
            customer.last_name = (last_name or first_name or 'Kunde')[:80]
            customer.phone = (row['phone'] or '')[:40]
            customer.save()

            staff = staff_map.get(row['staff_id']) if row['staff_id'] else None
            if not staff:
                staff = StaffMember.objects.filter(active=True, services=service).order_by('sort_order', 'pk').first()
            if not staff:
                staff, _ = StaffMember.objects.get_or_create(
                    display_name='A+esthetic Team',
                    defaults={'role': 'team', 'active': True, 'sort_order': 9999},
                )
                staff.services.add(service)

            source = 'app' if row['source'] == 'app' else ('admin' if row['source'] == 'admin' else 'admin')
            Appointment.objects.update_or_create(
                idempotency_key=f"legacy-aesthetic-{row['id']}",
                defaults={
                    'customer': customer,
                    'service': service,
                    'staff': staff,
                    'starts_at': starts_at,
                    'ends_at': ends_at,
                    'status': status_map.get(row['status'], 'new'),
                    'source': source,
                    'notes_customer': (row['notes_customer'] or '')[:3000],
                },
            )
            imported_appointments += 1

        if imported_service_slugs:
            Service.objects.exclude(slug__in=imported_service_slugs).filter(appointments__isnull=True).update(
                active=False,
                bookable=False,
            )
        if imported_staff_names:
            StaffMember.objects.exclude(display_name__in=imported_staff_names).filter(appointments__isnull=True).update(active=False)

        conn.close()
        self.stdout.write(self.style.SUCCESS(
            f'Legacy-Import abgeschlossen: {len(service_map)} Behandlungen, '
            f'{len(staff_map)} Mitarbeiter, {imported_appointments} Termine; '
            f'{skipped_appointments} Termine übersprungen.'
        ))
