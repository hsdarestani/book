from datetime import datetime, timedelta
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


def available_slots(service, staff, day, *, step_minutes=15, exclude_appointment_id=None, reserved_duration=None):
    if not service.active or not service.bookable or not staff.active:
        return []
    if not staff.services.filter(pk=service.pk).exists():
        return []
    today = clinic_localdate()
    if day < today or day > today + timedelta(days=BOOKING_HORIZON_DAYS):
        return []

    duration = service.reserved_duration if reserved_duration is None else reserved_duration
    day_start = datetime.combine(day, datetime.min.time(), tzinfo=CLINIC_TZ)
    day_end = day_start + timedelta(days=1)
    now_with_lead = timezone.now() + LEAD_TIME

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
                       cancellation_terms_accepted=False, privacy_accepted=False):
    if idempotency_key:
        existing = Appointment.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing, False

    with transaction.atomic():
        locked_staff = StaffMember.objects.select_for_update().get(pk=staff.pk, active=True)
        local_day = clinic_localdate(starts_at)
        if starts_at not in available_slots(service, locked_staff, local_day):
            raise ValueError('time_not_available')
        appointment = Appointment(
            customer=customer,
            service=service,
            staff=locked_staff,
            starts_at=starts_at,
            ends_at=add_elapsed(starts_at, service.reserved_duration),
            treatment_minutes_at_booking=service.duration_minutes,
            status='new' if service.requires_confirmation else 'confirmed',
            source=source,
            notes_customer=message[:3000],
            returning_customer=bool(returning_customer),
            referral_source=(referral_source or '')[:100],
            marketing_opt_in=bool(marketing_opt_in),
            cancellation_terms_accepted=bool(cancellation_terms_accepted),
            privacy_accepted=bool(privacy_accepted),
            idempotency_key=idempotency_key or None,
        )
        appointment.full_clean()
        appointment.save()
    return appointment, True
