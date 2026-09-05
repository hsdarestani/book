import json
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import (
    Appointment,
    BlockedPeriod,
    Customer,
    DailyAvailabilityOverride,
    PatientRecord,
    Service,
    StaffMember,
    WorkingHour,
)
from .services import effective_working_ranges

AESTHETIC_ADMIN_VERIFY_URL = "https://esthetic.smarbiz.sbs/api/mobile/admin/"


def _private(payload, status=200):
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Pragma"] = "no-cache"
    return response


def _json(request):
    try:
        value = json.loads(request.body.decode("utf-8")) if request.body else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _verify_admin(request):
    auth = str(request.headers.get("Authorization") or "").strip()
    if not auth.startswith("Bearer ") or len(auth) < 24:
        return None
    remote = Request(
        AESTHETIC_ADMIN_VERIFY_URL,
        headers={
            "Authorization": auth,
            "Accept": "application/json",
            "User-Agent": "A-Esthetic-Book-InApp-Admin/1.0",
        },
    )
    try:
        with urlopen(remote, timeout=12) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not payload.get("ok") or not payload.get("admin"):
        return None
    return payload["admin"]


def _require_admin(request):
    admin = _verify_admin(request)
    if not admin:
        return None, _private({"ok": False, "error": "admin_required"}, 403)
    return admin, None


def _day_bounds(day):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, datetime.min.time()), tz)
    return start, start + timedelta(days=1)


def _local_dt(day_value, time_value):
    day = parse_date(str(day_value or ""))
    clock = parse_time(str(time_value or ""))
    if not day or not clock:
        return None
    return timezone.make_aware(datetime.combine(day, clock), timezone.get_current_timezone())


def _is_quarter(value):
    return bool(value) and value.minute % 15 == 0


def _customer_payload(item, include_records=False):
    payload = {
        "id": item.pk,
        "name": item.full_name,
        "first_name": item.first_name,
        "last_name": item.last_name,
        "email": item.email,
        "phone": item.phone,
        "appointments": item.appointments.count(),
        "patient_records": item.patient_records.count(),
        "created_at": item.created_at.isoformat(),
    }
    if include_records:
        payload["records"] = [
            {
                "id": str(record.public_id),
                "kind": record.kind,
                "title": record.title,
                "note": record.note,
                "has_file": record.has_file,
                "shared_with_customer": bool((record.metadata or {}).get("shared_with_customer")),
                "source": record.source,
                "created_at": record.created_at.isoformat(),
            }
            for record in item.patient_records.all()[:100]
        ]
    return payload


def _appointment_payload(item):
    local_start = timezone.localtime(item.starts_at)
    local_end = timezone.localtime(item.ends_at)
    return {
        "id": item.pk,
        "public_id": str(item.public_id),
        "customer_id": item.customer_id,
        "customer_name": item.customer.full_name,
        "customer_email": item.customer.email,
        "customer_phone": item.customer.phone,
        "service_id": item.service_id,
        "service_name": item.service.name,
        "staff_id": item.staff_id,
        "staff_name": item.staff.display_name,
        "date": local_start.date().isoformat(),
        "start": local_start.strftime("%H:%M"),
        "end": local_end.strftime("%H:%M"),
        "status": item.status,
        "source": item.source,
        "notes_customer": item.notes_customer,
    }


def _block_payload(item):
    local_start = timezone.localtime(item.starts_at)
    local_end = timezone.localtime(item.ends_at)
    return {
        "id": item.pk,
        "staff_id": item.staff_id,
        "staff_name": item.staff.display_name,
        "date": local_start.date().isoformat(),
        "start": local_start.strftime("%H:%M"),
        "end": local_end.strftime("%H:%M"),
        "reason": item.reason,
        "note": str(item.reason or "").startswith("[NOTE]"),
    }


def _service_payload(item):
    return {
        "id": item.pk,
        "name": item.name,
        "slug": item.slug,
        "description": item.description,
        "duration_minutes": item.duration_minutes,
        "buffer_minutes": item.buffer_minutes,
        "price_label": item.price_label,
        "active": item.active,
        "bookable": item.bookable,
        "requires_confirmation": item.requires_confirmation,
        "sort_order": item.sort_order,
        "staff": list(item.staff_members.filter(active=True).values_list("display_name", flat=True)),
    }


