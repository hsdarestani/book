from datetime import timedelta
from unittest.mock import patch

from django.core.management.base import CommandError
from django.test import TestCase

from .clinical_time import clinic_localdate, parse_clinic_wall_time
from .models import BlockedPeriod, ExternalSyncState, StaffMember
from .simplybook_calendar import ACTION_ID_BASE, WRITE_STATE, CalendarSourceConflict, mutate_note
from .simplybook_outbound import ARIANE


@patch.dict('os.environ', {'SIMPLYBOOK_CALENDAR_WRITEBACK_ENABLED': '1'})
class SimplyBookCalendarWritebackTests(TestCase):
    def setUp(self):
        self.staff = StaffMember.objects.create(display_name=ARIANE, active=True)
        day = (clinic_localdate() + timedelta(days=3)).isoformat()
        self.start = parse_clinic_wall_time(day, '15:00')
        self.end = parse_clinic_wall_time(day, '15:15')
        self.remote = None
        self.writes = []

    def source(self, path='', *, method='GET', payload=None):
        if path == '/types/default':
            return {'id': 1}
        if path.startswith('?'):
            return {'data': [self.remote] if self.remote else [], 'metadata': {'pages_count': 1}}
        if method in {'POST', 'PUT'}:
            self.writes.append(method)
            self.remote = dict(payload, id=80)
            return self.remote
        if method == 'DELETE':
            self.writes.append(method)
            self.remote = None
            return {}
        if not self.remote:
            raise CommandError('SimplyBook notes HTTP 404')
        return self.remote

    def create(self):
        return mutate_note(self.staff.pk, 'create', start=self.start, end=self.end, text='Synthetic test')

    @patch('booking.simplybook_calendar._check_bookings')
    def test_source_first_lifecycle_rejects_stale_native_id_and_preserves_block_identity(self, reservations):
        with patch('booking.simplybook_calendar._notes_session', return_value=self.source):
            block_id, action_id = self.create()
            self.assertEqual(self.create(), (block_id, action_id))
            _, edited_id = mutate_note(self.staff.pk, 'update', revision_id=action_id - ACTION_ID_BASE,
                                       start=self.start, end=self.end, text='Changed', blocked=True)
            with self.assertRaises(CalendarSourceConflict):
                mutate_note(self.staff.pk, 'delete', revision_id=action_id - ACTION_ID_BASE)
            self.assertEqual(BlockedPeriod.objects.get(staff=self.staff).pk, block_id)
            mutate_note(self.staff.pk, 'delete', revision_id=edited_id - ACTION_ID_BASE)
            self.assertFalse(BlockedPeriod.objects.filter(staff=self.staff).exists())
        reservations.assert_called_once()
        self.assertEqual(self.writes, ['POST', 'PUT', 'DELETE'])

    def test_remote_change_is_rejected_before_mutation(self):
        with patch('booking.simplybook_calendar._notes_session', return_value=self.source):
            _, action_id = self.create()
            self.remote['note'] = 'External edit'
            with self.assertRaises(CalendarSourceConflict):
                mutate_note(self.staff.pk, 'delete', revision_id=action_id - ACTION_ID_BASE)
            self.assertEqual(self.writes, ['POST'])
            self.assertEqual(ExternalSyncState.objects.get(source=WRITE_STATE).metadata, {})

    def test_uncertain_write_blocks_replay_even_with_new_request(self):
        def timeout(path='', **kwargs):
            if kwargs.get('method') == 'POST':
                self.source(path, **kwargs)
                raise TimeoutError
            return self.source(path, **kwargs)

        with patch('booking.simplybook_calendar._notes_session', return_value=timeout):
            with self.assertRaises(CalendarSourceConflict):
                self.create()
            with self.assertRaises(CalendarSourceConflict):
                self.create()
        self.assertEqual(self.writes, ['POST'])
        self.assertTrue(ExternalSyncState.objects.get(source=WRITE_STATE).metadata['pending'])
        self.assertFalse(BlockedPeriod.objects.filter(staff=self.staff).exists())
