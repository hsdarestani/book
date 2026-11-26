from datetime import date, datetime, time, timedelta
from importlib.util import find_spec
from os import environ
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings

from booking.clinical_time import CLINIC_TZ
from booking.models import Appointment, BlockedPeriod, Customer, Service, StaffMember


@skipUnless(find_spec('playwright'), 'Chromium calendar acceptance')
@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class PopulatedCalendarBrowserTests(StaticLiveServerTestCase):
    def test_december_calendar_scroll_menu_colors_and_time(self):
        from playwright.sync_api import expect, sync_playwright

        admin = get_user_model().objects.create_user(username='synthetic-calendar-admin', is_staff=True, is_superuser=True)
        staff = StaffMember.objects.create(display_name='Synthetic Clinician', active=True)
        service = Service.objects.create(name='Synthetic Treatment', slug='calendar-december-fixture')
        staff.services.add(service)
        day = date(2026, 12, 30)

        def first_at(hours, minutes):
            return datetime.combine(day, time(hours, minutes), tzinfo=CLINIC_TZ)

        for name, begin, clinical, reserved in [
            ('Calendar Long', first_at(18, 30), 45, 55),
            ('Calendar Overlap', first_at(18, 45), 15, 15),
            ('Calendar Short', first_at(17, 0), 15, 15),
        ]:
            patient = Customer.objects.create(first_name='Synthetic', last_name=name)
            Appointment.objects.create(staff=staff, service=service, customer=patient, starts_at=begin,
                                       ends_at=begin + timedelta(minutes=reserved), status='confirmed',
                                       treatment_minutes_at_booking=clinical)
        BlockedPeriod.objects.create(staff=staff, starts_at=first_at(10, 0), ends_at=first_at(14, 0),
                                     reason='[BLOCKNOTE][STAFF] Synthetic Block')
        base = self.live_server_url
        route = base + f'/verwaltung/kalender/?date={day}&staff={staff.pk}'
        screenshots = environ.get('BOOK_QA_SCREENSHOTS')
        viewports = ((1920, 'Pacific/Honolulu'), (1366, 'Europe/Berlin'), (390, 'Pacific/Kiritimati'))
        cookies = {}
        for width, _ in viewports:
            for mode in ('week', 'day'):
                self.client.cookies.clear()
                self.client.force_login(admin)
                session = self.client.session
                session['aplus_app_admin'] = True
                session.save()
                cookies[width, mode] = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
            for width, zone in viewports:
                with self.subTest(width=width, zone=zone):
                    context = browser.new_context(viewport={'width': width, 'height': 910}, timezone_id=zone,
                                                  is_mobile=width == 390, has_touch=width == 390)
                    context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                                          'value': cookies[width, 'week'],
                                          'url': base}])
                    context.route('**/*', lambda req: req.continue_() if req.request.url.startswith(base + '/') else req.abort())
                    page = context.new_page()
                    response = page.goto(route + '&cal_view=week', wait_until='load')
                    self.assertEqual(response.status, 200)
                    menu = page.locator('#calendar-view-menu')
                    button = page.locator('[data-view-menu-open]:visible').first
                    button.click()
                    expect(menu).to_be_visible()
                    self.assertEqual(menu.get_by_role('menuitem').count(), 4)
                    menu_box, button_box = menu.bounding_box(), button.bounding_box()
                    self.assertLessEqual(abs(menu_box['y'] - (button_box['y'] + button_box['height'])), 13)
                    self.assertLessEqual(menu_box['x'], button_box['x'] + button_box['width'])
                    if screenshots:
                        Path(screenshots).mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=Path(screenshots) / f'populated-menu-{width}.png')
                    page.keyboard.press('Escape')
                    expect(menu).to_be_hidden()
                    expect(button).to_be_focused()
                    page.locator('.sb-horizontal-track-viewport').scroll_into_view_if_needed()
                    viewport = page.locator('.sb-horizontal-track-viewport')
                    axis = viewport.locator('.sb-time-axis')
                    ruler_x = axis.bounding_box()['x']
                    range_ = viewport.evaluate('e => e.scrollWidth - e.clientWidth')
                    viewport.evaluate('(e,left) => { e.scrollTop=200; e.scrollLeft=left }', min(range_, 350))
                    self.assertGreater(viewport.evaluate('e => e.scrollTop'), 0)
                    if width < 1920:
                        self.assertGreater(viewport.evaluate('e => e.scrollLeft'), 0)
                    self.assertAlmostEqual(axis.bounding_box()['x'], ruler_x, delta=2)
                    for head in viewport.locator('.sb-day-head').all():
                        self.assertAlmostEqual(head.bounding_box()['y'], viewport.bounding_box()['y'], delta=4)
                    expect(page.locator('.ferrari-calendar-sticky')).to_have_count(0)
                    expect(page.locator('.sb-time-axis')).to_have_count(1)
                    expect(page.locator('.sb-day-head')).to_have_count(7)
                    long_ = page.locator('.sb-calendar-event[data-calendar-start="18:30"]')
                    overlap = page.locator('.sb-calendar-event[data-calendar-start="18:45"]')
                    short = page.locator('.sb-calendar-event[data-calendar-start="17:00"]')
                    block = page.locator('.sb-calendar-block:not(.is-note)').first
                    expect(long_).to_contain_text('18:30–19:15 · +10 Min. Puffer')
                    expect(short).to_have_class('sb-calendar-event is-compact')
                    expect(long_).to_have_css('background-color', 'rgb(33, 91, 159)')
                    expect(block).to_have_css('background-color', 'rgb(255, 227, 173)')
                    self.assertGreater(overlap.bounding_box()['x'], long_.bounding_box()['x'] + 15)
                    self.assertAlmostEqual(long_.evaluate('e => parseFloat(e.style.height)') /
                                           overlap.evaluate('e => parseFloat(e.style.height)'), 55/15, delta=.02)
                    long_.scroll_into_view_if_needed()
                    if screenshots:
                        page.screenshot(path=Path(screenshots) / f'populated-week-{width}.png')
                    page.close()
                    context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                                          'value': cookies[width, 'day'], 'url': base}])
                    page = context.new_page()
                    response = page.goto(route + '&cal_view=day', wait_until='load')
                    self.assertEqual(response.status, 200)
                    self.assertTrue('data-calendar-mode="day"' in response.text(), (page.url, page.title()))
                    expect(page.locator('.sb-day-head')).to_have_count(1)
                    expect(page.locator('.sb-time-axis')).to_have_count(1)
                    expect(page.locator('.sb-calendar-event[data-calendar-start="18:30"]')).to_contain_text('18:30–19:15')
                    if width == 390:
                        expect(page.locator('.sb-reference-day-label')).to_contain_text('30.12.2026')
                    if screenshots:
                        page.eval_on_selector('.sb-calendar-event[data-calendar-start="18:30"]',
                                              'e => e.scrollIntoView({block: "center"})')
                        page.screenshot(path=Path(screenshots) / f'populated-day-{width}.png')
                    context.close()
