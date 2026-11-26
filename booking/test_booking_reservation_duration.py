import json
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .clinical_time import parse_clinic_wall_time
from .models import Appointment, BlockedPeriod, Customer, Service, StaffMember, WorkingHour


class HistoricalReservationTests(TestCase):
    def setUp(self):
        self.service = Service.objects.create(
            name='Synthetic treatment', slug='synthetic-duration',
            duration_minutes=25, buffer_minutes=5, active=True, bookable=True,
        )
        self.staff = StaffMember.objects.create(display_name='Synthetic provider', active=True)
        self.staff.services.add(self.service)
        self.customer = Customer.objects.create(
            first_name='Synthetic', last_name='Patient',
            email='reserved-time@example.invalid', phone='+49690000123',
        )
        start = parse_clinic_wall_time('2026-12-29', '18:30')
        self.item = Appointment.objects.create(
            customer=self.customer, service=self.service, staff=self.staff,
            starts_at=start, ends_at=start + timedelta(minutes=55),
            treatment_minutes_at_booking=45, status='confirmed', source='app',
        )
        self.day = date(2026, 12, 30)
        WorkingHour.objects.create(
            staff=self.staff, weekday=self.day.weekday(), start_time='18:30', end_time='19:30',
        )

    def test_native_status_edit_keeps_existing_treatment_and_reserved_span(self):
        target = reverse('booking:app_admin_appointment_action', args=[self.item.pk])
        with patch('booking.app_admin_api._verify_admin', return_value={'id': 1}), \
             patch('booking.app_admin_api.notify_admin_changed'):
            response = self.client.post(target, json.dumps({'status': 'completed'}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.json())
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, 'completed')
        self.assertEqual(self.item.reserved_duration, timedelta(minutes=55))
        payload = response.json()['appointment']
        self.assertEqual(payload['buffer_minutes'], 10)
        self.assertEqual(payload['treatment_end'], '19:15')
        self.assertEqual(payload['end'], '19:25')

    def test_native_rescheduling_checks_blocks_in_the_full_reserved_span(self):
        target_day = self.day.isoformat()
        BlockedPeriod.objects.create(
            staff=self.staff, starts_at=parse_clinic_wall_time(target_day, '19:15'),
            ends_at=parse_clinic_wall_time(target_day, '19:30'), reason='Synthetic closure',
        )
        url = reverse('booking:app_admin_appointment_action', args=[self.item.pk])
        with patch('booking.app_admin_api._verify_admin', return_value={'id': 1}):
            response = self.client.post(url, data=json.dumps({
                'date': target_day, 'time': '18:30',
            }), content_type='application/json')
        self.assertEqual(response.status_code, 409, response.json())
        self.item.refresh_from_db()
        self.assertEqual(self.item.starts_at, parse_clinic_wall_time('2026-12-29', '18:30'))

    def test_web_admin_rescheduling_keeps_snapshot_and_reserved_span(self):
        admin = get_user_model().objects.create_user(
            username='duration-admin', is_staff=True, is_superuser=True,
        )
        self.client.force_login(admin)
        session = self.client.session
        session['aplus_app_admin'] = True
        session.save()
        with patch('booking.admin_views.notify_admin_changed'):
            response = self.client.post(reverse('booking:admin_calendar'), {
                'action': 'edit_appointment', 'appointment_id': self.item.pk,
                'appointment_date': self.day.isoformat(), 'appointment_time': '18:30',
                'appointment_staff_id': self.staff.pk, 'service_id': self.service.pk,
                'customer_id': self.customer.pk, 'status': 'confirmed',
            })
        self.assertEqual(response.status_code, 302)
        self.assertIn('appointment-updated', response.url)
        self.item.refresh_from_db()
        self.assertEqual(self.item.starts_at, parse_clinic_wall_time(self.day.isoformat(), '18:30'))
        self.assertEqual(self.item.reserved_duration, timedelta(minutes=55))
        self.assertEqual(self.item.treatment_minutes_at_booking, 45)

    def test_reschedule_picker_and_write_use_the_existing_legacy_span(self):
        self.item.treatment_minutes_at_booking = None
        self.item.save(update_fields=['treatment_minutes_at_booking'])
        target_day = self.day.isoformat()
        member = {
            'email': self.customer.email, 'phone': self.customer.phone,
            'first_name': self.customer.first_name, 'last_name': self.customer.last_name,
        }
        params = {
            'service_id': self.service.pk, 'staff_id': self.staff.pk, 'day': target_day,
            'exclude_appointment_id': str(self.item.public_id),
        }
        with patch('django.utils.timezone.now', return_value=datetime(2026, 12, 27, tzinfo=UTC)), \
             patch('booking.mobile_api._member', return_value=(member, None)), \
             patch('booking.mobile_api.notify_customer_rescheduled'):
            slots = self.client.get(reverse('booking:mobile_slots'), params)
            self.assertEqual(slots.status_code, 200, slots.json())
            self.assertEqual(slots.json()['slots'], [f'{target_day}T18:30:00+01:00'])
            url = reverse('booking:mobile_appointment_change', args=[self.item.public_id])
            result = self.client.post(url, data=json.dumps({
                'action': 'reschedule', 'staff_id': self.staff.pk,
                'starts_at': slots.json()['slots'][0],
            }), content_type='application/json')
        self.assertEqual(result.status_code, 200, result.json())
        self.item.refresh_from_db()
        self.assertEqual(self.item.starts_at, parse_clinic_wall_time(target_day, '18:30'))
        self.assertEqual(self.item.reserved_duration, timedelta(minutes=55))
        self.assertIsNone(self.item.treatment_minutes_at_booking)
        self.assertEqual(self.item.calendar_buffer_minutes, 0)

    def test_reschedule_picker_requires_appointment_owner(self):
        other = {
            'email': 'another@example.invalid', 'phone': '+49690000124',
            'first_name': 'Another', 'last_name': 'Synthetic',
        }
        with patch('django.utils.timezone.now', return_value=datetime(2026, 12, 27, tzinfo=UTC)), \
             patch('booking.mobile_api._member', return_value=(other, None)):
            response = self.client.get(reverse('booking:mobile_slots'), {
                'service_id': self.service.pk, 'day': self.day.isoformat(),
                'exclude_appointment_id': str(self.item.public_id),
            })
        self.assertEqual(response.status_code, 404, response.json())
