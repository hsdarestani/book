import base64

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from . import app_management_views
from .admin_dashboard_views import _is_view_only
from .models import WhatsAppTemplate


@never_cache
@staff_member_required(login_url="/verwaltung/login/")
@require_http_methods(["GET", "POST"])
def admin_more(request):
    view_only = _is_view_only(request.user)
    error = ""

    if request.method == "POST":
        if view_only:
            return HttpResponseForbidden(
                "Dieser Zugang ist nur zum Ansehen freigeschaltet."
            )
        action = str(request.POST.get("action") or "").strip()
        try:
            if action == "template_save":
                raw_id = str(request.POST.get("template_id") or "").strip()
                item = WhatsAppTemplate.objects.filter(pk=int(raw_id)).first() if raw_id.isdigit() else WhatsAppTemplate()
                name = str(request.POST.get("name") or "").strip()
                body = str(request.POST.get("body") or "").strip()
                if not name or not body:
                    raise ValueError("Name und Text der Vorlage sind erforderlich.")
                item.name = name[:100]
                item.body = body[:5000]
                item.active = request.POST.get("active") == "on"
                item.sort_order = max(0, min(9999, int(request.POST.get("sort_order") or 100)))
                item.save()
                return redirect("/verwaltung/mehr/?saved=template#whatsapp-templates")

            if action == "template_delete":
                WhatsAppTemplate.objects.filter(
                    pk=int(request.POST.get("template_id"))
                ).delete()
                return redirect("/verwaltung/mehr/?saved=template#whatsapp-templates")

            if action in {"banner_save", "banner_delete"}:
                payload = {"action": "delete" if action == "banner_delete" else "save"}
                banner_id = str(request.POST.get("banner_id") or "").strip()
                if banner_id.isdigit():
                    payload["id"] = int(banner_id)
                if action == "banner_save":
                    uploaded = request.FILES.get("cover_image")
                    payload.update({
                        "title": request.POST.get("title") or "",
                        "text": request.POST.get("text") or "",
                        "image_url": request.POST.get("image_url") or "",
                        "cta_label": request.POST.get("cta_label") or "",
                        "cta_url": request.POST.get("cta_url") or "",
                        "active": request.POST.get("active") == "on",
                        "starts_at": request.POST.get("starts_at") or "",
                        "ends_at": request.POST.get("ends_at") or "",
                        "sort_order": int(request.POST.get("sort_order") or 100),
                    })
                    if uploaded:
                        if uploaded.content_type not in {"image/jpeg", "image/png", "image/webp"}:
                            raise ValueError("Bitte ein JPG-, PNG- oder WebP-Bild auswählen.")
                        if uploaded.size > 6 * 1024 * 1024:
                            raise ValueError("Das Banner-Bild darf maximal 6 MB groß sein.")
                        payload.update({
                            "cover_name": uploaded.name,
                            "cover_type": uploaded.content_type,
                            "cover_data": base64.b64encode(uploaded.read()).decode("ascii"),
                        })
                app_management_views._api(
                    request,
                    "dashboard-banners/",
                    method="POST",
                    payload=payload,
                )
                return redirect("/verwaltung/mehr/?saved=banner#campaigns")
        except (PermissionError, RuntimeError, ValueError, TypeError) as exc:
            error = str(exc)

    banners = []
    banners_error = ""
    if request.session.get("aplus_app_admin"):
        try:
            banners = app_management_views._api(
                request, "dashboard-banners/"
            ).get("banners", [])
        except (PermissionError, RuntimeError) as exc:
            banners_error = str(exc)

    return render(request, "booking/admin_more.html", {
        "banners": banners,
        "banners_error": banners_error,
        "templates": WhatsAppTemplate.objects.all(),
        "view_only": view_only,
        "error": error,
        "saved": request.GET.get("saved") or "",
    })