def _staff_payload(item):
    hours = item.working_hours.filter(active=True).order_by("weekday", "start_time")
    return {
        "id": item.pk,
        "name": item.display_name,
        "role": item.role,
        "active": item.active,
        "services": list(item.services.filter(active=True).values("id", "name")),
        "working_hours": [
            {
                "id": row.pk,
                "weekday": row.weekday,
                "weekday_label": row.get_weekday_display(),
                "start": row.start_time.strftime("%H:%M"),
                "end": row.end_time.strftime("%H:%M"),
            }
            for row in hours
        ],
    }


@csrf_exempt
@require_http_methods(["GET"])
def overview(request):
    admin, error = _require_admin(request)
    if error:
        return error
    today = timezone.localdate()
    day_start, day_end = _day_bounds(today)
    today_qs = Appointment.objects.filter(starts_at__gte=day_start, starts_at__lt=day_end).select_related("customer", "service", "staff")
    upcoming = (
        Appointment.objects.filter(starts_at__gte=timezone.now())
        .exclude(status="cancelled")
        .select_related("customer", "service", "staff")
        .order_by("starts_at")[:12]
    )
    return _private({
        "ok": True,
        "admin": admin,
        "stats": {
            "today": today_qs.exclude(status="cancelled").count(),
            "new_today": today_qs.filter(status="new").count(),
            "customers": Customer.objects.count(),
            "active_services": Service.objects.filter(active=True).count(),
            "active_staff": StaffMember.objects.filter(active=True).count(),
        },
        "upcoming": [_appointment_payload(item) for item in upcoming],
    })


@csrf_exempt
@require_http_methods(["GET"])
def calendar(request):
    admin, error = _require_admin(request)
    if error:
        return error
    day = parse_date(request.GET.get("date") or "") or timezone.localdate()
    staff_qs = StaffMember.objects.filter(active=True).order_by("sort_order", "display_name")
    staff = staff_qs.filter(pk=request.GET.get("staff")).first() if request.GET.get("staff") else staff_qs.first()
    if not staff:
        return _private({"ok": True, "date": day.isoformat(), "staff": [], "appointments": [], "blocks": [], "ranges": []})
    start, end = _day_bounds(day)
    appointments = (
        Appointment.objects.filter(staff=staff, starts_at__lt=end, ends_at__gt=start)
        .select_related("customer", "service", "staff")
        .order_by("starts_at")
    )
    blocks = BlockedPeriod.objects.filter(staff=staff, starts_at__lt=end, ends_at__gt=start).select_related("staff").order_by("starts_at")
    ranges, override = effective_working_ranges(staff, day)
    return _private({
        "ok": True,
        "date": day.isoformat(),
        "selected_staff": staff.pk,
        "staff": [{"id": row.pk, "name": row.display_name} for row in staff_qs],
        "services": [_service_payload(item) for item in Service.objects.filter(active=True).order_by("sort_order", "name")],
        "customers": [{"id": item.pk, "name": item.full_name, "email": item.email} for item in Customer.objects.order_by("last_name", "first_name")[:1000]],
        "ranges": [{"start": start_time.strftime("%H:%M"), "end": end_time.strftime("%H:%M")} for start_time, end_time in ranges],
        "override": bool(override),
        "closed": bool(override.closed) if override else not bool(ranges),
        "appointments": [_appointment_payload(item) for item in appointments],
        "blocks": [_block_payload(item) for item in blocks],
    })


@csrf_exempt
@require_http_methods(["GET"])
def bookings(request):
    admin, error = _require_admin(request)
    if error:
        return error
    query = str(request.GET.get("q") or "").strip()
    status = str(request.GET.get("status") or "").strip()
    qs = Appointment.objects.select_related("customer", "service", "staff").order_by("-starts_at")
    if query:
        qs = qs.filter(
            Q(customer__first_name__icontains=query)
            | Q(customer__last_name__icontains=query)
            | Q(customer__email__icontains=query)
            | Q(customer__phone__icontains=query)
            | Q(service__name__icontains=query)
        )
    if status:
        qs = qs.filter(status=status)
    return _private({"ok": True, "bookings": [_appointment_payload(item) for item in qs[:250]]})


