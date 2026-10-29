"""Browser-level regression for the actual management templates, not CSS source strings."""
import importlib.util
import re
import time
import unittest
from pathlib import Path
from urllib.parse import urlparse
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import StaffMember, Service

ROOT = Path(__file__).resolve().parent.parent

@unittest.skipUnless(importlib.util.find_spec("playwright"), "requires Chromium browser CI")
@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class ManagementMobileBrowserTests(TestCase):
    def setUp(self):
        admin = get_user_model().objects.create_user(
            username="mobile-browser-admin", password="test-password",
            is_staff=True, is_superuser=True,
        )
        self.client.force_login(admin)
        session = self.client.session
        session["aplus_app_admin"] = True
        session["aplus_admin_authorization"] = "Bearer test-browser"
        session.save()
        self.staff = StaffMember.objects.create(
            display_name="Browser Test Doctor", active=True, sort_order=1, role="doctor",
        )

    def _html_with_styles(self, response, calendar=False):
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        collected = []
        pattern = re.compile(r'<link\b[^>]*rel="stylesheet"[^>]*>|<style[^>]*>.*?</style>', re.I | re.S)
        for match in pattern.finditer(html):
            tag = match.group(0)
            if tag.lower().startswith("<style"):
                collected.append(re.sub(r"^<style[^>]*>|</style>$", "", tag, flags=re.I | re.S))
                continue
            href = re.search(r'href="([^"]+)"', tag)
            if not href: continue
            path = urlparse(href.group(1)).path
            if not path.startswith("/static/"): continue
            item = finders.find(path[len("/static/"):])
            self.assertTrue(item, path)
            collected.append(Path(item).read_text(encoding="utf-8"))
        html = pattern.sub("", html)
        html = re.sub(r'<script\b[^>]*>.*?</script>', "", html, flags=re.I | re.S)
        html = re.sub(r'(<img[^>]*?)\s+src="[^"]+"', r"\1", html, flags=re.I)
        if calendar:
            # These are loaded by admin.js after the initial template response.
            # The last scroll stylesheet is intentionally injected last.
            css_names = ["admin-simply.css", "admin-calendar-plus.css",
                         "admin-calendar-mobile-v2.css", "admin-calendar-iphone-v1.css",
                         "admin-calendar-reference-v2.css", "admin-calendar-sheet-fix-v3.css",
                         "admin-calendar-mobile-finish-v4.css", "admin-calendar-scroll-v5.css",
                         "admin-calendar-date-dock-v6.css","admin-calendar-view-modes-v1.css",
                         "admin-calendar-horizontal-v2.css"]
            for name in css_names:
                item = finders.find("booking/"+name)
                self.assertTrue(item, name)
                collected.append(Path(item).read_text(encoding="utf-8"))
        return html, collected

    def _page(self, browser, html, styles, *, calendar=False):
        context = browser.new_context(
            viewport={"width":390,"height":820}, is_mobile=True,
            has_touch=True, device_scale_factor=2,
        )
        page = context.new_page()
        page.set_content(html, wait_until="domcontentloaded")
        if calendar:
            page.evaluate("document.body.classList.add('sb-calendar-pro')")
        for style in styles:
            page.add_style_tag(content=style)
        if calendar:
            page.add_script_tag(content=Path(
                finders.find("booking/admin-calendar-iphone-v1.js")
            ).read_text(encoding="utf-8"))
        return context, page

    def test_server_html_shows_correct_calendar_before_javascript(self):
        response=self.client.get('/verwaltung/kalender/', {'staff':self.staff.pk})
        self.assertEqual(response.status_code,200)
        html,styles=self._html_with_styles(response,calendar=True)
        self.assertIn('sb-calendar-pro sb-calendar-booting', html)
        self.assertIn('sb-reference-date-preview',html)
        self.assertIn('admin-calendar-date-dock-v6.css',response.content.decode())
        with __import__('playwright.sync_api',fromlist=['sync_playwright']).sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
            try:
                context=browser.new_context(viewport={'width':390,'height':820},is_mobile=True,has_touch=True)
                page=context.new_page()
                page.set_content(html)
                for style in styles: page.add_style_tag(content=style)
                self.assertEqual(page.locator('.sb-reference-date-preview .sb-iphone-day').count(),7)
                self.assertTrue(page.locator('.sb-reference-date-preview').is_visible())
                self.assertFalse(page.locator('main.sb-admin-shell .sb-date-nav').is_visible())
                self.assertEqual(page.locator('body.sb-calendar-pro').count(),1)
                context.close()
            finally: browser.close()

    def test_android_swipe_reaches_late_calendar_hours(self):
        from playwright.sync_api import sync_playwright
        date = timezone.localdate().isoformat()
        response = self.client.get("/verwaltung/kalender/", {
            "date":date, "staff":self.staff.pk,
        })
        html, styles = self._html_with_styles(response, calendar=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                context, page = self._page(browser, html, styles, calendar=True)
                self.assertTrue(page.locator(".sb-calendar-shell.is-day").count())
                self.assertEqual(page.locator("body.sb-calendar-booting").count(),0)
                page.wait_for_timeout(120)
                self.assertEqual(page.evaluate("document.querySelector('main.sb-admin-shell').scrollTop"),0)
                first_label = page.locator(".sb-time-axis span").first
                self.assertEqual(first_label.text_content().strip(),"10:00")

                dock=page.locator(".sb-reference-date-dock")
                # Browser regression from the 19:36 phone screenshot: scrollTop=0
                # was passing despite a fully obscured 10:00 hour behind
                # the fixed month/week dock. Test visual geometry instead.
                geometry=page.evaluate("""() => {
                    const box=s=>document.querySelector(s)?.getBoundingClientRect();
                    const dock=box('.sb-reference-date-dock');
                    const spacer=box('.sb-calendar-dock-space');
                    const head=box('.sb-calendar-shell.is-day .sb-day-head');
                    const track=box('.sb-calendar-shell.is-day .sb-day-track');
                    const first=box('.sb-time-axis span');
                    return {
                      dockBottom:dock?.bottom, spacerHeight:spacer?.height,
                      headTop:head?.top, trackTop:track?.top,
                      firstTop:first?.top, viewport:innerHeight,
                      scroll:document.querySelector('main.sb-admin-shell')?.scrollTop
                    };
                }""")
                self.assertEqual(geometry['scroll'],0,geometry)
                self.assertAlmostEqual(geometry['spacerHeight'],150,delta=2,msg=str(geometry))
                self.assertGreaterEqual(geometry['headTop'],geometry['dockBottom']-2,geometry)
                self.assertGreater(geometry['trackTop'],geometry['dockBottom']+25,geometry)
                self.assertLess(geometry['trackTop'],geometry['viewport']-15,geometry)
                self.assertGreaterEqual(geometry['firstTop'],geometry['dockBottom']-7,geometry)

                self.assertEqual(dock.count(),1)
                self.assertEqual(dock.locator(".sb-iphone-day").count(),7)
                fixed_before=dock.evaluate("""node=>({
                  y:node.getBoundingClientRect().top,
                  position:getComputedStyle(node).position,
                  month:node.querySelector('.sb-iphone-month-button')?.textContent
                })""")
                self.assertEqual(fixed_before['position'],'fixed', fixed_before)
                self.assertGreaterEqual(fixed_before['y'],60)
                self.assertLess(fixed_before['y'],70)
                self.assertTrue(fixed_before['month'])
                before = page.evaluate("""() => {
                    const m=document.querySelector('main.sb-admin-shell');
                    return {y:m.scrollTop, height:m.scrollHeight, client:m.clientHeight,
                            overflow:getComputedStyle(m).overflowY};
                }""")
                self.assertGreater(before["height"], before["client"]+300, before)
                self.assertIn(before["overflow"], ("scroll","auto"), before)
                page.mouse.move(220, 640)
                page.mouse.wheel(0, 680)
                page.wait_for_timeout(200)
                self.assertGreater(page.evaluate("document.querySelector('main.sb-admin-shell').scrollTop"), 70)
                # Browser/WebView may restore a former day's scroll offset.
                # The first view after pageshow must return to working start.
                page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))")
                page.wait_for_timeout(90)
                self.assertEqual(page.evaluate("document.querySelector('main.sb-admin-shell').scrollTop"),0)
                page.mouse.wheel(0, 680)
                page.wait_for_timeout(100)
                self.assertGreater(page.evaluate("document.querySelector('main.sb-admin-shell').scrollTop"),70)
                self.assertLess(abs(dock.evaluate("el=>el.getBoundingClientRect().top")-fixed_before['y']),2)
                self.assertTrue(dock.locator(".sb-iphone-month-button").is_visible())
                self.assertTrue(dock.locator(".sb-iphone-day").first.is_visible())
                page.evaluate("document.querySelector('main.sb-admin-shell').scrollTop=0")
                # Touch on an appointment card/time track must not deadlock scrolling.
                session=context.new_cdp_session(page)
                session.send("Input.dispatchTouchEvent",{
                    "type":"touchStart","touchPoints":[{"x":210,"y":680,"id":1}]
                })
                for y in range(660,200,-20):
                    session.send("Input.dispatchTouchEvent",{
                        "type":"touchMove","touchPoints":[{"x":210,"y":y,"id":1}]
                    })
                    time.sleep(.011)
                session.send("Input.dispatchTouchEvent",{
                    "type":"touchEnd","touchPoints":[]
                })
                page.wait_for_timeout(220)
                self.assertGreater(
                    page.evaluate("document.querySelector('main.sb-admin-shell').scrollTop"),
                    60, "Android finger gesture did not move the calendar scrollport"
                )
                self.assertLess(abs(dock.evaluate("el=>el.getBoundingClientRect().top")-fixed_before['y']),2,
                                "The calendar month/week navigation scrolled off-screen")
                context.close()
            finally:
                browser.close()

    def test_native_horizontal_swipe_on_week_provider_and_service_columns(self):
        """Real Android touch gestures must scroll columns, not just match CSS text."""
        from playwright.sync_api import sync_playwright
        day=timezone.localdate().isoformat()
        # Guarantee at least 3 columns in provider and service views even
        # when the base fixture contains only one clinician.
        for i in range(3):
            member=StaffMember.objects.create(
                display_name=f'Horizontal Physician {i}', role='doctor',
                active=True, sort_order=90+i,
            )
            service=Service.objects.create(
                name=f'Horizontal Service {i}', slug=f'horizontal-service-{i}',
                active=True, sort_order=90+i,
            )
            self.staff.services.add(service)
        sources=[]
        for mode in ("week","provider","service"):
            response=self.client.get("/verwaltung/kalender/",{
                "date":day,"staff":self.staff.pk,"cal_view":mode,
            })
            html,styles=self._html_with_styles(response,calendar=True)
            sources.append((mode,html,styles))
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
            try:
                for mode,html,styles in sources:
                    with self.subTest(mode=mode):
                        context,page=self._page(browser,html,styles,calendar=True)
                        page.wait_for_timeout(100)
                        shell=page.locator(".sb-calendar-shell.is-week")
                        viewport=page.locator(".sb-horizontal-track-viewport")
                        self.assertEqual(shell.count(),1)
                        self.assertEqual(viewport.count(),1)
                        geom=viewport.evaluate("""el=>{
                            const head=el.querySelector('.sb-day-head');
                            const track=el.querySelector('.sb-day-track');
                            const h=head?.getBoundingClientRect();
                            const t=track?.getBoundingClientRect();
                            const css=getComputedStyle(el);
                            return {width:el.clientWidth,
                                    scrollWidth:el.scrollWidth,
                                    left:el.scrollLeft,
                                    touch:css.touchAction,
                                    overflowX:css.overflowX,
                                    headTop:h?.top,headBottom:h?.bottom,
                                    trackTop:t?.top};
                        }""")
                        self.assertGreater(geom["scrollWidth"],geom["width"]+90,geom)
                        self.assertEqual(geom["overflowX"],"auto",geom)
                        self.assertIn(geom["touch"],("auto","pan-x pan-y","pan-y pan-x"),geom)
                        self.assertLessEqual(geom["headBottom"],geom["trackTop"]+2,geom)
                        self.assertLess(geom["headTop"],geom["trackTop"],geom)
                        # Horizontal wheel should only move the columns,
                        # leaving the time labels in the fixed first grid cell.
                        axis_x=page.locator(".sb-calendar-shell.is-week > .sb-time-axis").evaluate(
                            "el=>el.getBoundingClientRect().left")
                        page.mouse.move(300,610)
                        page.mouse.wheel(470,0)
                        page.wait_for_timeout(150)
                        self.assertGreater(viewport.evaluate("el=>el.scrollLeft"),65,
                            "Horizontal wheel did not move "+mode)
                        axis_after=page.locator(".sb-calendar-shell.is-week > .sb-time-axis").evaluate(
                            "el=>el.getBoundingClientRect().left")
                        self.assertLess(abs(axis_after-axis_x),2)
                        viewport.evaluate("el=>el.scrollLeft=0")
                        page.wait_for_timeout(80)
                        # CDP touch on the appointment/working segment, the same
                        # input that got stuck in the user's Android WebView.
                        session=context.new_cdp_session(page)
                        session.send("Input.dispatchTouchEvent",{
                            "type":"touchStart","touchPoints":[{"x":327,"y":615,"id":1}]})
                        for x in range(311,95,-18):
                            session.send("Input.dispatchTouchEvent",{
                                "type":"touchMove","touchPoints":[{"x":x,"y":615,"id":1}]})
                            time.sleep(.012)
                        session.send("Input.dispatchTouchEvent",{
                            "type":"touchEnd","touchPoints":[]})
                        page.wait_for_timeout(250)
                        self.assertGreater(viewport.evaluate("el=>el.scrollLeft"),50,
                            "Actual Android finger swipe was blocked in "+mode)
                        context.close()
            finally:
                browser.close()

    @patch("booking.app_management_views._api")
    def test_points_and_patient_emerald_hero_is_visible_in_chromium(self, api):
        api.return_value = {"ok":True, "customers":[]}
        # Fetch Django responses before Playwright starts its event loop:
        # synchronous ORM access inside its context is prohibited by Django.
        sources = []
        for path, selector in (
            ("/verwaltung/app/wallet/", ".points-admin-hero"),
            ("/verwaltung/app/patients/", ".premium-list-heading"),
        ):
            response = self.client.get(path)
            html, styles = self._html_with_styles(response)
            sources.append((path, selector, html, styles))
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
            try:
                for path, selector, html, styles in sources:
                    with self.subTest(path=path):
                        context,page=self._page(browser,html,styles)
                        hero=page.locator(selector).first
                        self.assertTrue(hero.is_visible())
                        computed=hero.evaluate("""el => ({
                            image:getComputedStyle(el).backgroundImage,
                            box:el.getBoundingClientRect().toJSON()
                        })""")
                        self.assertIn("rgb(16, 39, 29)",computed["image"],computed)
                        if path.endswith("/patients/"):
                            panel=page.locator(".premium-customer-panel").first
                            inset=page.evaluate("""() => {
                                let p=document.querySelector('.premium-customer-panel').getBoundingClientRect();
                                let h=document.querySelector('.premium-list-heading').getBoundingClientRect();
                                return {left:Math.abs(p.left-h.left),right:Math.abs(p.right-h.right)}
                            }""")
                            self.assertLess(inset["left"],3,inset)
                            self.assertLess(inset["right"],3,inset)
                        context.close()
            finally:
                browser.close()
