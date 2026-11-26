from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import AdminAccessProfile, Customer, PatientFormNotificationRead, PatientRecord


class DesktopFormNotificationsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="desk-admin", is_staff=True)
        self.patient = Customer.objects.create(first_name="Anna", last_name="Test",
                                               email="desk@example.test")
        self.url = reverse('booking:patient_form_notifications')

    def test_only_staff_can_read_private_feed(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(User.objects.create_user(username="visitor"))
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_initial_sync_suppresses_old_form_history(self):
        PatientRecord.objects.create(customer=self.patient, kind="form",
                                     source="botoxbogen", title="Botoxbogen",
                                     note="Sensitive clinic details.")
        self.client.force_login(self.admin)
        result = self.client.get(self.url)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["events"], [])
        self.assertGreater(result.json()["cursor"], 0)
        self.assertEqual(result['Cache-Control'].find('no-store') >= 0, True)

    def test_cursor_returns_new_opaque_id_and_no_health_info(self):
        old = PatientRecord.objects.create(customer=self.patient, kind="form",
                                           source="botoxbogen", title="Old", note="SENSITIVE OLD")
        new = PatientRecord.objects.create(customer=self.patient, kind="form",
                                           source="botoxbogen", title="New", note="SENSITIVE NEW")
        PatientRecord.objects.create(customer=self.patient, kind="form",
                                     source="a_esthetic_app", title="Unrelated", note="secret")
        self.client.force_login(self.admin)
        response = self.client.get(self.url, {'after': old.pk})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["events"]), 1)
        self.assertEqual(data["events"][0]["id"], new.pk)
        self.assertEqual(data["events"][0]["customer_id"], self.patient.pk)
        self.assertNotIn("SENSITIVE", response.content.decode("utf-8"))
        self.assertNotIn(self.patient.email, response.content.decode("utf-8"))

    def test_validates_cursor(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url, {'after': 'abc'}).status_code, 400)

    def test_admin_pages_include_shared_logo_fix_but_calendar_partial_unchanged(self):
        from django.template.loader import get_template
        for page in ("booking/admin_dashboard_lambo.html", "booking/app_management.html",
                     "booking/admin_more.html"):
            template = get_template(page)
            self.assertIn("clinic-web-polish-v2.css", template.template.source)
            self.assertIn("clinic-desktop-notifications-v1.js", template.template.source)
        cal = get_template("booking/_shared_admin_calendar.html").template.source
        self.assertNotIn("clinic-web-polish-v2.css", cal)


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class PatientFormNotificationInboxTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='inbox-admin', is_staff=True)
        patient = Customer.objects.create(first_name='Synthetic', last_name='Inbox', email='inbox@example.invalid')
        self.form = PatientRecord.objects.create(customer=patient, kind='form', source='office_intake',
                                                 title='Sensitive title', note='Sensitive body')
        self.other = PatientRecord.objects.create(customer=patient, kind='document', source='manual', title='Private')
        self.url = reverse('booking:notification_inbox')
        self.client = Client(enforce_csrf_checks=True)

    def test_inbox_read_state_is_private_and_idempotent(self):
        self.client.force_login(self.staff)
        reply = self.client.get(self.url)
        data = reply.json()
        self.assertEqual(len(data['events']), 1)
        self.assertEqual(data['unread'], 1)
        self.assertFalse(data['events'][0]['read'])
        self.assertEqual(data['events'][0]['id'], str(self.form.public_id))
        self.assertContains(reply, 'Neuer Aufnahmebogen')
        self.assertNotContains(reply, 'Sensitive')
        self.assertIn('no-store', reply['Cache-Control'])
        self.assertEqual(self.client.get(data['events'][0]['url']).status_code, 200)
        payload = {'record': self.form.public_id}
        self.assertEqual(self.client.post(self.url, payload).status_code, 403)
        csrf = {'HTTP_X_CSRFTOKEN': data['csrf_token']}
        self.assertEqual(self.client.post(self.url, {'record': 'invalid'}, **csrf).status_code, 400)
        self.assertEqual(self.client.post(self.url, {'record': self.other.public_id}, **csrf).status_code, 404)
        for _ in range(2):
            self.assertEqual(self.client.post(self.url, payload, **csrf).status_code, 200)
        after = self.client.get(self.url).json()
        self.assertEqual(after['unread'], 0)
        self.assertTrue(after['events'][0]['read'])
        self.assertEqual(PatientFormNotificationRead.objects.count(), 1)
        self.client.force_login(User.objects.create_user(username='inbox-other', is_staff=True))
        self.assertEqual(self.client.get(self.url).json()['unread'], 1)

    def test_inbox_remains_inaccessible_to_public_and_view_only_users(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        admin = User.objects.create_user(username='inbox-view-only', is_staff=True)
        AdminAccessProfile.objects.create(user=admin, view_only=True)
        self.client.force_login(admin)
        self.assertEqual(self.client.get(self.url).status_code, 403)
