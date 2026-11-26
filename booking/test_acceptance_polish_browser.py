import os
from importlib.util import find_spec
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings

from booking.models import StaffMember


@skipUnless(find_spec('playwright'), 'Chromium acceptance check')
@override_settings(STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                             'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class AdminAcceptancePolishTests(StaticLiveServerTestCase):
    @patch('booking.app_management_views._api', return_value={'ok': True, 'hero_images': [
        {'variant': 'default', 'label': 'Standard'}, {'variant': 'frau', 'label': 'Damen'},
        {'variant': 'herr', 'label': 'Herren'},
    ]})
    def test_settings_hero_and_german_date_fields(self, upstream):
        from playwright.sync_api import sync_playwright

        admin = get_user_model().objects.create_user(username='synthetic-layout-admin', is_staff=True, is_superuser=True)
        StaffMember.objects.create(display_name='Synthetic clinician', active=True)
        self.client.force_login(admin)
        session = self.client.session
        session['aplus_app_admin'] = True
        session.save()
        with sync_playwright() as p:
            launch = {'headless': True, 'args': ['--no-sandbox']}
            if os.environ.get('BOOK_QA_CHROMIUM'):
                launch['executable_path'] = os.environ['BOOK_QA_CHROMIUM']
            browser = p.chromium.launch(**launch)
            context = browser.new_context(locale='en-US', viewport={'width': 1920, 'height': 900})
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                                  'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                                  'url': self.live_server_url}])
            context.route('**/*', lambda r: r.continue_() if r.request.url.startswith(self.live_server_url + '/') else r.abort())
            page = context.new_page()
            for path, active in [('/verwaltung/app/hero/', 'hero'), ('/verwaltung/einstellungen/', 'settings')]:
                self.assertEqual(page.goto(self.live_server_url + path).status, 200)
                self.assertEqual(page.locator('.premium-sidebar [aria-current=page]').get_attribute('href'), path)
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth === document.documentElement.clientWidth'))
                if active == 'hero':
                    photos = page.locator('.hero-admin-photo').all()
                    self.assertEqual(len(photos), 3)
                    heights = [item.bounding_box()['y'] for item in photos]
                    self.assertLess(max(heights)-min(heights), 4)
            self.assertEqual(page.goto(self.live_server_url + '/verwaltung/app/forms/').status, 200)
            field = page.locator('input[name=from]')
            self.assertEqual(field.get_attribute('placeholder'), 'TT.MM.JJJJ')
            field.fill('30.12.2026')
            page.locator('.intake-filters button[type=submit]').click()
            page.wait_for_url('**/verwaltung/app/forms/?*')
            self.assertEqual(page.locator('input[name=from]').input_value(), '30.12.2026')
            page.goto(self.live_server_url + '/verwaltung/app/forms/?from=31.02.2026')
            self.assertIn('gültiges Datum', page.locator('[role=alert]').inner_text())
            browser.close()
