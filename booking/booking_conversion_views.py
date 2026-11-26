"""Restricted first-party aggregate reporting view."""
from datetime import date, timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .management.commands.booking_conversion_report import BERLIN, aggregate_bookings
from .admin_dashboard_views import _is_view_only


@never_cache
@staff_member_required(login_url="/verwaltung/login/")
@require_GET
def booking_conversion_dashboard(request):
    if not request.user.is_superuser or _is_view_only(request.user) or getattr(request, "doctor_staff_scope", None) is not None:
        return HttpResponseForbidden("Nur für die Praxisleitung.")
    yesterday = timezone.now().astimezone(BERLIN).date() - timedelta(days=1)
    try:
        end = date.fromisoformat(request.GET["end"]) if request.GET.get("end") else yesterday
        start = date.fromisoformat(request.GET["start"]) if request.GET.get("start") else end - timedelta(days=27)
        report = aggregate_bookings(start, end)
    except (ValueError, OverflowError):
        return render(request, "booking/booking_conversion_dashboard.html", {
            "error": "Bitte einen gültigen Zeitraum von höchstens 366 Tagen auswählen.",
        }, status=400)
    labels = {"web": "Web", "app": "App", "admin": "Verwaltung", "imported": "Import", "other": "Sonstige"}
    rows = [{"label": labels[channel], **counts} for channel, counts in report["channels"].items()]
    return render(request, "booking/booking_conversion_dashboard.html", {"report": report, "rows": rows})
