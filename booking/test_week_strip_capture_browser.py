"""End-to-end week-strip touch navigation using the ACTUAL Book admin template.

Unlike the old synthetic fixture this serves the real calendar HTML, all
local stylesheets, the legacy date-strip script, and the independent capture
script; CDP sends browser touch input over the rendered seven-day bar.
"""
import importlib.util
import unittest
from datetime import time
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase, override_settings
from .models import Service, StaffMember, WorkingHour


@unittest.skipUnless(importlib.util.find_spec("playwright"), "Playwright browser installed in CI")
@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class RealCalendarStripCaptureTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="week-capture-admin", password="test-secret",
            is_staff=True, is_superuser=True,
        )
        self.client.force_login(user)
        session=self.client.session
        session["aplus_app_admin"]=True
        session.save()
        self.service=Service.objects.create(name="Week capture test",slug="week-capture-test")
        self.staff=StaffMember.objects.create(display_name="Week capture clinician",role="doctor",active=True)
        self.staff.services.add(self.service)
        for weekday in range(7):
            WorkingHour.objects.create(staff=self.staff,weekday=weekday,start_time=time(9),end_time=time(18),active=True)
        # Django's test DB and session store must NOT be accessed from a
        # Playwright route callback; prerender the actual authenticated pages.
        self.rendered_pages={}
        for mode in ("day","week"):
            response=self.client.get("/verwaltung/kalender/",{
                "date":"2026-11-22","cal_view":mode,"staff":self.staff.pk,
            })
            self.assertEqual(response.status_code,200)
            self.rendered_pages[mode]=response.content

        # Use actual authenticated Django AJAX payloads. Sunday 13 Dec has
        # weekly working hours but must still be visually closed by policy.
        # Sunday 6 Dec and 13 Dec must look identical after in-place navigation.
        self.calendar_day_payloads={}
        for day in ("2026-11-22","2026-12-06","2026-12-13","2026-12-10","2026-12-14"):
            response=self.client.get("/verwaltung/api/calendar-day/",{
                "date": day, "staff": self.staff.pk,
            })
            self.assertEqual(response.status_code,200)
            self.calendar_day_payloads[day]=response.content

    def route(self, route):
        from mimetypes import guess_type
        url=urlsplit(route.request.url)
        if url.netloc!="book.test":
            route.abort()
            return
        if url.path.startswith("/static/"):
            fp=finders.find(url.path[len("/static/"):])
            if fp and Path(fp).is_file():
                content=Path(fp).read_bytes()
                route.fulfill(status=200,body=content,content_type=guess_type(fp)[0] or "application/octet-stream")
            else:
                route.fulfill(status=404,body="Not found")
            return
        if url.path.startswith("/verwaltung/kalender/"):
            mode=parse_qs(url.query).get("cal_view",["day"])[0]
            route.fulfill(status=200,body=self.rendered_pages.get(mode,self.rendered_pages["day"]),
                          content_type="text/html; charset=utf-8")
            return
        if url.path.startswith("/verwaltung/api/calendar-day/"):
            date=parse_qs(url.query).get("date",[""])[0]
            payload=self.calendar_day_payloads.get(date)
            if payload is None:
                route.fulfill(status=400,body='{"ok":false,"error":"unknown_day_test"}',
                              content_type="application/json")
                return
            route.fulfill(status=200,body=payload,content_type="application/json")
            return
        if url.path.startswith("/verwaltung/api/") or url.path.startswith("/api/"):
            route.fulfill(status=200,body='{"ok":true,"appointments":[],"blocks":[]}',
                          content_type="application/json")
            return
        route.fulfill(status=404,body="Not found")

    def drag(self, page, x0, y0, x1, y1):
        devtools=page.context.new_cdp_session(page)
        try:
            devtools.send("Input.dispatchTouchEvent",{
                "type":"touchStart","touchPoints":[{"x":x0,"y":y0,"id":1}]
            })
            for n in range(1,7):
                k=n/6
                devtools.send("Input.dispatchTouchEvent",{
                    "type":"touchMove",
                    "touchPoints":[{"x":x0+(x1-x0)*k,"y":y0+(y1-y0)*k,"id":1}]
                })
                page.wait_for_timeout(18)
            devtools.send("Input.dispatchTouchEvent",{"type":"touchEnd","touchPoints":[]})
        finally:
            devtools.detach()

    def open_calendar(self,browser,mode):
        context=browser.new_context(viewport={"width":390,"height":820},
                                    device_scale_factor=2,is_mobile=True,has_touch=True)
        page=context.new_page()
        page.route("**/*",self.route)
        page.goto(f"https://book.test/verwaltung/kalender/?date=2026-11-22&cal_view={mode}&staff={self.staff.pk}",wait_until="domcontentloaded")
        page.wait_for_function("document.documentElement.dataset.weekStripSwipeVersion==='20261122-strip3'")
        page.locator(".sb-iphone-weekstrip").first.wait_for()
        # Wait for existing calendar JS to swap the server preview for its
        # interactive fixed strip; capture must work regardless of layering.
        page.wait_for_function("document.body.classList.contains('sb-iphone-calendar-ready')")
        rect=page.locator(".sb-reference-date-dock .sb-iphone-weekstrip").bounding_box()
        self.assertIsNotNone(rect)
        self.assertGreater(rect["width"],300)
        self.assertGreater(rect["height"],40)
        return context,page,rect

    def test_december_six_is_visibly_closed_in_real_book_calendar(self):
        for mode in ("day", "week"):
            with self.subTest(mode=mode):
                html = self.client.get("/verwaltung/kalender/", {
                    "date": "2026-12-06", "cal_view": mode, "staff": self.staff.pk,
                }).content.decode("utf-8")
                self.assertIn("is-sunday is-closed-day", html)
                self.assertIn("Geschlossen", html)
                self.assertIn("Sonntag – geschlossen", html)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
            try:
                for mode in ("day", "week"):
                    context,page,_=self.open_calendar(browser,mode)
                    sunday=page.locator(".sb-reference-date-dock .sb-iphone-day.is-sunday")
                    self.assertEqual(sunday.count(),1)
                    label=page.locator(".sb-calendar-day.is-sunday .sb-sunday-closed-label")
                    self.assertEqual(label.count(),1)
                    self.assertEqual(label.inner_text(),"Geschlossen")
                    self.assertIn("Zu",page.evaluate("""() => getComputedStyle(
                        document.querySelector('.sb-reference-date-dock .sb-iphone-day.is-sunday'),
                        '::after'
                    ).content"""))
                    gray=page.evaluate("""() => getComputedStyle(
                        document.querySelector('.sb-reference-date-dock .sb-iphone-day.is-sunday strong')
                    ).backgroundColor""")
                    self.assertNotEqual(gray,"rgba(0, 0, 0, 0)")
                    self.assertNotEqual(gray,"rgb(255, 255, 255)")
                    context.close()
            finally:
                browser.close()

    def test_ajax_navigation_keeps_every_sunday_closed_and_restores_weekdays(self):
        from playwright.sync_api import sync_playwright

        # The fast calendar API's 'closed' is staff-availability state, not
        # the customer Sunday policy. It can be false on an unblocked Sunday.
        import json
        data=json.loads(self.calendar_day_payloads["2026-12-13"])
        self.assertFalse(data["closed"])
        self.assertEqual(data["date"],"2026-12-13")

        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
            try:
                context,page,_=self.open_calendar(browser,"day")
                page.wait_for_function("typeof window.aplusCalendarNavigate === 'function'")
                for day in ("2026-12-06","2026-12-13"):
                    ok=page.evaluate(
                        "(date) => window.aplusCalendarNavigate(date)", day)
                    self.assertTrue(ok)
                    page.wait_for_function(
                        "(day) => new URLSearchParams(location.search).get('date')===day", day)
                    column=page.locator(".sb-calendar-shell.is-day .sb-calendar-day")
                    self.assertIn("is-sunday",column.get_attribute("class"))
                    self.assertIn("is-closed-day",column.get_attribute("class"))
                    label=column.locator(".sb-sunday-closed-label")
                    self.assertEqual(label.count(),1)
                    self.assertEqual(label.inner_text(),"Geschlossen")
                    bg=page.evaluate("""() => getComputedStyle(
                        document.querySelector('.sb-calendar-shell.is-day .sb-calendar-day .sb-day-track')
                    ).backgroundImage""")
                    self.assertIn("repeating-linear-gradient",bg)

                ok=page.evaluate(
                    "() => window.aplusCalendarNavigate('2026-12-14')")
                self.assertTrue(ok)
                page.wait_for_function(
                    "() => new URLSearchParams(location.search).get('date')==='2026-12-14'")
                column=page.locator(".sb-calendar-shell.is-day .sb-calendar-day")
                self.assertNotIn("is-sunday",column.get_attribute("class"))
                self.assertNotIn("is-closed-day",column.get_attribute("class"))
                self.assertEqual(column.locator(".sb-sunday-closed-label").count(),0)
                context.close()
            finally:
                browser.close()

    def test_real_calendar_day_strip_swipe_left_and_vertical_scroll(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
            try:
                context,page,rect=self.open_calendar(browser,"day")
                y=rect["y"]+rect["height"]/2
                self.drag(page,300,y,300,y+45)
                self.assertIn("date=2026-11-22",page.url,"Vertical scroll must not navigate weeks")
                self.drag(page,300,y,90,y)
                page.wait_for_url("**date=2026-11-29&cal_view=day*",timeout=8000)
                self.assertIn("date=2026-11-29",page.url)
                context.close()
            finally:
                browser.close()

    def test_real_calendar_week_strip_swipe_left(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
            try:
                context,page,rect=self.open_calendar(browser,"week")
                y=rect["y"]+rect["height"]/2
                self.drag(page,300,y,90,y)
                page.wait_for_url("**date=2026-11-23&cal_view=week*",timeout=8000)
                self.assertIn("date=2026-11-23",page.url)
                context.close()
            finally:
                browser.close()
