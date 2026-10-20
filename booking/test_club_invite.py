"""Checks for the optional public-web-only A+ Club download invitation."""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class BookingClubInviteTests(SimpleTestCase):
    def test_booking_page_has_hidden_club_invite_and_real_store_links(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('id="club-app-invite" hidden aria-hidden="true"', content)
        self.assertIn("https://apps.apple.com/de/app/a-esthetic/id6799468115", content)
        self.assertIn("https://play.google.com/store/apps/details?id=de.aplusesthetic.app", content)
        self.assertIn("Deine Termine und Buchungshistorie im Blick", content)
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
