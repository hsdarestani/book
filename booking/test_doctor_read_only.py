from datetime import datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from .models import (AdminAccessProfile, Appointment, Customer, DailyAvailabilityOverride,
                     Service, StaffMember, WorkingHour)


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

    def test_only_own_day_and_month_appointments_are_visible(self):
        response = self.client.get('/verwaltung/arzt/', {'date': self.day.isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Meine Patientin')
        self.assertNotContains(response, 'Fremde Patientin')
        self.assertContains(response, 'Wochenzeiten speichern')

    def test_other_admin_surfaces_and_write_apis_are_rejected(self):
        for url in ['/verwaltung/dashboard/', '/verwaltung/kalender/', '/verwaltung/kunden/',
                    '/verwaltung/mehr/', '/verwaltung/patienten/1/', '/verwaltung/api/day-availability/',
                    '/verwaltung/api/calendar-day/', '/admin/']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post('/verwaltung/dashboard/', {'action': 'save'}).status_code, 403)

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
        self.assertEqual(user.aesthetic_access.staff_id, self.doctor.pk)
