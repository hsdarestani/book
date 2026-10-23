"""Keep the premium shell consistent without altering calendar behavior."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class ManagementThemeIsolationTests(TestCase):
    def setUp(self):
        # All tests here are offline, including accidentally introduced calls.
        network = patch('socket.create_connection', side_effect=AssertionError('Network is disabled in theme tests'))
        network.start()
        self.addCleanup(network.stop)
        self.client.force_login(get_user_model().objects.create_user(
            username='theme-admin', is_staff=True, is_superuser=True,
        ))

    def enable_sso(self):
        session = self.client.session
        session['aplus_app_admin'] = True
        session['aplus_admin_authorization'] = 'Bearer test-only'
        session.save()

    def test_calendar_never_loads_management_theme_with_or_without_sso(self):
        for sso in (False, True):
            if sso:
                self.enable_sso()
            for path in ('/verwaltung/', '/verwaltung/kalender/'):
                with self.subTest(path=path, sso=sso):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertNotContains(response, 'clinic-management.css')
                    self.assertNotContains(response, 'data-clinic-design="calm"')
                    self.assertContains(response, 'clinic-navigation.css')
                    self.assertContains(response, 'clinic-premium-all-v2.css')
                    self.assertContains(response, 'data-admin-page="calendar"')

    @patch('booking.app_management_views._api', return_value={'ok': True})
    def test_premium_theme_loads_last_for_management_routes(self, api):
        for sso in (False, True):
            if sso:
                self.enable_sso()
            for path in ('/verwaltung/dashboard/', '/verwaltung/mehr/',
                         '/verwaltung/app/patients/', '/verwaltung/app/wallet/',
                         '/verwaltung/app/reviews/', '/verwaltung/app/referrals/',
                         '/verwaltung/app/hero/', '/verwaltung/einstellungen/',
                         '/verwaltung/behandlungen/', '/verwaltung/information/'):
                if not sso and '/app/' in path:
                    continue  # App management intentionally requires an SSO session.
                with self.subTest(path=path, sso=sso):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    source = response.content.decode()
                    self.assertIn('data-clinic-design="premium"', source)
                    head = source.split('</head>')[0]
                    self.assertEqual(head.count('data-clinic-design-sheet'), 1)
                    self.assertEqual(head.count('data-clinic-navigation-sheet'), 1)
                    self.assertEqual(head.count('clinic-premium-all-v2.css'), 1)
                    self.assertGreater(head.index('clinic-premium-all-v2.css'), head.index('data-clinic-navigation-sheet'))
                    self.assertGreater(head.index('data-clinic-navigation-sheet'), head.index('data-clinic-design-sheet'))