@csrf_exempt
@require_http_methods(["GET"])
def customers(request):
    admin, error = _require_admin(request)
    if error:
        return error
    query = str(request.GET.get("q") or "").strip()
    qs = Customer.objects.order_by("last_name", "first_name")
    if query:
        qs = qs.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(phone__icontains=query)
        )
    return _private({"ok": True, "customers": [_customer_payload(item) for item in qs[:250]]})


@csrf_exempt
@require_http_methods(["GET"])
def customer_detail(request, customer_id):
    admin, error = _require_admin(request)
    if error:
        return error
    item = Customer.objects.filter(pk=customer_id).first()
    if not item:
        return _private({"ok": False, "error": "customer_not_found"}, 404)
    appointments = item.appointments.select_related("customer", "service", "staff").order_by("-starts_at")[:100]
    return _private({
        "ok": True,
        "customer": _customer_payload(item, include_records=True),
        "appointments": [_appointment_payload(row) for row in appointments],
    })


@csrf_exempt
@require_http_methods(["GET"])
def services(request):
    admin, error = _require_admin(request)
    if error:
        return error
    return _private({"ok": True, "services": [_service_payload(item) for item in Service.objects.order_by("sort_order", "name")]})


@csrf_exempt
@require_http_methods(["GET"])
def settings(request):
    admin, error = _require_admin(request)
    if error:
        return error
    staff = StaffMember.objects.order_by("sort_order", "display_name")
    overrides = DailyAvailabilityOverride.objects.filter(date__gte=timezone.localdate()).select_related("staff").order_by("date")[:100]
    return _private({
        "ok": True,
        "staff": [_staff_payload(item) for item in staff],
        "upcoming_overrides": [
            {
                "id": item.pk,
                "staff_id": item.staff_id,
                "staff_name": item.staff.display_name,
                "date": item.date.isoformat(),
                "closed": item.closed,
                "ranges": [
                    {"start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")}
                    for start, end in item.ranges()
                ],
            }
            for item in overrides
        ],
    })


@csrf_exempt
@require_http_methods(["POST"])
def appointment_action(request, appointment_id):
    admin, error = _require_admin(request)
    if error:
        return error
    data = _json(request)
    item = Appointment.objects.select_related("customer", "service", "staff").filter(pk=appointment_id).first()
    if not item:
        return _private({"ok": False, "error": "appointment_not_found"}, 404)
    action = str(data.get("action") or "update")
    if action == "delete":
        item.delete()
        return _private({"ok": True, "deleted": True})

    status = str(data.get("status") or item.status)
    allowed_statuses = {value for value, _ in Appointment.STATUS}
    if status not in allowed_statuses:
        return _private({"ok": False, "error": "invalid_status"}, 400)
    service = Service.objects.filter(pk=data.get("service_id") or item.service_id).first()
    staff = StaffMember.objects.filter(pk=data.get("staff_id") or item.staff_id, active=True).first()
    customer = Customer.objects.filter(pk=data.get("customer_id") or item.customer_id).first()
    starts_at = _local_dt(data.get("date") or timezone.localtime(item.starts_at).date().isoformat(), data.get("time") or timezone.localtime(item.starts_at).strftime("%H:%M"))
    if not service or not staff or not customer or not starts_at or not _is_quarter(starts_at):
        return _private({"ok": False, "error": "invalid_appointment"}, 400)
    if not staff.services.filter(pk=service.pk).exists():
        return _private({"ok": False, "error": "service_not_assigned_to_staff"}, 409)
    ends_at = starts_at + timedelta(minutes=service.duration_minutes + service.buffer_minutes)
    item.service = service
    item.staff = staff
    item.customer = customer
    item.starts_at = starts_at
    item.ends_at = ends_at
    item.status = status
    try:
        item.full_clean()
        item.save()
    except ValidationError as exc:
        return _private({"ok": False, "error": "appointment_conflict", "message": "; ".join(exc.messages)}, 409)
    return _private({"ok": True, "appointment": _appointment_payload(item)})


