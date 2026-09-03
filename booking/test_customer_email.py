from datetime import timedelta

from django.template.loader import render_to_string
from django.test import TestCase
from django.utils import timezone

from .emails import _email_staff_name
from .models import Appointment, Customer, Service, StaffMember


class CustomerEmailPresentationTests(TestCase):
    def setUp(self):
        self.service = Service.objects.create(
            name='Ästhetische Erstberatung',
            slug='email-test-consultation',
            duration_minutes=30,
            price_label='30 €',
        )
        self.staff = StaffMember.objects.create(
            display_name='Frau Ariane Regaei',
            role='doctor',
        )
        self.customer = Customer.objects.create(
            first_name='Anna',
            last_name='Muster',
            email='anna@example.com',
            phone='0123456789',
        )
        starts_at = timezone.now() + timedelta(days=3)
        self.appointment = Appointment.objects.create(
            customer=self.customer,
            service=self.service,
            staff=self.staff,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            status='new',
        )

    def test_doctor_name_is_shortened_for_customer_email(self):
        self.assertEqual(_email_staff_name(self.staff), 'Frau A. Regaei')

    def test_customer_email_hides_status_and_price_and_shows_useful_links(self):
        html = render_to_string(
            'booking/email_booking_confirmation.html',
            {
                'appointment': self.appointment,
                'local_start': timezone.localtime(self.appointment.starts_at),
                'staff_email_name': 'Frau A. Regaei',
                'staff_image_url': 'https://example.com/doctor.jpg',
                'calendar_url': 'https://book.a-esthetic.de/test.ics',
                'directions_url': 'https://example.com/directions',
                'instagram_url': 'https://instagram.com/aplus.esthetic/',
                'google_reviews_url': 'https://example.com/reviews',
                'whatsapp_url': 'https://wa.me/496971417012',
                'clinic_address': 'Stiftstraße 14, 60313 Frankfurt am Main · 2. OG',
                'clinic_phone': '069 71417012',
                'clinic_phone_href': 'tel:+496971417012',
                'website_url': 'https://a-esthetic.de',
                'admin_url': 'https://book.a-esthetic.de/verwaltung/',
                'is_admin': False,
            },
        )
        self.assertNotIn('>Preis<', html)
        self.assertNotIn('>Status<', html)
        self.assertIn('Behandelnde/r Arzt/Ärztin', html)
        self.assertIn('Frau A. Regaei', html)
        self.assertIn('Hallo Anna,<br>', html)
        self.assertIn('Zum Kalender hinzufügen', html)
        self.assertIn('Wegbeschreibung', html)
        self.assertIn('Instagram', html)
        self.assertIn('Google Bewertungen', html)
        self.assertIn('WhatsApp', html)
        self.assertIn('A+ Esthetic Frankfurt', html)
        self.assertIn('Frankfurt am Main · 2. OG', html)
        self.assertNotIn('Frankfurt am Main, 2. OG', html)
        self.assertIn('phone.png', html)
        self.assertLess(html.index('Kontaktdaten'), html.index('Hilfreiche Links'))

    def test_calendar_download_is_valid_ics(self):
        response = self.client.get(f'/termin/{self.appointment.public_id}/kalender.ics')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('text/calendar'))
        content = response.content.decode('utf-8')
        self.assertIn('BEGIN:VCALENDAR', content)
        self.assertIn('BEGIN:VEVENT', content)
        self.assertIn('A+Esthetic', content)
        self.assertIn('Stiftstraße 14', content)
