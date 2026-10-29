from datetime import datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from .models import (AdminAccessProfile, Appointment, Customer, DailyAvailabilityOverride,
                     DoctorPatientAccess, PatientRecord, Service, StaffMember, WorkingHour)


class DoctorPrivateCalendarTests(TestCase):
    def setUp(self):
        self.doctor = StaffMember.objects.create(display_name='Qamar Hameed', role='doctor')
        self.other = StaffMember.objects.create(display_name='Andere Ärztin', role='doctor')
        self.service = Service.objects.create(name='Beratung Arzt', slug='beratungsarzt')
        self.doctor.services.add(self.service)
        self.other.services.add(self.service)
        mine = Customer.objects.create(first_name='Meine', last_name='Patientin', email='mine@example.test')
        other = Customer.objects.create(first_name='Fremde', last_name='Patientin', email='other@example.test')
        self.day = timezone.localdate() + timedelta(days=2)
        start = timezone.make_aware(datetime.combine(self.day, time(10, 0)),
                                    timezone.get_current_timezone())
        self.mine = Appointment.objects.create(
            staff=self.doctor, customer=mine, service=self.service,
            starts_at=start, ends_at=start + timedelta(minutes=30))
        self.theirs = Appointment.objects.create(
            staff=self.other, customer=other, service=self.service,
            starts_at=start, ends_at=start + timedelta(minutes=30))
        for staff in (self.doctor, self.other):
            WorkingHour.objects.create(
                staff=staff, weekday=self.day.weekday(),
                start_time=time(9, 0), end_time=time(17, 0), active=True)
        self.user = User.objects.create_user(username='doctor-qamar', password='test-secret',
                                             is_staff=True)
        AdminAccessProfile.objects.create(user=self.user, staff=self.doctor, view_only=True)
        self.client.force_login(self.user)

    def post_calendar(self, **values):
        return self.client.post('/verwaltung/arzt/', {'date': self.day.isoformat(), **values})

    def test_qamar_uses_latest_shared_iphone_calendar_in_day_and_week_modes(self):
        from pathlib import Path
        base = Path(__file__).resolve().parent.parent / 'static' / 'booking'
        loader = (base / 'admin.js').read_text(encoding='utf-8')
        iphone = (base / 'admin-calendar-iphone-v1.js').read_text(encoding='utf-8')
        for asset in ('admin-calendar-iphone-v1.css',
                      'admin-calendar-reference-v2.css',
                      'admin-calendar-sheet-fix-v3.css',
                      'admin-calendar-mobile-finish-v4.css'):
            self.assertIn(asset, loader)
        self.assertIn("document.querySelector('.sb-calendar-panel')", loader)
        self.assertIn("document.body.dataset.doctorCalendar==='1'", iphone)

        for mode in ('day', 'week'):
            with self.subTest(mode=mode):
                response = self.client.get('/verwaltung/arzt/', {
                    'date': self.day.isoformat(),
                    'section': 'calendar',
                    'cal_view': mode,
                    # A doctor may supply a foreign staff query but must
                    # never change the server-selected clinician scope.
                    'staff': str(self.other.pk),
                })
                self.assertEqual(response.status_code, 200)
                for marker in (
                    'sb-reference-calendar-bar',
                    'sb-reference-mode-button',
                    'data-iphone-date-open',
                    'data-iphone-filter-open',
                    'data-doctor-calendar="1"',
                    'data-fab-actions',
                    'data-open-note',
                    'data-open-block',
                    'admin.js?v=20261029-sheet-v3',
                ):
                    self.assertContains(response, marker)
                self.assertContains(response, 'Meine Patientin')
                self.assertNotContains(response, 'Fremde Patientin')
                self.assertNotContains(response, 'Andere Ärztin')
                self.assertContains(response, 'data-doctor-staff-id="' + str(self.doctor.pk) + '"')

    def test_qamar_fast_swipe_api_remains_scoped_to_own_appointments(self):
        from urllib.parse import urlencode
        day = self.day.isoformat()
        for member, code in ((self.doctor, 200), (self.other, 403)):
            with self.subTest(staff=member.pk):
                response = self.client.get('/verwaltung/api/calendar-day/?' + urlencode({
                    'date': day, 'staff': member.pk,
                }))
                self.assertEqual(response.status_code, code)
                if code == 200:
                    payload = response.json()
                    self.assertEqual(payload['staff_id'], self.doctor.pk)
                    self.assertTrue(all(
                        item['staff_id'] == self.doctor.pk
                        for item in payload['appointments']
                    ))
                    self.assertNotIn('Fremde Patientin', response.content.decode('utf-8'))

    def test_only_own_day_and_month_appointments_are_visible(self):
        response = self.client.get('/verwaltung/arzt/', {'date': self.day.isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Meine Patientin')
        self.assertNotContains(response, 'Fremde Patientin')
        self.assertContains(response, 'Wochenplan')
        self.assertContains(response, 'sb-calendar-shell')
        self.assertContains(response, 'sb-provider-switcher')
        self.assertContains(response, 'admin-ferrari-v17.js')
        self.assertContains(response, 'booking/admin.js')
        self.assertContains(response, 'data-doctor-role="1"')
        self.assertContains(response, 'Buchungsübersicht')
        self.assertContains(response, '/verwaltung/patienten/')
        self.assertNotContains(response, 'Fremde Patientin')
        self.assertNotContains(response, 'Andere Ärztin')

    def test_calendar_content_is_not_hidden_until_admin_javascript_runs(self):
        from pathlib import Path
        css = (Path(__file__).resolve().parent.parent /
               'static/booking/admin-fixes.css').read_text(encoding='utf-8')
        self.assertIn('body.sb-admin-body:not([data-doctor-calendar="1"]):not(:has(.sb-page-hidden))', css)
        result = self.client.get('/verwaltung/arzt/', {'date': self.day.isoformat()})
        self.assertEqual(result.status_code, 200)
        self.assertContains(result, 'data-doctor-calendar="1"')
        self.assertContains(result, 'booking/admin.js')
        self.assertContains(result, 'data-doctor-role="1"')
        self.assertContains(result, 'Meine Patientin')

    def test_other_admin_surfaces_and_write_apis_are_rejected(self):
        for url in ['/verwaltung/dashboard/', '/verwaltung/kalender/', '/verwaltung/kunden/',
                    '/verwaltung/mehr/', '/admin/']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post('/verwaltung/dashboard/', {'action': 'save'}).status_code, 403)

    def test_actual_admin_shell_renders_every_doctor_section_without_other_data(self):
        for section, heading in [('dashboard', 'Buchungsübersicht'), ('calendar', 'Tagesansicht'),
                                 ('bookings', 'Kommende Termine'), ('customers', 'Kunden'),
                                 ('settings', 'Verfügbarkeit')]:
            with self.subTest(section=section):
                response = self.client.get('/verwaltung/arzt/',
                                           {'date': self.day.isoformat(), 'section': section})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, heading)
                self.assertContains(response, 'admin.js')
                self.assertNotContains(response, 'Fremde Patientin')
                self.assertNotContains(response, 'Andere Ärztin')

    def test_scope_patient_record_pages_and_patient_files(self):
        own_customer = self.mine.customer
        other_customer = self.theirs.customer
        own_doc = PatientRecord.objects.create(customer=own_customer, appointment=self.mine,
                                               title='Only Qamar')
        hidden_doc = PatientRecord.objects.create(customer=own_customer,
                                                  title='Clinic confidential')
        other_doc = PatientRecord.objects.create(customer=other_customer, appointment=self.theirs,
                                                 title='Other doctor doc')
        response = self.client.get(f'/verwaltung/patienten/{own_customer.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Only Qamar')
        self.assertNotContains(response, 'Clinic confidential')
        self.assertEqual(self.client.get(f'/verwaltung/patienten/{other_customer.pk}/').status_code, 404)
        self.assertEqual(self.client.get(
            f'/verwaltung/patienten/{own_customer.pk}/datei/{hidden_doc.public_id}/').status_code, 404)
        self.assertEqual(self.client.get(
            f'/verwaltung/patienten/{other_customer.pk}/datei/{other_doc.public_id}/').status_code, 404)
        response = self.client.post(f'/verwaltung/patienten/{own_customer.pk}/',
                                    {'action': 'delete_record', 'record_id': hidden_doc.pk})
        self.assertEqual(response.status_code, 404)
        self.assertTrue(PatientRecord.objects.filter(pk=hidden_doc.pk).exists())
        self.assertTrue(PatientRecord.objects.filter(pk=own_doc.pk).exists())

    def test_new_patient_creation_is_scoped_and_bookable(self):
        response = self.post_calendar(action='add_customer', first_name='Neue',
                                      last_name='Kunde', email='newpatient@example.test')
        self.assertIn('notice=saved', response.url)
        new_patient = Customer.objects.get(email='newpatient@example.test')
        self.assertTrue(DoctorPatientAccess.objects.filter(staff=self.doctor, customer=new_patient).exists())
        panel = self.client.get('/verwaltung/arzt/', {'date': self.day.isoformat(), 'section': 'customers'})
        self.assertContains(panel, 'Neue Kunde')
        response = self.post_calendar(action='add_appointment',
                                      customer_id=new_patient.pk,
                                      appointment_staff_id=self.other.pk,
                                      service_id=self.service.pk, appointment_date=self.day.isoformat(),
                                      appointment_time='11:00')
        self.assertIn('notice=saved', response.url)
        self.assertTrue(Appointment.objects.filter(staff=self.doctor, customer=new_patient).exists())
        self.assertFalse(Appointment.objects.filter(staff=self.other, customer=new_patient).exists())

    def test_shared_patient_identity_cannot_be_modified_by_doctor(self):
        shared = self.mine.customer
        Appointment.objects.create(staff=self.other, customer=shared, service=self.service,
                                   starts_at=self.theirs.starts_at + timedelta(days=7),
                                   ends_at=self.theirs.ends_at + timedelta(days=7))
        before = shared.first_name
        response = self.post_calendar(action='add_customer', first_name='Verändert',
                                      last_name=shared.last_name, email=shared.email)
        self.assertIn('notice=error', response.url)
        shared.refresh_from_db()
        self.assertEqual(shared.first_name, before)

    def test_main_admin_edit_modal_rejects_other_staff_patient_and_booking(self):
        item = self.mine
        original = item.starts_at
        self.post_calendar(action='edit_appointment', appointment_id=item.pk,
                           appointment_staff_id=self.other.pk, customer_id=item.customer.pk,
                           service_id=self.service.pk, appointment_date=self.day.isoformat(),
                           appointment_time='12:00', status='confirmed')
        item.refresh_from_db()
        self.assertEqual(item.starts_at, original)
        bad = self.post_calendar(action='edit_appointment', appointment_id=self.theirs.pk,
                                  appointment_staff_id=self.doctor.pk, customer_id=item.customer.pk,
                                  service_id=self.service.pk, appointment_date=self.day.isoformat(),
                                  appointment_time='12:00', status='confirmed')
        self.assertIn('notice=error', bad.url)
        self.theirs.refresh_from_db()
        self.assertEqual(self.theirs.status, 'new')
        self.post_calendar(action='delete_appointment', appointment_id=self.theirs.pk)
        self.assertTrue(Appointment.objects.filter(pk=self.theirs.pk).exists())

    def test_own_patient_file_upload_and_unauthorized_attachment_rejected(self):
        url = f'/verwaltung/patienten/{self.mine.customer.pk}/'
        response = self.client.post(url, {'action': 'add_record', 'kind': 'note',
                                          'title': 'Eigene Notiz', 'note': 'Nur für Dr Qamar'})
        self.assertEqual(response.status_code, 302)
        record = PatientRecord.objects.get(title='Eigene Notiz')
        self.assertEqual(record.uploaded_by, self.user)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertContains(self.client.get(url), 'Eigene Notiz')
        response = self.client.post(url, {'action': 'add_record', 'kind': 'note',
                                          'note': 'Other linked appointment',
                                          'appointment_id': self.theirs.pk})
        self.assertEqual(response.status_code, 404)

    def test_doctor_navigation_shows_only_working_role_links(self):
        from pathlib import Path
        html = self.client.get('/verwaltung/arzt/', {
            'section': 'calendar', 'date': self.day.isoformat(),
        })
        self.assertEqual(html.status_code, 200)
        self.assertContains(html, 'data-doctor-role="1"')
        self.assertContains(html, 'admin-unified-nav-v14.js?v=20261020-doctor-menu')
        for section in ('dashboard', 'calendar', 'bookings', 'customers', 'settings'):
            self.assertContains(html, f'/verwaltung/arzt/?section={section}')
            landing = self.client.get('/verwaltung/arzt/', {'section': section})
            self.assertEqual(landing.status_code, 200)
            self.assertNotContains(landing, 'Fremde Patientin')
        for forbidden in ('/verwaltung/app/wallet/', '/verwaltung/app/reviews/',
                          '/verwaltung/app/referrals/', '/verwaltung/app/invoices/',
                          '/verwaltung/app/hero/', '/verwaltung/mehr/'):
            self.assertNotContains(html, f'href="{forbidden}"')
        script = (Path(__file__).resolve().parent.parent /
                  'static/booking/admin-unified-nav-v14.js').read_text(encoding='utf-8')
        self.assertIn('const items = doctorRole ? doctorItems', script)
        self.assertIn("'Meine Buchungen', '/verwaltung/arzt/?section=bookings'", script)
        self.assertIn("'Arbeitszeiten', '/verwaltung/arzt/?section=settings'", script)

    def test_final_menu_guard_survives_late_legacy_rewrites(self):
        from pathlib import Path
        response = self.client.get('/verwaltung/arzt/', {'section': 'calendar'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-aplus-doctor-nav-finalizer')
        self.assertContains(response, 'MutationObserver(schedule)')
        self.assertContains(response, 'MEINE VERWALTUNG')
        self.assertContains(response, '20261020-doctor-role-v2')
        self.assertEqual(response['Cache-Control'].find('no-store') >= 0, True)
        for section in ('dashboard', 'calendar', 'bookings', 'customers', 'settings'):
            self.assertContains(response, '/verwaltung/arzt/?section=' + section)
        root = Path(__file__).resolve().parent.parent
        for script in ('admin-luxury-v2.js', 'admin-unified-nav-v13.js'):
            contents = (root / 'static' / 'booking' / script).read_text(encoding='utf-8')
            self.assertIn("document.documentElement.dataset.doctorRole === '1'", contents)

    def test_final_menu_guard_on_doctor_owned_patient_file(self):
        response = self.client.get('/verwaltung/patienten/' + str(self.mine.customer.pk) + '/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-aplus-doctor-nav-finalizer')
        self.assertContains(response, '/verwaltung/arzt/?section=customers')
        self.assertNotContains(response, 'href="/verwaltung/app/wallet/"')

    def test_doctor_patient_record_menu_uses_scoped_navigation(self):
        response = self.client.get(f'/verwaltung/patienten/{self.mine.customer.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-doctor-role="1"')
        self.assertContains(response, '/verwaltung/arzt/?section=customers')
        self.assertContains(response, 'admin-unified-nav-v14.js?v=20261020-doctor-menu')
        self.assertNotContains(response, 'href="/verwaltung/app/wallet/"')
        self.assertNotContains(response, 'href="/verwaltung/dashboard/"')

    def test_booking_status_save_returns_to_booking_tab(self):
        url = '/verwaltung/arzt/?section=bookings&date=' + self.day.isoformat()
        response = self.client.post(url, {
            'action': 'appointment_status', 'appointment_id': self.mine.pk,
            'status': 'confirmed',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('section=bookings', response.url)
        self.assertIn('notice=saved', response.url)

    def test_native_admin_calendar_api_is_scoped_to_own_staff(self):
        path = '/verwaltung/api/calendar-day/'
        own = self.client.get(path, {'staff': self.doctor.pk, 'date': self.day.isoformat()})
        self.assertEqual(own.status_code, 200, own.content)
        self.assertIn('Meine Patientin', str(own.json()))
        self.assertNotIn('Fremde Patientin', str(own.json()))
        other = self.client.get(path, {'staff': self.other.pk, 'date': self.day.isoformat()})
        self.assertEqual(other.status_code, 403)
        other_hours = self.client.get('/verwaltung/api/day-availability/',
                                      {'staff': self.other.pk, 'date': self.day.isoformat()})
        self.assertEqual(other_hours.status_code, 403)
        own_close = self.client.post('/verwaltung/api/day-availability/',
                                     {'staff_id': self.doctor.pk, 'date': self.day.isoformat(),
                                      'closed': 'on'})
        self.assertEqual(own_close.status_code, 302)
        self.assertIn('/verwaltung/arzt/', own_close.url)
        other_close = self.client.post('/verwaltung/api/day-availability/',
                                       {'staff_id': self.other.pk, 'date': self.day.isoformat(),
                                        'closed': 'on'})
        self.assertEqual(other_close.status_code, 403)
        self.assertFalse(DailyAvailabilityOverride.objects.filter(staff=self.other).exists())

    def test_daily_open_close_reset_only_changes_own_availability(self):
        result = self.post_calendar(action='save', closed='on', staff_id=str(self.other.pk))
        self.assertEqual(result.status_code, 302)
        value = DailyAvailabilityOverride.objects.get(staff=self.doctor, date=self.day)
        self.assertTrue(value.closed)
        self.assertFalse(DailyAvailabilityOverride.objects.filter(staff=self.other).exists())
        self.assertTrue(Appointment.objects.filter(pk=self.mine.pk).exists())

        result = self.post_calendar(action='save', start_1='11:00', end_1='15:00')
        self.assertEqual(result.status_code, 302)
        value.refresh_from_db()
        self.assertFalse(value.closed)
        self.assertEqual(value.start_time_1, time(11))
        self.assertEqual(value.end_time_1, time(15))
        self.post_calendar(action='reset')
        self.assertFalse(DailyAvailabilityOverride.objects.filter(staff=self.doctor).exists())

    def test_weekly_schedule_edits_only_own_staff(self):
        result = self.post_calendar(action='weekly', start_1='08:00', end_1='12:00',
                                    start_2='13:00', end_2='16:00', staff_id=str(self.other.pk))
        self.assertEqual(result.status_code, 302)
        own = list(WorkingHour.objects.filter(staff=self.doctor, weekday=self.day.weekday()))
        self.assertEqual(len(own), 2)
        self.assertEqual(own[0].start_time, time(8))
        self.assertEqual(own[1].start_time, time(13))
        self.assertEqual(WorkingHour.objects.get(staff=self.other).start_time, time(9))
        self.post_calendar(action='weekly', closed='on')
        self.assertFalse(WorkingHour.objects.filter(staff=self.doctor, weekday=self.day.weekday()).exists())
        self.assertTrue(WorkingHour.objects.filter(staff=self.other).exists())

    def test_only_own_appointments_can_change_status_or_move(self):
        response = self.post_calendar(action='status', appointment_id=self.theirs.pk, status='cancelled')
        self.assertIn('notice=error', response.url)
        self.theirs.refresh_from_db()
        self.assertEqual(self.theirs.status, 'new')
        response = self.post_calendar(action='move', appointment_id=self.theirs.pk,
                                      new_date=self.day.isoformat(), new_time='13:00')
        self.assertIn('notice=error', response.url)
        self.post_calendar(action='status', appointment_id=self.mine.pk, status='confirmed')
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.status, 'confirmed')
        self.post_calendar(action='move', appointment_id=self.mine.pk,
                           new_date=self.day.isoformat(), new_time='13:00')
        self.mine.refresh_from_db()
        self.assertEqual(timezone.localtime(self.mine.starts_at).time(), time(13))
        self.assertEqual(timezone.localtime(self.theirs.starts_at).time(), time(10))

    def test_weekly_admin_form_changes_only_own_schedule(self):
        form = {'date': self.day.isoformat(), 'action': 'save_hours',
                'day_0_enabled': 'on', 'day_0_start_1': '08:00', 'day_0_end_1': '12:00',
                'day_0_start_2': '', 'day_0_end_2': ''}
        response = self.client.post('/verwaltung/arzt/', form)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(WorkingHour.objects.filter(staff=self.doctor).count(), 1)
        self.assertEqual(WorkingHour.objects.filter(staff=self.other).count(), 1)
        self.assertEqual(WorkingHour.objects.get(staff=self.doctor).start_time, time(8))

    def test_admin_weekly_form_allows_saving_unchanged_existing_hours(self):
        form = {'date': self.day.isoformat(), 'action': 'save_hours',
                'day_%s_enabled' % self.day.weekday(): 'on',
                'day_%s_start_1' % self.day.weekday(): '09:00',
                'day_%s_end_1' % self.day.weekday(): '17:00'}
        response = self.client.post('/verwaltung/arzt/', form)
        self.assertIn('notice=saved', response.url)
        self.assertEqual(WorkingHour.objects.get(staff=self.doctor).start_time, time(9))

    def test_delete_calendar_block_cannot_affect_another_doctor(self):
        from .models import BlockedPeriod
        start = self.mine.starts_at + timedelta(hours=3)
        other_block = BlockedPeriod.objects.create(
            staff=self.other, starts_at=start, ends_at=start + timedelta(minutes=30))
        own_block = BlockedPeriod.objects.create(
            staff=self.doctor, starts_at=start, ends_at=start + timedelta(minutes=30))
        response = self.post_calendar(action='delete_block', block_id=other_block.pk,
                                      staff_id=str(self.other.pk))
        self.assertIn('notice=error', response.url)
        self.assertTrue(BlockedPeriod.objects.filter(pk=other_block.pk).exists())
        self.post_calendar(action='delete_block', block_id=own_block.pk)
        self.assertFalse(BlockedPeriod.objects.filter(pk=own_block.pk).exists())

    def test_invalid_weekly_times_preserve_existing_schedule(self):
        self.post_calendar(action='weekly', start_1='16:00', end_1='09:00')
        self.assertEqual(WorkingHour.objects.get(staff=self.doctor).start_time, time(9))

    def test_csrf_is_required_for_calendar_writes(self):
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.user)
        response = secure.post('/verwaltung/arzt/',
                               {'date': self.day.isoformat(), 'action': 'save', 'closed': 'on'})
        self.assertEqual(response.status_code, 403)

    @patch('booking.auth_views._verify_doctor')
    @patch('booking.app_admin_api._verify_admin', return_value=None)
    def test_doctor_sso_uses_scoped_session(self, _admin, verify_doctor):
        verify_doctor.return_value = {'id': 908, 'name': 'Qamar Hameed', 'email': ''}
        self.client.logout()
        response = self.client.post('/verwaltung/app-sso/',
            HTTP_AUTHORIZATION='Bearer a-verified-doctor-token-that-is-long')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['redirect'], '/verwaltung/arzt/')
        user = User.objects.get(username='aplus_app_admin_908')
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.aesthetic_access.view_only)
        self.assertEqual(user.aesthetic_access.staff.display_name, 'Qamar Hameed')