@csrf_exempt
@require_http_methods(["POST"])
def block_action(request):
    admin, error = _require_admin(request)
    if error:
        return error
    data = _json(request)
    action = str(data.get("action") or "create")
    if action == "delete":
        BlockedPeriod.objects.filter(pk=data.get("id")).delete()
        return _private({"ok": True, "deleted": True})
    staff = StaffMember.objects.filter(pk=data.get("staff_id"), active=True).first()
    starts_at = _local_dt(data.get("date"), data.get("start"))
    ends_at = _local_dt(data.get("date"), data.get("end"))
    if not staff or not starts_at or not ends_at or ends_at <= starts_at or not _is_quarter(starts_at) or not _is_quarter(ends_at):
        return _private({"ok": False, "error": "invalid_block"}, 400)
    text = str(data.get("text") or ("Notiz" if data.get("kind") == "note" else "Gesperrt"))[:120]
    prefix = "[NOTE][STAFF]" if data.get("kind") == "note" else "[BLOCKNOTE][STAFF]"
    item = BlockedPeriod.objects.create(staff=staff, starts_at=starts_at, ends_at=ends_at, reason=f"{prefix} {text}"[:160])
    return _private({"ok": True, "block": _block_payload(item)})


@csrf_exempt
@require_http_methods(["POST"])
def service_action(request, service_id):
    admin, error = _require_admin(request)
    if error:
        return error
    data = _json(request)
    item = Service.objects.filter(pk=service_id).first()
    if not item:
        return _private({"ok": False, "error": "service_not_found"}, 404)
    for field in ("name", "description", "price_label"):
        if field in data:
            setattr(item, field, str(data[field] or "").strip())
    for field in ("active", "bookable", "requires_confirmation"):
        if field in data:
            setattr(item, field, bool(data[field]))
    for field in ("duration_minutes", "buffer_minutes", "sort_order"):
        if field in data:
            try:
                setattr(item, field, max(0, int(data[field])))
            except (TypeError, ValueError):
                return _private({"ok": False, "error": "invalid_service_value"}, 400)
    try:
        item.full_clean()
        item.save()
    except ValidationError as exc:
        return _private({"ok": False, "error": "invalid_service", "message": "; ".join(exc.messages)}, 400)
    return _private({"ok": True, "service": _service_payload(item)})


@csrf_exempt
@require_http_methods(["POST"])
def day_override_action(request):
    admin, error = _require_admin(request)
    if error:
        return error
    data = _json(request)
    staff = StaffMember.objects.filter(pk=data.get("staff_id"), active=True).first()
    day = parse_date(str(data.get("date") or ""))
    if not staff or not day:
        return _private({"ok": False, "error": "invalid_override"}, 400)
    if data.get("action") == "reset":
        DailyAvailabilityOverride.objects.filter(staff=staff, date=day).delete()
        return _private({"ok": True, "reset": True})
    closed = bool(data.get("closed"))
    ranges = data.get("ranges") if isinstance(data.get("ranges"), list) else []
    parsed = []
    for row in ranges[:2]:
        start = parse_time(str((row or {}).get("start") or ""))
        end = parse_time(str((row or {}).get("end") or ""))
        if not start or not end or not _is_quarter(start) or not _is_quarter(end):
            return _private({"ok": False, "error": "invalid_override_range"}, 400)
        parsed.append((start, end))
    if not closed and not parsed:
        return _private({"ok": False, "error": "override_range_required"}, 400)
    item, _ = DailyAvailabilityOverride.objects.get_or_create(staff=staff, date=day)
    item.closed = closed
    item.start_time_1 = item.end_time_1 = item.start_time_2 = item.end_time_2 = None
    if parsed:
        item.start_time_1, item.end_time_1 = parsed[0]
    if len(parsed) > 1:
        item.start_time_2, item.end_time_2 = parsed[1]
    try:
        item.full_clean()
        item.save()
    except ValidationError as exc:
        return _private({"ok": False, "error": "invalid_override", "message": "; ".join(exc.messages)}, 400)
    return _private({"ok": True, "saved": True})
