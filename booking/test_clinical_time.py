import json
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from .clinical_time import add_elapsed, parse_appointment_start, parse_clinic_wall_time
from .models import Appointment, Service, StaffMember, WorkingHour
from .services import available_slots
from .simplybook_outbound import _dt as simplybook_timestamp


class ClinicClockTests(SimpleTestCase):
    def test_winter_and_summer_wall_time_match_simplybook(self):
        for day, utc_hour in [('2026-12-30', 17), ('2026-07-01', 16)]:
            with self.subTest(day=day), timezone.override('Pacific/Honolulu'):
                expected = datetime.fromisoformat(f'{day}T{utc_hour:02}:30:00+00:00')
                self.assertEqual(parse_clinic_wall_time(day, '18:30'), expected)
                self.assertEqual(simplybook_timestamp(f'{day} 18:30:00'), expected)

    def test_nonexistent_and_repeated_wall_times_require_a_unique_instant(self):
        for day in ['2026-03-29', '2026-10-25']:
            with self.subTest(day=day):
                self.assertIsNone(parse_clinic_wall_time(day, '02:30'))
                self.assertIsNone(parse_appointment_start(f'{day}T02:30:00'))
                self.assertIsNone(simplybook_timestamp(f'{day} 02:30:00'))
        first = parse_appointment_start('2026-10-25T02:30:00+02:00')
        second = parse_appointment_start('2026-10-25T02:30:00+01:00')
        self.assertEqual(second - first, timedelta(hours=1))

    def test_reserved_minutes_use_elapsed_time_at_both_transitions(self):
        for day, clock, expected_hour in [
            ('2026-03-29', '01:45', 1),
            ('2026-10-25', '01:45', 0),
        ]:
            with self.subTest(day=day):
                start = parse_clinic_wall_time(day, clock)
                end = add_elapsed(start, timedelta(minutes=55))
                self.assertEqual(end.isoformat(), f'{day}T{expected_hour:02}:40:00+00:00')
                self.assertEqual(end - start, timedelta(minutes=55))


class BookingClinicClockTests(TestCase):
    def setUp(self):
        self.service = Service.objects.create(
            name='Synthetic consultation', slug='synthetic-clinic-clock',
            duration_minutes=45, buffer_minutes=10, active=True, bookable=True,
        )
        self.staff = StaffMember.objects.create(display_name='Synthetic provider', active=True)
        self.staff.services.add(self.service)
        self.admin = get_user_model().objects.create_user(
            username='clinic-clock-admin', is_staff=True, is_superuser=True,
        )

    def test_patient_slot_booking_and_both_admin_calendars_agree(self):
        for day, utc_hour in [('2026-12-30', 17), ('2026-07-01', 16)]:
            with self.subTest(day=day), timezone.override('America/Los_Angeles'):
                self.client.logout()
                parsed_day = date.fromisoformat(day)
                WorkingHour.objects.get_or_create(
                    staff=self.staff, weekday=parsed_day.weekday(),
                    start_time='18:30', end_time='19:30',
                )
                expected = datetime.fromisoformat(f'{day}T{utc_hour:02}:30:00+00:00')
                now = datetime.combine(parsed_day, datetime.min.time(), UTC) - timedelta(days=1)
                params = {'service_id': self.service.pk, 'staff_id': self.staff.pk}
                with patch('django.utils.timezone.now', return_value=now):
                    web = self.client.get(reverse('booking:availability'), {**params, 'date': day})
                    mobile = self.client.get(reverse('booking:mobile_slots'), {**params, 'day': day})
                    self.assertEqual(web.status_code, 200, web.json())
                    self.assertEqual(mobile.status_code, 200, mobile.json())
                    slot = web.json()['slots'][0]
                    self.assertEqual(slot['label'], '18:30')
                    self.assertEqual(datetime.fromisoformat(slot['starts_at']), expected)
                    self.assertEqual(mobile.json()['slots'], [slot['starts_at']])
                    booking = self.client.post(
                        reverse('booking:appointments'),
                        json.dumps({
                            **params, 'starts_at': f'{day}T18:30:00',
                            'first_name': 'Synthetic', 'last_name': 'Clock',
                            'email': f'clock-{day}@example.invalid', 'phone': '+49690000111',
                            'referral_source': 'Google',
                            'cancellation_terms_accepted': True, 'privacy_accepted': True,
                        }),
                        content_type='application/json',
                    )
                self.assertEqual(booking.status_code, 201, booking.json())
                item = Appointment.objects.get(public_id=booking.json()['appointment']['id'])
                self.assertEqual(item.starts_at, expected)
                self.assertEqual(item.ends_at - item.starts_at, timedelta(minutes=55))
                self.client.force_login(self.admin)
                with patch('booking.app_admin_api._verify_admin', return_value={'id': 1}):
                    native = self.client.get(
                        reverse('booking:app_admin_calendar'), {'date': day, 'staff': self.staff.pk},
                    )
                self.assertEqual(native.status_code, 200, native.json())
                session = self.client.session
                session['aplus_app_admin'] = True
                session.save()
                admin = self.client.get(
                    reverse('booking:admin_calendar_day'), {'date': day, 'staff': self.staff.pk},
                )
                self.assertEqual(admin.status_code, 200, admin.json())
                for response in (native, admin):
                    appointment = response.json()['appointments'][0]
                    self.assertEqual(appointment['start'], '18:30')
                    self.assertEqual(appointment['end'], '19:25')
                    self.assertEqual(appointment['treatment_end'], '19:15')

    def test_slot_grid_skips_nonexistent_and_repeated_wall_times(self):
        WorkingHour.objects.create(staff=self.staff, weekday=6, start_time='01:00', end_time='04:00')
        for day in (date(2026, 3, 29), date(2026, 10, 25)):
            now = datetime.combine(day, datetime.min.time(), UTC) - timedelta(days=1)
            with self.subTest(day=day), patch('django.utils.timezone.now', return_value=now):
                slots = available_slots(self.service, self.staff, day)
            labels = [slot.strftime('%H:%M') for slot in slots]
            self.assertEqual(labels, ['01:00', '01:15', '01:30', '01:45', '03:00'])
