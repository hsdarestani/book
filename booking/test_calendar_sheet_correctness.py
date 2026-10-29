"""Calendar note/blocking is a booking rule, not a decorative UI switch."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from .doctor_views import _calendar_block
from .models import BlockedPeriod, StaffMember


TEST_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


@override_settings(STORAGES=TEST_STORAGES)
class CalendarNoteBlockingBehaviorTests(TestCase):
    def setUp(self):
        admin = get_user_model().objects.create_user(
            username='sheet-admin', password='secret', is_staff=True, is_superuser=True,
        )
        self.client.force_login(admin)
        session = self.client.session
        session['aplus_app_admin'] = True
        session.save()
        self.staff = StaffMember.objects.create(
            display_name='Doctor Sheet Regression', active=True, sort_order=1, role='doctor',
        )
        self.day = (timezone.localdate() + timedelta(days=2)).isoformat()

    def post_note(self, blocked):
        data = {
            'action': 'add_calendar_note',
            'staff_id': self.staff.pk,
            'note_date': self.day,
            'note_start': '10:00',
            'note_end': '10:15',
            'note_scope': 'staff',
            'note_text': 'UI regression test',
            'return_view': 'day',
            'return_date': self.day,
        }
        if blocked:
            data['note_blocked'] = 'on'
        response = self.client.post('/verwaltung/kalender/', data)
        self.assertEqual(response.status_code, 302)
        return BlockedPeriod.objects.get(staff=self.staff)

    def test_unblocked_note_does_not_reserve_time(self):
        item = self.post_note(False)
        self.assertTrue(item.reason.startswith('[NOTE]'))
        self.assertFalse(item.reason.startswith('[BLOCKNOTE]'))

    def test_checked_note_blocks_time_for_admin(self):
        item = self.post_note(True)
        self.assertTrue(item.reason.startswith('[BLOCKNOTE]'))

    def test_doctor_only_note_respects_checkbox(self):
        data = {
            'action': 'add_calendar_note',
            'note_date': self.day,
            'note_start': '10:00',
            'note_end': '10:15',
            'note_text': 'Doctor blocking',
            'note_blocked': 'on',
        }
        _calendar_block(self.staff, data)
        item = BlockedPeriod.objects.get(staff=self.staff)
        self.assertTrue(item.reason.startswith('[BLOCKNOTE][STAFF]'))

    def test_doctor_note_unchecked_is_not_blocked(self):
        data = {
            'action': 'add_calendar_note',
            'note_date': self.day,
            'note_start': '10:00',
            'note_end': '10:15',
            'note_text': 'Doctor nonblocking',
        }
        _calendar_block(self.staff, data)
        item = BlockedPeriod.objects.get(staff=self.staff)
        self.assertTrue(item.reason.startswith('[NOTE][STAFF]'))
