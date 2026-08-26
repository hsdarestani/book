import json
from datetime import datetime, time, timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Appointment, BlockedPeriod, Customer, Service, StaffMember, WorkingHour
from .services import available_slots


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class BookingApiTests(TestCase):
    def setUp(self):
        self.service = Service.objects.create(
            name='Beratung', slug='beratung', duration_minutes=30, buffer_minutes=0,
            active=True, bookable=True,
        )
        self.staff = StaffMember.objects.create(display_name='A+esthetic Team', role='team', active=True)
        self.staff.services.add(self.service)
        for weekday in range(7):
            WorkingHour.objects.create(staff=self.staff, weekday=weekday, start_time=time(9), end_time=time(18))

    def future_slot(self, days=2, hour=10):
        day = timezone.localdate() + timedelta(days=days)
        tz = timezone.get_current_timezone()
        return timezone.make_aware(datetime.combine(day, time(hour, 0)), tz)

    def test_health(self):
        response = self.client.get('/api/health/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])

    def test_services_and_staff(self):
        services = self.client.get('/api/services/').json()['services']
        self.assertEqual(services[0]['name'], 'Beratung')
        staff = self.client.get(f'/api/staff/?service_id={self.service.pk}').json()['staff']
        self.assertEqual(staff[0]['name'], 'A+esthetic Team')

    def test_availability_excludes_blocked_period(self):
        slot = self.future_slot()
        BlockedPeriod.objects.create(staff=self.staff, starts_at=slot, ends_at=slot + timedelta(hours=1), reason='Fortbildung')
        slots = available_slots(self.service, self.staff, slot.date())
        self.assertNotIn(slot, slots)

    def test_create_appointment_and_prevent_overlap(self):
        slot = self.future_slot()
        payload = {
            'service_id': self.service.pk,
            'staff_id': self.staff.pk,
            'starts_at': slot.isoformat(),
            'first_name': 'Anna',
            'last_name': 'Muster',
            'email': 'anna@example.com',
            'phone': '015100000000',
            'message': 'Bitte kurz bestätigen.',
        }
        response = self.client.post('/api/appointments/', data=json.dumps(payload), content_type='application/json', HTTP_IDEMPOTENCY_KEY='abc-1')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Appointment.objects.count(), 1)
        repeat = self.client.post('/api/appointments/', data=json.dumps(payload), content_type='application/json', HTTP_IDEMPOTENCY_KEY='abc-1')
        self.assertEqual(repeat.status_code, 200)
        self.assertEqual(Appointment.objects.count(), 1)

        payload['email'] = 'other@example.com'
        overlap = self.client.post('/api/appointments/', data=json.dumps(payload), content_type='application/json', HTTP_IDEMPOTENCY_KEY='abc-2')
        self.assertEqual(overlap.status_code, 409)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_cancelled_appointment_releases_slot(self):
        slot = self.future_slot()
        customer = Customer.objects.create(first_name='A', last_name='B', email='a@b.de')
        Appointment.objects.create(
            customer=customer, service=self.service, staff=self.staff,
            starts_at=slot, ends_at=slot + timedelta(minutes=30), status='cancelled',
        )
        self.assertIn(slot, available_slots(self.service, self.staff, slot.date()))

    def test_past_and_far_dates_have_no_slots(self):
        self.assertEqual(available_slots(self.service, self.staff, timezone.localdate() - timedelta(days=1)), [])
        self.assertEqual(available_slots(self.service, self.staff, timezone.localdate() + timedelta(days=91)), [])
