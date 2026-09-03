from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Appointment, BlockedPeriod, Customer, Service, StaffMember, WorkingHour
from .services import available_slots


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class MobileAdminFlowTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            username='mobile-admin',
            password='test-password',
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.admin)

        self.service = Service.objects.create(
            name='Testbehandlung',
            slug='testbehandlung-mobile-admin',
            duration_minutes=30,
            buffer_minutes=0,
            price_label='30 €',
            active=True,
            bookable=True,
            requires_confirmation=False,
            sort_order=1,
        )
        self.staff = StaffMember.objects.create(
            display_name='Frau Test Ärztin',
            role='doctor',
            active=True,
            sort_order=1,
        )
        self.staff.services.add(self.service)
        self.customer = Customer.objects.create(
            first_name='Mobile',
            last_name='Test',
            email='mobile-test@example.com',
            phone='+49123456789',
        )
        self.day = timezone.localdate() + timedelta(days=2)
        WorkingHour.objects.create(
            staff=self.staff,
            weekday=self.day.weekday(),
            start_time=time(9, 0),
            end_time=time(13, 0),
            active=True,
        )

    def test_dashboard_contains_quarter_hour_mobile_controls(self):
        response = self.client.get(
            reverse('booking:dashboard'),
            {'staff': self.staff.pk, 'date': self.day.isoformat(), 'cal_view': 'day'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="appointment_time" step="900"')
        self.assertContains(response, 'name="note_start" step="900"')
        self.assertContains(response, 'name="note_end" step="900"')
        self.assertContains(response, 'name="block_start" step="900"')
        self.assertContains(response, 'name="block_end" step="900"')
        self.assertContains(response, 'data-open-booking')
        self.assertContains(response, 'data-open-customer-picker')
        self.assertContains(response, 'data-open-block')
        self.assertContains(response, 'data-modal="block"')
        self.assertContains(response, 'name="action" value="add_calendar_block"')
        self.assertContains(response, 'https://a-esthetic.de/wp-content/uploads/prev.png')

    def test_separate_admin_section_routes_render(self):
        route_names = [
            'admin_dashboard',
            'admin_calendar',
            'admin_bookings',
            'admin_customers',
            'admin_settings',
            'admin_services',
            'admin_information',
        ]
        for route_name in route_names:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(f'booking:{route_name}'), {'staff': self.staff.pk})
                self.assertEqual(response.status_code, 200)

    def test_admin_can_create_booking_at_quarter_hour(self):
        response = self.client.post(
            reverse('booking:dashboard'),
            {
                'action': 'add_appointment',
                'staff_id': self.staff.pk,
                'appointment_staff_id': self.staff.pk,
                'service_id': self.service.pk,
                'customer_id': self.customer.pk,
                'appointment_date': self.day.isoformat(),
                'appointment_time': '10:15',
                'return_date': self.day.isoformat(),
                'return_view': 'day',
            },
        )
        self.assertEqual(response.status_code, 302)
        appointment = Appointment.objects.get(customer=self.customer, service=self.service)
        local_start = timezone.localtime(appointment.starts_at)
        self.assertEqual((local_start.hour, local_start.minute), (10, 15))
        self.assertEqual(appointment.source, 'admin')

    def test_plain_note_does_not_block_booking_slots(self):
        response = self.client.post(
            reverse('booking:dashboard'),
            {
                'action': 'add_calendar_note',
                'staff_id': self.staff.pk,
                'note_date': self.day.isoformat(),
                'note_start': '10:00',
                'note_end': '11:00',
                'note_scope': 'staff',
                'note_text': 'Interne Notiz',
                'return_date': self.day.isoformat(),
                'return_view': 'day',
            },
        )
        self.assertEqual(response.status_code, 302)
        note = BlockedPeriod.objects.get(staff=self.staff)
        self.assertTrue(note.reason.startswith('[NOTE]'))

        slots = available_slots(self.service, self.staff, self.day)
        quarter_hours = {timezone.localtime(slot).strftime('%H:%M') for slot in slots}
        self.assertIn('10:00', quarter_hours)
        self.assertIn('10:15', quarter_hours)

    def test_dedicated_block_action_blocks_slots_and_renders_in_calendar(self):
        response = self.client.post(
            reverse('booking:admin_calendar'),
            {
                'action': 'add_calendar_block',
                'staff_id': self.staff.pk,
                'block_date': self.day.isoformat(),
                'block_start': '10:00',
                'block_end': '11:00',
                'block_scope': 'staff',
                'block_text': 'Pause',
            },
        )
        self.assertEqual(response.status_code, 302)
        block = BlockedPeriod.objects.get(staff=self.staff)
        self.assertTrue(block.reason.startswith('[BLOCKNOTE]'))
        self.assertIn('notice=block', response['Location'])
        self.assertIn(f'focus_block={block.pk}', response['Location'])
        self.assertIn(f'date={self.day.isoformat()}', response['Location'])
        self.assertIn(f'staff={self.staff.pk}', response['Location'])

        slots = available_slots(self.service, self.staff, self.day)
        quarter_hours = {timezone.localtime(slot).strftime('%H:%M') for slot in slots}
        self.assertNotIn('10:00', quarter_hours)
        self.assertNotIn('10:15', quarter_hours)
        self.assertIn('11:00', quarter_hours)

        focused = self.client.get(response['Location'])
        self.assertEqual(focused.status_code, 200)
        self.assertContains(focused, 'sb-calendar-block is-blocked-note')
        self.assertContains(focused, 'Pause')
        self.assertContains(focused, '10:00–11:00')
        self.assertContains(focused, 'is-focused-block')

    def test_block_action_rejects_non_quarter_hour_times(self):
        response = self.client.post(
            reverse('booking:admin_calendar'),
            {
                'action': 'add_calendar_block',
                'staff_id': self.staff.pk,
                'block_date': self.day.isoformat(),
                'block_start': '10:10',
                'block_end': '11:00',
                'block_scope': 'staff',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('notice=block-error', response['Location'])
        self.assertFalse(BlockedPeriod.objects.exists())
