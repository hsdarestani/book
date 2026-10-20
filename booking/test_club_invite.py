"""Checks for the optional public-web-only A+ Club download invitation."""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, override_settings


@override_settings(STORAGES={
    **settings.STORAGES,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class BookingClubInviteTests(SimpleTestCase):
    def test_booking_page_has_hidden_club_invite_and_real_store_links(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('id="club-app-invite" hidden aria-hidden="true"', content)
        self.assertIn("https://apps.apple.com/de/app/a-esthetic/id6799468115", content)
        self.assertIn("https://play.google.com/store/apps/details?id=de.aplusesthetic.app", content)
        self.assertIn("Deine Termine und bisherigen Buchungen im Blick", content)
        self.assertNotIn("MEMBERSHIP", content)
        self.assertNotIn("BEAUTY CLUB", content)
        self.assertNotIn("Rewards", content)
        self.assertNotIn("A+ Coins", content)
        self.assertNotIn("Beauty-Erfahrung", content)
        self.assertNotIn("unsere", content.split('id="club-app-invite"', 1)[1].split('</div>\n  <script', 1)[0].lower())

    def test_invitation_is_only_initialized_on_public_booking_host(self):
        root = Path(settings.BASE_DIR) / "static" / "booking"
        js = (root / "club-invite.js").read_text(encoding="utf-8")
        self.assertIn("window.location.hostname.toLowerCase() !== 'book.a-esthetic.de'", js)
        self.assertIn("window.self !== window.top", js)
        self.assertIn("window.Capacitor", js)
        self.assertIn("window.ReactNativeWebView", js)
        self.assertIn("navigator.standalone", js)
        self.assertIn("overlay.hidden = true", js)
        self.assertIn("window.localStorage", js)

    def test_logo_typography_uses_ms_madi(self):
        root = Path(settings.BASE_DIR) / "static" / "booking"
        css = (root / "club-invite.css").read_text(encoding="utf-8")
        html = (Path(settings.BASE_DIR) / "templates" / "booking" / "_club_invite.html").read_text(encoding="utf-8")
        self.assertIn("family=Ms+Madi", css)
        self.assertIn('font-family:"Ms Madi"', css)
        self.assertIn('class="club-invite__signature"', html)
        self.assertIn('class="club-invite__emblem"', html)
