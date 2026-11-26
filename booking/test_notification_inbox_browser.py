from importlib.util import find_spec
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings

from .models import Customer, PatientRecord, StaffMember


@skipUnless(find_spec('playwright'), 'Chromium browser regression')
@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class NotificationInboxBrowserTests(StaticLiveServerTestCase):
    def test_bell_uses_in_page_list_and_persists_read_state(self):
        from playwright.sync_api import expect, sync_playwright

        admin = get_user_model().objects.create_user(username='inbox-browser', is_staff=True, is_superuser=True)
        StaffMember.objects.create(display_name='Synthetic Clinician', active=True)
        patient = Customer.objects.create(first_name='Synthetic', last_name='Inbox', email='browser@example.invalid')
        PatientRecord.objects.create(kind='form', source='office_intake', customer=patient, title='Synthetic form')
        self.client.force_login(admin)
        base = self.live_server_url
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context(viewport={'width': 390, 'height': 850}, is_mobile=True, has_touch=True)
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                                  'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                                  'url': base}])
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
            page = context.new_page()
            page.goto(base + '/verwaltung/kalender/', wait_until='load')
            panel = page.locator('#clinic-notification-inbox')
            mobile_bell = page.locator('.sb-reference-calendar-bar [data-clinic-notification-button]')
            expect(mobile_bell).to_be_visible()
            expect(mobile_bell).to_have_attribute('aria-label', 'Benachrichtigungen (1 ungelesen)')
            mobile_bell.click()
            expect(panel.get_by_text('1 ungelesen', exact=False)).to_be_visible()
            expect(panel.get_by_role('link', name='Neuer Aufnahmebogen')).to_be_visible()
            self.assertLessEqual(panel.bounding_box()['x'] + panel.bounding_box()['width'], 390)
            page.keyboard.press('Escape')
            expect(panel).to_be_hidden()
            expect(mobile_bell).to_be_focused()
            mobile_bell.click()
            with page.expect_response(lambda response: response.url.endswith('/api/notifications/')
                                      and response.request.method == 'POST') as marked:
                panel.get_by_role('button', name='Als gelesen markieren').click()
            self.assertEqual(marked.value.status, 200, marked.value.text()[:200])
            expect(panel.get_by_text('0 ungelesen', exact=False)).to_be_visible()
            page.set_viewport_size({'width': 1366, 'height': 850})
            page.reload(wait_until='load')
            desktop_bell = page.locator('.clinic-header-actions [data-clinic-notification-button]')
            desktop_bell.click()
            expect(panel.get_by_text('0 ungelesen', exact=False)).to_be_visible()
            expect(panel.get_by_role('button', name='Als gelesen markieren')).to_have_count(0)
            with page.expect_navigation() as target:
                panel.get_by_role('link', name='Neuer Aufnahmebogen').click()
            self.assertEqual(target.value.status, 200)
            self.assertIn('/ansicht/', page.url)
            browser.close()
