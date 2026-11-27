from types import SimpleNamespace
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from booking.management.commands.audit_simplybook_editability import (
    appointment_reason, calendar_index, http_status, note_source_id,
)
from booking.management.commands.sync_simplybook_notes import _marker
from booking.simplybook_outbound import ARIANE


class ExistingEditabilityAuditTests(SimpleTestCase):
    def test_legacy_id_fallback_does_not_override_review_state(self):
        appointment = SimpleNamespace(staff=SimpleNamespace(display_name=ARIANE, active=True),
                                      simplybook_booking_id=None, idempotency_key='simplybook-123',
                                      status='confirmed', simplybook_sync_state='review')
        self.assertEqual(appointment_reason(appointment), 'source_sync_not_ready')
        appointment.simplybook_sync_state = ''
        self.assertIsNone(appointment_reason(appointment))
        appointment.idempotency_key = 'simplybook-invalid'
        self.assertEqual(appointment_reason(appointment), 'source_booking_id_missing')

    def test_versioned_note_actions_are_joined_by_local_record_id(self):
        payload = {'blocks': [{'id': (1 << 50) + 456, 'record_id': 12, 'editable': True},
                              {'id': 15, 'record_id': 15, 'editable': False}]}
        indexed = calendar_index(payload, 'block')
        self.assertEqual(http_status(indexed[12], 'block'), 'editable')
        self.assertEqual(http_status(indexed[15], 'block'), 'read_only')
        self.assertEqual(http_status(indexed.get(19), 'block'), 'not_returned')

    def test_missing_field_is_not_treated_as_success(self):
        self.assertEqual(http_status({'id': 1}, 'appointment'), 'missing_eligibility')
        with self.assertRaises(CommandError):
            calendar_index({'appointments': [{'id': 1}, {'id': 1}]}, 'appointment')

    def test_legacy_note_marker_can_be_read_without_revision(self):
        note = SimpleNamespace(reason='[NOTE][STAFF] Synthetic' + _marker(42), simplybook_managed=True)
        self.assertEqual(note_source_id(note), 42)
        note.simplybook_managed = False
        self.assertIsNone(note_source_id(note))
