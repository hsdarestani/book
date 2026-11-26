from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime, parse_time

CLINIC_TZ = ZoneInfo('Europe/Berlin')


def clinic_localtime(value=None):
    return timezone.localtime(value, CLINIC_TZ)


def clinic_localdate(value=None):
    return clinic_localtime(value).date()


def clinic_wall_time(wall_time):
    """Return a Berlin time only when the wall clock identifies one instant."""
    first = wall_time.replace(tzinfo=CLINIC_TZ, fold=0)
    second = wall_time.replace(tzinfo=CLINIC_TZ, fold=1)
    if first.utcoffset() != second.utcoffset():
        return None
    return first


def parse_clinic_wall_time(day, clock):
    try:
        parsed_day = parse_date(str(day or ''))
        parsed_time = parse_time(str(clock or ''))
    except ValueError:
        return None
    if parsed_day is None or parsed_time is None:
        return None
    return clinic_wall_time(datetime.combine(parsed_day, parsed_time))


def parse_appointment_start(value):
    try:
        parsed = parse_datetime(str(value or ''))
    except ValueError:
        return None
    if parsed is None or timezone.is_aware(parsed):
        return parsed
    return clinic_wall_time(parsed)


def add_elapsed(start, duration):
    return start.astimezone(UTC) + duration
