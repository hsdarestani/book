from datetime import datetime, timedelta
from django.db import transaction
from django.utils import timezone
from .models import Appointment, BlockedPeriod, StaffMember, WorkingHour

LEAD_TIME = timedelta(hours=1)
BOOKING_HORIZON_DAYS = 90


def available_slots(service, staff, day, *, step_minutes=15):
    if not service.active or not service.bookable or not staff.active:
        return []
    if not staff.services.filter(pk=service.pk).exists():
        return []
    today = timezone.localdate()
    if day < today or day > today + timedelta(days=BOOKING_HORIZON_DAYS):
        return []

    duration = timedelta(minutes=service.duration_minutes + service.buffer_minutes)
    tz = timezone.get_current_timezone()
    slots = []
    hours = WorkingHour.objects.filter(staff=staff, weekday=day.weekday(), active=True).order_by('start_time')
    for working in hours:
        cursor = timezone.make_aware(datetime.combine(day, working.start_time), tz)
        end_of_work = timezone.make_aware(datetime.combine(day, working.end_time), tz)
        while cursor + duration <= end_of_work:
            slot_end = cursor + duration
            if cursor >= timezone.now() + LEAD_TIME:
                blocked = BlockedPeriod.objects.filter(staff=staff, starts_at__lt=slot_end, ends_at__gt=cursor).exists()
                conflict = Appointment.objects.filter(
                    staff=staff,
                    status__in=['new', 'confirmed'],
                    starts_at__lt=slot_end,
                    ends_at__gt=cursor,
                ).exists()
                if not blocked and not conflict:
                    slots.append(cursor)
            cursor += timedelta(minutes=step_minutes)
    return slots


def create_appointment(*, customer, service, staff, starts_at, message='', idempotency_key=None, source='web'):
    if idempotency_key:
        existing = Appointment.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing, False

    duration = timedelta(minutes=service.duration_minutes + service.buffer_minutes)
    with transaction.atomic():
        locked_staff = StaffMember.objects.select_for_update().get(pk=staff.pk, active=True)
        local_day = starts_at.astimezone(timezone.get_current_timezone()).date()
        if starts_at not in available_slots(service, locked_staff, local_day):
            raise ValueError('time_not_available')
        appointment = Appointment(
            customer=customer,
            service=service,
            staff=locked_staff,
            starts_at=starts_at,
            ends_at=starts_at + duration,
            status='new' if service.requires_confirmation else 'confirmed',
            source=source,
            notes_customer=message[:3000],
            idempotency_key=idempotency_key or None,
        )
        appointment.full_clean()
        appointment.save()
    return appointment, True
