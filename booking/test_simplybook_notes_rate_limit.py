from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from .models import ExternalSyncState


class SimplyBookNotesRateLimitTests(TestCase):
    def setUp(self):
        self.state = ExternalSyncState.objects.create(
            source="simplybook", baseline_completed_at=timezone.now(),
        )

    @patch("booking.management.commands.sync_simplybook_continuous.snapshots", return_value={})
    @patch("booking.management.commands.sync_simplybook_continuous.call_command")
    def test_retryable_notes_limit_does_not_block_booking_sync(self, nested, snapshots):
        def fake(command, *args, **kwargs):
            if command == "sync_simplybook_notes":
                raise CommandError('SimplyBook notes HTTP 403: {"message":"Too many attempts please try later."}')
        nested.side_effect = fake
        call_command("sync_simplybook_continuous", stdout=StringIO(), stderr=StringIO())
        self.state.refresh_from_db()
        self.assertIsNotNone(self.state.last_success_at)
        self.assertEqual(self.state.metadata.get("last_notes_status"), "rate_limited")
        nested.assert_any_call("simplybook_import", strict=True)

    @patch("booking.management.commands.sync_simplybook_continuous.snapshots", return_value={})
    @patch("booking.management.commands.sync_simplybook_continuous.call_command")
    def test_other_notes_errors_still_fail_loudly(self, nested, snapshots):
        def fake(command, *args, **kwargs):
            if command == "sync_simplybook_notes":
                raise CommandError("SimplyBook notes HTTP 401: Invalid credentials")
        nested.side_effect = fake
        with self.assertRaises(CommandError):
            call_command("sync_simplybook_continuous", stdout=StringIO())
        self.state.refresh_from_db()
        self.assertIsNone(self.state.last_success_at)
