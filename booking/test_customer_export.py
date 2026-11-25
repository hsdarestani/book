import csv
import io

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import AdminAccessProfile, Customer, SimplyBookClientLink


class CustomerExportTests(TestCase):
    path = '/verwaltung/app/patients/'

    def setUp(self):
        self.user = get_user_model().objects.create_user(username='export-admin', is_staff=True)
        self.client.force_login(self.user)
        session = self.client.session
        session['aplus_app_admin'] = True
        session.save()
        self.customer = Customer.objects.create(
            first_name='=1+1', last_name='Muster', email='source@invalid.local', phone='+49123456789',
        )

    def parse(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertIn('no-store', response['Cache-Control'])
        return list(csv.reader(io.StringIO(response.content.decode('utf-8-sig')), delimiter=';'))

    def test_all_ignores_display_limit_and_search_and_escapes_formulas(self):
        Customer.objects.bulk_create([
            Customer(first_name=f'Name{i}', last_name='Test', email=f'c{i}@example.test')
            for i in range(260)
        ])
        rows = self.parse(self.client.get(self.path, {'export': 'all', 'q': 'no-match'}))
        self.assertEqual(len(rows), 262)
        original = next(row for row in rows[1:] if row[0] == str(self.customer.pk))
        self.assertEqual(original[1:], ["'=1+1", 'Muster', '', "'+49123456789"])

    def test_simplybook_uses_each_source_id_including_shared_local_profile(self):
        for external_id in ('1001', '1002'):
            SimplyBookClientLink.objects.create(
                customer=self.customer, external_client_id=external_id,
                source_name='Quellname', source_email='source@example.test', source_phone='012345678',
            )
        rows = self.parse(self.client.get(self.path, {'export': 'simplybook'}))
        self.assertEqual([row[0] for row in rows[1:]], ['1001', '1002'])
        self.assertEqual(rows[1][1:4], ['Quellname', 'source@example.test', '012345678'])
        self.assertEqual(rows[2][4], str(self.customer.pk))

    def test_unconfirmed_staff_cannot_export(self):
        session = self.client.session
        session.pop('aplus_app_admin', None)
        session.save()
        self.assertEqual(self.client.get(self.path, {'export': 'all'}).status_code, 403)

    def test_view_only_cannot_export_even_with_confirmed_session(self):
        AdminAccessProfile.objects.create(user=self.user, view_only=True)
        for mode in ('all', 'simplybook'):
            self.assertEqual(self.client.get(self.path, {'export': mode}).status_code, 403)

    def test_anonymous_cannot_export(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.path, {'export': 'all'}).status_code, 302)
