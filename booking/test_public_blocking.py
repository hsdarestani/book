import json
from datetime import datetime, time, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Appointment, BlockedPeriod, Service, StaffMember, WorkingHour


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class PublicBlockedPeriodTests(TestCase):
    def setUp(self):
        self.service = Service.objects.create(
            name='Public Blocking Test',
            slug='public-blocking-test',
            duration_minutes=30,
            buffer_minutes=0,
            price_label='',
            active=True,
            bookable=True,
            requires_confirmation=False,
            sort_order=1,
        )
        self.staff = StaffMember.objects.create(
            display_name='Frau Public Test',
            role='doctor',
            active=True,
            sort_order=1,
        )
        self.staff.services.add(self.service)
        self.day = timezone.localdate() + timedelta(days=2)
        WorkingHour.objects.create(
            staff=self.staff,
            weekday=self.day.weekday(),
            start_time=time(9, 0),
            end_time=time(13, 0),
            active=True,
        )

    def _local_dt(self, hour, minute=0):
        return timezone.make_aware(
            datetime.combine(self.day, time(hour, minute)),
            timezone.get_current_timezone(),
        )

    def _availability(self):
        return self.client.get(
            reverse('booking:availability'),
            {
                'service_id': self.service.pk,
                'staff_id': self.staff.pk,
                'date': self.day.isoformat(),
            },
        )

    def test_admin_block_disappears_from_public_book_slots(self):
        before = self._availability()
        self.assertEqual(before.status_code, 200)
        before_labels = {item['label'] for item in before.json()['slots']}
        self.assertIn('10:00', before_labels)
        self.assertIn('10:15', before_labels)

        BlockedPeriod.objects.create(
            staff=self.staff,
            starts_at=self._local_dt(10, 0),
            ends_at=self._local_dt(11, 0),
            reason='[BLOCKNOTE][STAFF] Pause',
        )

        after = self._availability()
        self.assertEqual(after.status_code, 200)
        after_labels = {item['label'] for item in after.json()['slots']}
        self.assertNotIn('10:00', after_labels)
        self.assertNotIn('10:15', after_labels)
        self.assertIn('11:00', after_labels)

        overview = self.client.get(
            reverse('booking:availability_overview'),
            {'service_id': self.service.pk, 'staff_id': self.staff.pk, 'days': 7},
        )
        self.assertEqual(overview.status_code, 200)
        matching_day = next(item for item in overview.json()['days'] if item['date'] == self.day.isoformat())
        overview_labels = {item['label'] for item in matching_day['slots']}
        self.assertNotIn('10:00', overview_labels)
        self.assertNotIn('10:15', overview_labels)
        self.assertIn('11:00', overview_labels)

    def test_public_api_cannot_book_a_blocked_time_even_with_direct_post(self):
        BlockedPeriod.objects.create(
            staff=self.staff,
            starts_at=self._local_dt(10, 0),
            ends_at=self._local_dt(11, 0),
            reason='[BLOCKNOTE][STAFF] Pause',
        )

        payload = {
            'service_id': self.service.pk,
            'staff_id': self.staff.pk,
            'starts_at': self._local_dt(10, 0).isoformat(),
            'first_name': 'Blocked',
            'last_name': 'Customer',
            'email': 'blocked@example.com',
            'phone': '+49123456789',
            'referral_source': 'Google',
            'returning_customer': False,
            'marketing_opt_in': False,
            'cancellation_terms_accepted': True,
            'privacy_accepted': True,
        }
        response = self.client.post(
            reverse('booking:appointments'),
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error'], 'time_not_available')
        self.assertEqual(Appointment.objects.count(), 0)

        payload['starts_at'] = self._local_dt(11, 0).isoformat()
        payload['email'] = 'free@example.com'
        free_response = self.client.post(
            reverse('booking:appointments'),
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(free_response.status_code, 201)
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(
            timezone.localtime(Appointment.objects.get().starts_at).strftime('%H:%M'),
            '11:00',
        )
