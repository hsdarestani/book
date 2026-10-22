from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .models import Appointment, BlockedPeriod, Customer, Service, StaffMember, WorkingHour


TEST_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class FastCalendarDayApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='calendar-admin',
            password='secret-pass',
            is_staff=True,
        )
        self.service = Service.objects.create(
            name='Botox',
            slug='test-botox-fast-calendar',
            duration_minutes=30,
            buffer_minutes=0,
            active=True,
            bookable=True,
        )
        self.staff = StaffMember.objects.create(
            display_name='Frau Ariane Regaei',
            role='team',
            active=True,
        )
        self.staff.services.add(self.service)
        for weekday in range(7):
            WorkingHour.objects.create(
                staff=self.staff,
                weekday=weekday,
                start_time=time(9, 0),
                end_time=time(18, 0),
                active=True,
            )
        self.customer = Customer.objects.create(
            first_name='Anna',
            last_name='Muster',
            email='anna.fast@example.com',
            phone='015100000009',
        )
        self.day = timezone.localdate() + timedelta(days=2)
        tz = timezone.get_current_timezone()
        self.starts_at = timezone.make_aware(datetime.combine(self.day, time(10, 0)), tz)
        self.appointment = Appointment.objects.create(
            customer=self.customer,
            service=self.service,
            staff=self.staff,
            starts_at=self.starts_at,
            ends_at=self.starts_at + timedelta(minutes=30),
            status='confirmed',
        )
        self.block = BlockedPeriod.objects.create(
            staff=self.staff,
            starts_at=self.starts_at + timedelta(hours=2),
            ends_at=self.starts_at + timedelta(hours=3),
            reason='[NOTE][STAFF] Rückruf',
        )

    @override_settings(STORAGES=TEST_STORAGES)
    def test_admin_calendar_exposes_doctor_count_and_import_overlap_warning(self):
        # Imported appointments may overlap without being written through the
        # normal validated booking form. Both must stay discoverable by staff.
        import_dt = self.starts_at
        second_customer = Customer.objects.create(
            first_name='Lisa', last_name='Muster',
            email='lisa-import@example.invalid', phone='+49000000997')
        Appointment.objects.create(
            customer=second_customer, service=self.service, staff=self.staff,
            starts_at=import_dt, ends_at=import_dt + timedelta(minutes=30),
            status='confirmed', source='admin', idempotency_key='simplybook-test-overlap')
        second_staff = StaffMember.objects.create(
            display_name='Qamar Hameed', role='doctor', active=True)
        self.client.force_login(self.user)
        response = self.client.get('/verwaltung/', {
            'staff': self.staff.pk, 'date': self.day.isoformat(), 'cal_view': 'day'})
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('2 Termine', content)
        self.assertIn('0 Termine', content)
        self.assertIn('Überschneidende Termine', content)
        self.assertIn('Beide Buchungen bleiben sichtbar', content)
        api_response = self.client.get('/verwaltung/api/calendar-day/', {
            'staff': self.staff.pk, 'date': self.day.isoformat()})
        self.assertEqual(len(api_response.json()['appointments']), 2)
        self.assertTrue(StaffMember.objects.filter(pk=second_staff.pk).exists())

    def test_op_calendar_geometry_matches_fast_api_and_server_render(self):
        # Regression: fast navigation used an 08:00 origin while the initial
        # HTML and tick labels used 10:00, visually moving a 10:00 OP to 11:40.
        from .views import _calendar_position
        from .calendar_admin_api import _position

        op = BlockedPeriod.objects.create(
            staff=self.staff, starts_at=self.starts_at,
            ends_at=self.starts_at + timedelta(hours=10),
            reason='[BLOCKNOTE][STAFF] OP',
        )
        self.client.force_login(self.user)
        api = self.client.get('/verwaltung/api/calendar-day/', {
            'staff': self.staff.pk, 'date': self.day.isoformat(),
        }).json()
        operation = next(block for block in api['blocks'] if block['id'] == op.pk)
        self.assertEqual(operation['start'], '10:00')
        self.assertEqual(operation['end'], '20:00')
        self.assertAlmostEqual(operation['top'], 100 / 6, places=3)
        self.assertAlmostEqual(operation['height'], 500 / 6, places=3)
        self.assertEqual(
            _calendar_position(op.starts_at, op.ends_at),
            _position(op.starts_at, op.ends_at),
        )
        page = self.client.get('/verwaltung/kalender/', {
            'staff': self.staff.pk, 'date': self.day.isoformat(),
        })
        self.assertEqual(page.status_code, 200)
        html = page.content.decode('utf-8')
        self.assertIn('08:00', html)
        self.assertIn('20:00', html)
        self.assertIn(
            f'top:{operation["top"]}%;height:{operation["height"]}%;',
            html,
        )

    def test_calendar_day_api_requires_staff_login(self):
        response = self.client.get(
            '/verwaltung/api/calendar-day/',
            {'staff': self.staff.pk, 'date': self.day.isoformat()},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/verwaltung/login/', response.url)

    def test_calendar_day_api_returns_lightweight_day_payload(self):
        self.client.force_login(self.user)
        response = self.client.get(
            '/verwaltung/api/calendar-day/',
            {'staff': self.staff.pk, 'date': self.day.isoformat()},
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['date'], self.day.isoformat())
        self.assertEqual(payload['staff_id'], self.staff.pk)
        self.assertEqual(payload['appointments'][0]['id'], self.appointment.pk)
        self.assertEqual(payload['appointments'][0]['customer_name'], 'Anna Muster')
        self.assertEqual(payload['appointments'][0]['start'], '10:00')
        self.assertEqual(payload['blocks'][0]['id'], self.block.pk)
        self.assertEqual(payload['blocks'][0]['kind'], 'note')
        self.assertEqual(payload['blocks'][0]['text'], 'Rückruf')
        self.assertTrue(payload['ranges'])
        self.assertIn('no-store', response['Cache-Control'])


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    STORAGES=TEST_STORAGES,
)
class AdminLoginCsrfRecoveryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='login-admin',
            password='secret-pass',
            is_staff=True,
        )

    def test_login_page_is_never_cached(self):
        response = self.client.get('/verwaltung/login/')
        self.assertEqual(response.status_code, 200)
        cache_control = response.get('Cache-Control', '')
        self.assertIn('no-store', cache_control)
        self.assertIn('no-cache', cache_control)

    def test_stale_or_missing_csrf_login_recovers_with_fresh_form(self):
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(
            '/verwaltung/login/',
            {'username': 'login-admin', 'password': 'secret-pass'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/verwaltung/login/?csrf=refresh'))

    def test_normal_login_redirects_directly_to_dashboard(self):
        response = self.client.get('/verwaltung/login/')
        token = response.cookies['csrftoken'].value
        response = self.client.post(
            '/verwaltung/login/',
            {
                'username': 'login-admin',
                'password': 'secret-pass',
                'csrfmiddlewaretoken': token,
            },
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/verwaltung/dashboard/')
