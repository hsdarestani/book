"""Temporarily block all online appointments for Qamar Hameed through 2026.

This is one staff-specific absence record, not a change to recurring working hours,
the other clinician's schedule, or previously created appointments. The exclusive
end boundary reopens availability on 2027-01-01 (subject to normal rules).
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from django.db import migrations


BERLIN = ZoneInfo('Europe/Berlin')
STARTS_AT = datetime(2026, 11, 20, 0, 0, tzinfo=BERLIN)
ENDS_AT = datetime(2027, 1, 1, 0, 0, tzinfo=BERLIN)
REASON = '[BLOCKNOTE][STAFF] Keine Online-Termine bis 31.12.2026'


def block_qamar_until_2027(apps, schema_editor):
    Staff = apps.get_model('booking', 'StaffMember')
    BlockedPeriod = apps.get_model('booking', 'BlockedPeriod')
    database = schema_editor.connection.alias

    doctors = list(
        Staff.objects.using(database)
        .filter(display_name__iexact='Qamar Hameed', role='doctor')
        .values_list('pk', flat=True)
    )
    if len(doctors) != 1:
        raise RuntimeError(
            'Expected exactly one doctor named Qamar Hameed; '
            'refusing to change any other provider availability.'
        )

    BlockedPeriod.objects.using(database).get_or_create(
        staff_id=doctors[0],
        starts_at=STARTS_AT,
        ends_at=ENDS_AT,
        reason=REASON,
    )


def unblock_qamar_on_rollback(apps, schema_editor):
    Staff = apps.get_model('booking', 'StaffMember')
    BlockedPeriod = apps.get_model('booking', 'BlockedPeriod')
    database = schema_editor.connection.alias
    qamar_ids = list(
        Staff.objects.using(database)
        .filter(display_name__iexact='Qamar Hameed', role='doctor')
        .values_list('pk', flat=True)
    )
    if len(qamar_ids) == 1:
        BlockedPeriod.objects.using(database).filter(
            staff_id=qamar_ids[0],
            starts_at=STARTS_AT,
            ends_at=ENDS_AT,
            reason=REASON,
        ).delete()


class Migration(migrations.Migration):
    dependencies = [('booking', '0024_patient_identity_decision')]

    operations = [
        migrations.RunPython(block_qamar_until_2027, unblock_qamar_on_rollback),
    ]
