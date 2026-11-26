from importlib.util import find_spec
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings

from booking.models import StaffMember


@skipUnless(find_spec("playwright"), "Chromium browser regression")
@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class AdminResponsiveShellBrowserTests(StaticLiveServerTestCase):
    @patch('booking.app_management_views._api', return_value={'ok': True, 'hero_images': [
        {'variant': 'default', 'label': 'Standard'},
        {'variant': 'female', 'label': 'Damen'},
        {'variant': 'male', 'label': 'Herren'},
    ]})
    def test_admin_routes_at_requested_widths(self, upstream):
        admin = get_user_model().objects.create_user(
            username='synthetic-visual-admin', is_staff=True, is_superuser=True,
        )
        StaffMember.objects.create(display_name='Synthetic clinician', active=True)
        pages = {
            'calendar': '/verwaltung/kalender/',
            'patients': '/verwaltung/app/patients/',
            'settings': '/verwaltung/einstellungen/',
            'dashboard': '/verwaltung/dashboard/',
            'hero': '/verwaltung/app/hero/',
        }
        cookies = {}
        for width in (390, 768, 1024, 1366, 1920):
            self.client.cookies.clear()
            self.client.force_login(admin)
            session = self.client.session
            session['aplus_app_admin'] = True
            session.save()
            cookies[width] = self.client.cookies[settings.SESSION_COOKIE_NAME].value

        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
            for width, cookie in cookies.items():
                context = browser.new_context(
                    viewport={'width': width, 'height': 900},
                    is_mobile=width == 390, has_touch=width == 390,
                )
                context.add_cookies([{
                    'name': settings.SESSION_COOKIE_NAME,
                    'value': cookie,
                    'url': self.live_server_url,
                }])
                context.route('**/*', lambda route: (
                    route.continue_()
                    if route.request.url.startswith(self.live_server_url + '/')
                    and '/verwaltung/api/' not in route.request.url
                    else route.abort()
                ))
                page = context.new_page()
                for label, path in pages.items():
                    response = page.goto(self.live_server_url + path, wait_until='load', timeout=12000)
                    self.assertEqual(response.status, 200, f"{label}: {page.title()}")
                    self.assertNotIn('/login/', page.url)
                    if label == 'calendar' and width == 390:
                        heading = page.locator('.sb-calendar-shell.is-day .sb-day-head').first
                        dock = page.locator('.sb-reference-date-dock').first
                        self.assertEqual(heading.evaluate('(node) => getComputedStyle(node).position'), 'sticky')
                        for scroll_top in (0, 120, 360):
                            page.locator('main.sb-admin-shell').evaluate(
                                '(main, top) => {main.scrollTop = top}', scroll_top,
                            )
                            holder, bar = heading.bounding_box(), dock.bounding_box()
                            self.assertAlmostEqual(holder['y'], bar['y'] + bar['height'], delta=3)
                    result = page.evaluate('''() => ({
                        viewport: document.documentElement.clientWidth,
                        document: document.documentElement.scrollWidth,
                        main: Math.round(document.querySelector('main').getBoundingClientRect().width),
                        body: Math.round(document.body.getBoundingClientRect().width),
                        right: Math.round(document.querySelector('main').getBoundingClientRect().right),
                    })''')
                    self.assertEqual(result['viewport'], result['document'], (label, width, result))
                    if width >= 1366:
                        self.assertAlmostEqual(result['main'], width - 252, delta=2, msg=(label, width, result))
                    if label == 'settings':
                        self.assertEqual(page.locator('[data-view-menu-open], [data-iphone-date-open], [data-reference-date-dock]').count(), 0)
                        self.assertEqual(page.locator('.premium-sidebar [aria-current=page]').get_attribute('href'), path)
                    self.assertEqual(page.locator('nav a[href="/verwaltung/app/reviews/"]').count(), 0)
                    if label == 'calendar':
                        self.assertNotIn('Physical in-flow reservation', page.locator('body').inner_text())
                context.close()
            browser.close()
