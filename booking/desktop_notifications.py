"""Admin-only read-only feed for newly signed clinic patient forms.

Browser notifications are intentionally generic; no health data is sent
to the desktop Notification API or stored in a browser-readable feed.
"""
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import PatientRecord


@never_cache
@staff_member_required(login_url='/verwaltung/login/')
@require_GET
def new_patient_forms(request):
    profile = getattr(request.user, 'aesthetic_access', None)
    if profile is not None and profile.view_only:
        return HttpResponseForbidden("Nur für Praxisadministratoren.")
    # A monotonic database id prevents missed submissions within one session.
    try:
        since = max(0, int(request.GET.get("after", "0")))
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "invalid_cursor"}, status=400)
    if since > 2**63 - 1:
        return JsonResponse({"ok": False, "error": "invalid_cursor"}, status=400)
    qs = PatientRecord.objects.filter(source='botoxbogen')
    if not since:
        latest = qs.order_by('-pk').values_list('pk', flat=True).first() or 0
        response = JsonResponse({"ok": True, "cursor": latest, "events": [],
                                 "user_id": request.user.pk})
    else:
        rows = list(qs.filter(pk__gt=since).order_by('pk')
                    .values('pk', 'customer_id')[:30])
        # Fixed copy; never expose names, addresses or diagnoses on lock screens.
        events = [{"id": row["pk"], "customer_id": row["customer_id"],
                   "title": "Neuer Patientenbogen eingegangen",
                   "body": "Ein ausgefüllter Patientenbogen ist verfügbar. Akte öffnen."}
                  for row in rows]
        response = JsonResponse({"ok": True, "cursor": rows[-1]["pk"] if rows else since,
                                 "events": events, "user_id": request.user.pk})
    response['Cache-Control'] = 'private, no-store, max-age=0'
    response['Pragma'] = 'no-cache'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
