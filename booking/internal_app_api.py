import html
import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .emails import CLINIC_REPLY_EMAIL, _send_html_mail


def _token():
    direct = str(getattr(settings, "PATIENT_SYNC_TOKEN", "") or "").strip()
    if direct:
        return direct
    try:
        return Path(getattr(settings, "PATIENT_SYNC_TOKEN_FILE", "/etc/aesthetic-patient-sync.token")).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _authorized(request):
    expected = _token()
    supplied = str(request.headers.get("X-Aesthetic-Patient-Sync") or "").strip()
    return bool(expected and supplied and expected == supplied)


def _json(request):
    try:
        return json.loads(request.body.decode("utf-8")) if request.body else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _brand_mail(title, eyebrow, message, action_html=""):
    return f"""<!doctype html><html><body style="margin:0;background:#f5f1e9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;color:#24211c">
    <table width="100%" cellspacing="0" cellpadding="0" style="padding:32px 12px;background:#f5f1e9"><tr><td align="center">
    <table width="100%" cellspacing="0" cellpadding="0" style="max-width:620px;background:#fff;border:1px solid #e4dccd;border-radius:24px;overflow:hidden">
    <tr><td style="padding:32px 36px;text-align:center"><img src="https://a-esthetic.de/wp-content/uploads/prev.png" alt="A+ Esthetic" style="width:150px;max-width:44%;height:auto">
    <div style="margin-top:22px;font-size:10px;letter-spacing:.2em;color:#a47a22;font-weight:800">{html.escape(eyebrow)}</div>
    <h1 style="font-family:Georgia,serif;font-size:34px;font-weight:500;margin:10px 0 12px">{html.escape(title)}</h1>
    <p style="color:#756e64;line-height:1.65;margin:0 0 22px">{message}</p>{action_html}</td></tr>
    <tr><td style="background:#29251f;color:#d8d1c5;padding:22px;text-align:center;font-size:12px">A+ Esthetic Frankfurt · Stiftstraße 14, 60313 Frankfurt am Main</td></tr>
    </table></td></tr></table></body></html>"""


@csrf_exempt
@require_POST
def app_mail(request):
    if not _authorized(request):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)
    data = _json(request)
    recipient = str(data.get("recipient") or "").strip().lower()
    code = str(data.get("code") or "").strip()
    if str(data.get("kind") or "") != "email_verification":
        return JsonResponse({"ok": False, "error": "unsupported_mail_kind"}, status=400)
    if "@" not in recipient or len(code) != 6 or not code.isdigit():
        return JsonResponse({"ok": False, "error": "invalid_mail_payload"}, status=400)
    name = html.escape(str(data.get("name") or "A+ Mitglied"))
    subject = "A+ Esthetic · E-Mail bestätigen"
    text = f"Hallo {name},\n\nIhr Bestätigungscode lautet: {code}\nDer Code ist 15 Minuten gültig."
    action = f'<div style="display:inline-block;background:#29251f;color:#fff;border-radius:14px;padding:16px 25px;font-size:28px;letter-spacing:.22em;font-weight:800">{html.escape(code)}</div>'
    body = _brand_mail("E-Mail bestätigen", "A+ KONTO", f"Hallo {name},<br>geben Sie diesen Code in der A+ App ein. Er ist 15 Minuten gültig.", action)
    _send_html_mail(subject, text, body, [recipient], reply_to=[CLINIC_REPLY_EMAIL])
    return JsonResponse({"ok": True, "sent": True})


@csrf_exempt
@require_POST
def admin_bootstrap(request):
    if not _authorized(request):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)
    data = _json(request)
    email = str(data.get("email") or "").strip().lower()
    password = str(data.get("password") or "")
    if email != "info@a-esthetic.de" or len(password) < 16:
        return JsonResponse({"ok": False, "error": "invalid_admin_bootstrap"}, status=400)

    User = get_user_model()
    user = User.objects.filter(email__iexact=email).first() or User.objects.filter(username=email).first()
    created = user is None
    if user is None:
        user = User(username=email, email=email)
    user.username = email
    user.email = email
    user.first_name = "A+ Esthetic"
    user.last_name = "Admin"
    user.is_active = True
    user.is_staff = True
    user.is_superuser = True
    user.set_password(password)
    user.save()

    safe_email = html.escape(email)
    subject = "A+ Esthetic · Admin-Zugang"
    text = f"Admin-Zugang\n\nE-Mail: {email}\nPasswort: {password}\n\nBitte sicher aufbewahren."
    credentials = (
        '<div style="text-align:left;background:#fbf8f2;border:1px solid #e4dccd;border-radius:16px;padding:18px">'
        '<div style="font-size:11px;color:#8e826f">E-MAIL</div><strong>' + safe_email + '</strong>'
        '<div style="font-size:11px;color:#8e826f;margin-top:14px">TEMPORÄRES PASSWORT</div>'
        '<strong style="font-family:monospace;font-size:17px">' + html.escape(password) + '</strong></div>'
    )
    body = _brand_mail("Ihr Admin-Zugang", "A+ VERWALTUNG", "Der neue Admin-Zugang wurde eingerichtet. Bitte bewahren Sie die Zugangsdaten sicher auf.", credentials)
    _send_html_mail(subject, text, body, [email], reply_to=[CLINIC_REPLY_EMAIL])
    return JsonResponse({"ok": True, "created": created, "credentials_sent": True})
