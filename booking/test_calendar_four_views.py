"""SimplyBook mobile calendar view parity: real data in four usable layouts."""
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .models import Appointment, Customer, Service, StaffMember, WorkingHour


class CalendarFourViewsTests(TestCase):
    def setUp(self):
        admin = get_user_model().objects.create_user(
            username='view-parity-admin', password='secret',
            is_staff=True, is_superuser=True,
        )
        self.client.force_login(admin)
        session = self.client.session
        session['aplus_app_admin'] = True
        session.save()
        self.day = timezone.localdate() + timedelta(days=3)
        self.staff_a = StaffMember.objects.create(
            display_name='Ärztin Eins', role='doctor', active=True, sort_order=1,
        )
        self.staff_b = StaffMember.objects.create(
            display_name='Ärztin Zwei', role='doctor', active=True, sort_order=2,
        )
        self.botox = Service.objects.create(
            name='Botox test', slug='test-botox', sort_order=1,
        )
        self.laser = Service.objects.create(
            name='Laser test', slug='test-laser', sort_order=2,
        )
        self.staff_a.services.add(self.botox, self.laser)
        self.staff_b.services.add(self.botox)
        for staff in (self.staff_a, self.staff_b):
            WorkingHour.objects.create(
                staff=staff, weekday=self.day.weekday(),
                start_time=time(10), end_time=time(18), active=True,
            )
        tz = timezone.get_current_timezone()
        for staff, service, hour, name in [
            (self.staff_a, self.botox, 10, 'Eigener Botoxtermin'),
            (self.staff_a, self.laser, 11, 'Eigener Lasertermin'),
            (self.staff_b, self.botox, 12, 'Zweiter Arzttermin'),
        ]:
            customer = Customer.objects.create(
                first_name=name.split()[0], last_name=' '.join(name.split()[1:]),
                email=f'{hour}@view-test.example',
            )
            start = timezone.make_aware(datetime.combine(self.day, time(hour)), tz)
            Appointment.objects.create(
                staff=staff, customer=customer, service=service,
                starts_at=start, ends_at=start + timedelta(minutes=30),
            )

    def calendar(self, mode):
        response = self.client.get('/verwaltung/kalender/', {
            'date':self.day.isoformat(), 'cal_view':mode,
            'staff':self.staff_a.pk,
        })
        self.assertEqual(response.status_code,200)
        return response

    def test_day_and_week_are_functional(self):
        day = self.calendar('day')
        week = self.calendar('week')
        self.assertEqual(len(day.context['calendar_days']),1)
        self.assertEqual(len(week.context['calendar_days']),7)
        self.assertContains(day, 'Eigener Botoxtermin')
        self.assertNotContains(day, 'Zweiter Arzttermin')
        self.assertContains(week, 'is-week')
        self.assertContains(week, 'Woche')

    def test_provider_mode_shows_separate_staff_columns_with_actual_data(self):
        response = self.calendar('provider')
        columns = response.context['calendar_days']
        self.assertEqual([c['column_label'] for c in columns],
                         ['Ärztin Eins','Ärztin Zwei'])
        self.assertEqual([a['item'].staff_id for a in columns[0]['appointments']],
                         [self.staff_a.pk,self.staff_a.pk])
        self.assertEqual([a['item'].staff_id for a in columns[1]['appointments']],
                         [self.staff_b.pk])
        self.assertEqual(len(columns[0]['working_segments']),1)
        self.assertEqual(len(columns[1]['working_segments']),1)
        self.assertContains(response,'is-provider is-grouped')

    def test_service_mode_shows_real_service_specific_appointments(self):
        response = self.calendar('service')
        columns = response.context['calendar_days']
        self.assertEqual([c['column_label'] for c in columns],
                         ['Botox test', 'Laser test'])
        self.assertEqual([a['item'].service_id for a in columns[0]['appointments']],
                         [self.botox.pk])
        self.assertEqual([a['item'].service_id for a in columns[1]['appointments']],
                         [self.laser.pk])
        self.assertNotContains(response,'Zweiter Arzttermin')
        self.assertContains(response,'is-service is-grouped')

    def test_all_four_views_are_real_links_with_visible_chooser(self):
        response = self.calendar('day')
        for mode, label in [('day','Tagesansicht'),('week','Woche'),
                            ('provider','Dienstleister-Ansicht'),
                            ('service','Dienstleistungsansicht')]:
            with self.subTest(mode=mode):
                self.assertContains(response,'cal_view='+mode)
                self.assertContains(response,label)
        self.assertContains(response, 'sb-reference-mode-chevron')
        self.assertContains(response, 'admin-calendar-view-modes-v1.css')
        self.assertContains(response, 'aria-haspopup="menu"')
