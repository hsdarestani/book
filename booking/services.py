from datetime import datetime, timedelta
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .clinical_time import CLINIC_TZ, add_elapsed, clinic_localdate, clinic_wall_time
from .models import Appointment, BlockedPeriod, DailyAvailabilityOverride, StaffMember, WorkingHour

LEAD_TIME = timedelta(hours=1)
BOOKING_HORIZON_DAYS = 90


def effective_working_ranges(staff, day):
    """Return the effective availability ranges for one concrete date.

    A DailyAvailabilityOverride replaces the recurring weekday schedule for that
    one date. Without an override, the normal WorkingHour rows are used.
    """
    override = DailyAvailabilityOverride.objects.filter(staff=staff, date=day).first()
    if override:
        return override.ranges(), override
    hours = WorkingHour.objects.filter(
        staff=staff,
        weekday=day.weekday(),
        active=True,
    ).order_by('start_time')
    return [(item.start_time, item.end_time) for item in hours], None


def available_slots(service, staff, day, *, step_minutes=15, exclude_appointment_id=None, reserved_duration=None, source_availability=None, staff_booking=False):
    if not service.active or not service.bookable or not staff.active:
        return []
    if not staff.services.filter(pk=service.pk).exists():
        return []
    today = clinic_localdate()
    if day < today or (not staff_booking and day > today + timedelta(days=BOOKING_HORIZON_DAYS)):
        return []

    duration = service.reserved_duration if reserved_duration is None else reserved_duration
    day_start = datetime.combine(day, datetime.min.time(), tzinfo=CLINIC_TZ)
    day_end = day_start + timedelta(days=1)
    now_with_lead = timezone.now() + (timedelta(0) if staff_booking else LEAD_TIME)

    # Entries prefixed with [NOTE] are visual/admin calendar notes only and must
    # never make a public booking slot unavailable.
    blocked_periods = list(
        BlockedPeriod.objects.filter(staff=staff, starts_at__lt=day_end, ends_at__gt=day_start)
        .exclude(reason__startswith='[NOTE]')
        .values_list('starts_at', 'ends_at')
    )
    conflict_qs = Appointment.objects.filter(
        staff=staff,
        status__in=['new', 'confirmed'],
        starts_at__lt=day_end,
        ends_at__gt=day_start,
    )
    if exclude_appointment_id:
        conflict_qs = conflict_qs.exclude(public_id=exclude_appointment_id)
    conflicts = list(conflict_qs.values_list('starts_at', 'ends_at'))

    if source_availability is not None:
        starts, remote_blocks = source_availability
        conflicts += remote_blocks
        return [start for start in starts if start >= now_with_lead
                and clinic_localdate(add_elapsed(start, duration - timedelta(seconds=1))) == day
                and not any(a < add_elapsed(start, duration) and b > start
                            for a, b in blocked_periods + conflicts)]

    slots = []
    ranges, _override = effective_working_ranges(staff, day)
    step = timedelta(minutes=step_minutes)
    for start_time, end_time in ranges:
        cursor = datetime.combine(day, start_time)
        wall_end = datetime.combine(day, end_time)
        end_of_work = clinic_wall_time(wall_end)
        if end_of_work is None:
            continue
        # Keep the slot grid aligned to the clinic clock and measure the
        # reserve in elapsed minutes, including across offset changes.
        while cursor < wall_end:
            slot = clinic_wall_time(cursor)
            cursor += step
            if slot is None or slot < now_with_lead:
                continue
            slot_end = add_elapsed(slot, duration)
            if slot_end > end_of_work:
                break
            blocked = any(start < slot_end and end > slot for start, end in blocked_periods)
            conflict = any(start < slot_end and end > slot for start, end in conflicts)
            if not blocked and not conflict:
                slots.append(slot)
    return slots


def create_appointment(*, customer, service, staff, starts_at, message='', idempotency_key=None, source='web',
                       returning_customer=False, referral_source='', marketing_opt_in=True,
                       cancellation_terms_accepted=False, privacy_accepted=False,
                       returning_customer_answered=False, simplybook_sync_state='', source_availability=None):
    if idempotency_key:
        existing = Appointment.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing, False

    with transaction.atomic():
        locked_staff = StaffMember.objects.select_for_update().get(pk=staff.pk, active=True)
        local_day = clinic_localdate(starts_at)
        if starts_at not in available_slots(service, locked_staff, local_day, source_availability=source_availability):
            raise ValueError('time_not_available')
        appointment = Appointment(
            customer=customer,
            service=service,
            staff=locked_staff,
            starts_at=starts_at,
            ends_at=add_elapsed(starts_at, service.reserved_duration),
            treatment_minutes_at_booking=service.duration_minutes,
            status='new' if service.requires_confirmation or simplybook_sync_state else 'confirmed',
            source=source,
            notes_customer=message[:3000],
            returning_customer=bool(returning_customer),
            returning_customer_answered=returning_customer_answered,
            simplybook_sync_state=simplybook_sync_state,
            referral_source=(referral_source or '')[:100],
            marketing_opt_in=bool(marketing_opt_in),
            cancellation_terms_accepted=bool(cancellation_terms_accepted),
            privacy_accepted=bool(privacy_accepted),
            idempotency_key=idempotency_key or None,
        )
        appointment.full_clean()
        appointment.save()
    return appointment, True


def booking_source_availability(service, staff, day, end_day=None):
    """Fetch the vendor grid only for the active SimplyBook integration."""
    from .simplybook_outbound import SERVICE_MAP, integrated, public_availability_enabled, session, source_slots

    if not public_availability_enabled() or not integrated(service, staff):
        return None
    return source_slots(session(), SERVICE_MAP[service.slug][0], day.isoformat(), (end_day or day).isoformat())


def source_day(booked, day):
    if booked is None:
        return None
    days, blocked = booked
    return days.get(day.isoformat(), []), blocked


def prepare_staff_booking(appointment, *, request_key=None, defer_source_check=False):
    """Initialize a new staff reservation with the same source contract as public bookings."""
    from .simplybook_outbound import (
        SOURCE_AVAILABILITY_ERRORS, integrated, patient_booking_answers, public_sync_enabled,
    )

    if not integrated(appointment.service, appointment.staff):
        return
    if not public_sync_enabled():
        raise ValidationError('Die SimplyBook-Buchung ist für diesen Behandler momentan nicht verfügbar.')
    if not defer_source_check:
        day = clinic_localdate(appointment.starts_at)
        try:
            availability = source_day(booking_source_availability(appointment.service, appointment.staff, day), day)
        except SOURCE_AVAILABILITY_ERRORS as exc:
            raise ValidationError('Die SimplyBook-Verfügbarkeit kann gerade nicht geprüft werden.') from exc
        if availability is None or appointment.starts_at not in available_slots(
            appointment.service, appointment.staff, day, source_availability=availability, staff_booking=True,
        ):
            raise ValidationError('Dieser Zeitraum ist in SimplyBook nicht verfügbar.')
    appointment.returning_customer, appointment.referral_source = patient_booking_answers(appointment.customer)
    appointment.returning_customer_answered = True
    appointment.idempotency_key = request_key or f'staff-{uuid4()}'
    appointment.simplybook_sync_state = 'queued'
    appointment.status = 'new'
