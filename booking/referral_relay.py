import html
import json
import re
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .emails import CLINIC_REPLY_EMAIL, _send_html_mail
from .referral_models import ReferralEmailDelivery


ME_URL = "https://esthetic.smarbiz.sbs/api/mobile/me/"
REFERRAL_CODE_RE = re.compile(r"^(?:[A-HJ-NP-Z2-9]{6}|APLUS-[A-Z0-9-]{3,26})$")
DEFAULT_IOS_STORE_URL = "https://apps.apple.com/de/search?term=A%2B%20Esthetic"
DEFAULT_ANDROID_STORE_URL = "https://play.google.com/store/apps/details?id=de.aplusesthetic.app"


def _json(request):
    try:
        return json.loads(request.body.decode("utf-8")) if request.body else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _verify_customer_club_token(request):
    auth = str(request.headers.get("Authorization") or "").strip()
    if not auth.startswith("Bearer ") or len(auth) < 24:
        return None
    remote = Request(
        ME_URL,
        headers={
            "Authorization": auth,
            "Accept": "application/json",
            "User-Agent": "A-Esthetic-Book-Referral-Relay/1.0",
        },
    )
    try:
        with urlopen(remote, timeout=12) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not payload.get("ok"):
        return None
    profile = payload.get("profile") or {}
    member = payload.get("member") or {}
    email = str(profile.get("email") or "").strip().lower()
    name = str(member.get("name") or "A+ Mitglied").strip()[:120]
    if not email:
        return None
    return {"email": email, "name": name}


def _client_ip(request):
    forwarded = str(
        request.META.get("HTTP_CF_CONNECTING_IP")
        or request.META.get("HTTP_X_FORWARDED_FOR")
        or ""
    )
    if forwarded:
        return forwarded.split(",", 1)[0].strip()[:45]
    return str(request.META.get("REMOTE_ADDR") or "")[:45] or None


@csrf_exempt
@require_http_methods(["POST"])
def referral_email(request):
    identity = _verify_customer_club_token(request)
    if not identity:
        return JsonResponse(
            {"ok": False, "error": "customer_club_auth_required"},
            status=401,
        )

    data = _json(request)
    invited_email = str(data.get("invited_email") or "").strip().lower()
    referral_code = str(data.get("referral_code") or "").strip().upper()
    try:
        validate_email(invited_email)
    except ValidationError:
        return JsonResponse({"ok": False, "error": "valid_email_required"}, status=400)
    if invited_email == identity["email"]:
        return JsonResponse({"ok": False, "error": "cannot_refer_yourself"}, status=409)
    if not REFERRAL_CODE_RE.fullmatch(referral_code):
        return JsonResponse({"ok": False, "error": "invalid_referral_code"}, status=400)

    now = timezone.now()
    recent_sender = ReferralEmailDelivery.objects.filter(
        referrer_email__iexact=identity["email"],
        status="sent",
        created_at__gte=now - timedelta(hours=24),
    ).count()
    if recent_sender >= 5:
        return JsonResponse({"ok": False, "error": "referral_daily_limit"}, status=429)
    recent_recipient = ReferralEmailDelivery.objects.filter(
        referrer_email__iexact=identity["email"],
        invited_email__iexact=invited_email,
        status="sent",
        created_at__gte=now - timedelta(days=30),
    ).count()
    if recent_recipient >= 2:
        return JsonResponse({"ok": False, "error": "referral_recipient_limit"}, status=429)

    referrer_name = identity["name"] or "A+ Mitglied"
    safe_name = html.escape(referrer_name)
    safe_code = html.escape(referral_code)
    ios_url = html.escape(
        str(getattr(settings, "AESTHETIC_IOS_STORE_URL", DEFAULT_IOS_STORE_URL))
    )
    android_url = html.escape(
        str(getattr(settings, "AESTHETIC_ANDROID_STORE_URL", DEFAULT_ANDROID_STORE_URL))
    )

    subject = f"{referrer_name} lädt Sie zu A+ Esthetic ein"
    text = (
        f"Hallo,\n\n{referrer_name} lädt Sie in die A+ Esthetic App ein.\n"
        "1. Laden Sie die App im App Store oder bei Google Play herunter.\n"
        f"2. Registrieren Sie sich und geben Sie den Empfehlungscode {referral_code} ein.\n"
        "3. Nach erfolgreicher Registrierung erhalten Sie 300 A+ Punkte.\n\n"
        "A+ Esthetic"
    )
    html_body = f"""<!doctype html>
    <html><body style="margin:0;background:#f5f1e9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;color:#24211c">
    <table width="100%" cellspacing="0" cellpadding="0" style="background:#f5f1e9;padding:32px 12px"><tr><td align="center">
    <table width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;background:#fff;border:1px solid #e4dccd;border-radius:24px;overflow:hidden">
    <tr><td style="padding:32px 38px 18px;text-align:center"><img src="https://a-esthetic.de/wp-content/uploads/prev.png" alt="A+ Esthetic" style="width:150px;max-width:45%;height:auto"></td></tr>
    <tr><td style="padding:2px 38px 38px;text-align:center">
    <div style="font-size:10px;letter-spacing:.2em;color:#a47a22;font-weight:800">PERSÖNLICHE EINLADUNG</div>
    <h1 style="font-family:Georgia,serif;font-size:34px;font-weight:500;line-height:1.12;margin:11px 0 12px">Willkommen bei A+ Esthetic</h1>
    <p style="color:#716a61;line-height:1.65;margin:0 0 24px"><strong>{safe_name}</strong> hat Sie persönlich eingeladen. Laden Sie zuerst die A+ Esthetic App herunter und registrieren Sie sich anschließend mit dem Empfehlungscode.</p>
    <div style="display:inline-block;background:#fbf7ee;border:1px solid #e6dac0;border-radius:16px;padding:16px 24px;margin:0 0 24px">
      <div style="font-size:10px;color:#8b806e;letter-spacing:.13em">IHR EMPFEHLUNGSCODE</div>
      <div style="font-size:23px;font-weight:850;letter-spacing:.08em;margin-top:6px">{safe_code}</div>
      <div style="font-size:11px;color:#8b806e;margin-top:6px">300 A+ Punkte nach erfolgreicher Registrierung</div>
    </div>
    <div style="margin:0 auto 10px"><a href="{ios_url}" style="display:inline-block;min-width:210px;background:#25221d;color:#fff;text-decoration:none;padding:14px 20px;border-radius:12px;font-weight:750">Im App Store laden</a></div>
    <div><a href="{android_url}" style="display:inline-block;min-width:210px;border:1px solid #d9d0c2;color:#25221d;text-decoration:none;padding:13px 20px;border-radius:12px;font-weight:750">Bei Google Play laden</a></div>
    <p style="font-size:12px;color:#8b847b;line-height:1.6;margin:26px 0 0">Nach der Installation: Konto erstellen → E-Mail und Telefonnummer bestätigen → Empfehlungscode eingeben.</p>
    </td></tr>
    <tr><td style="background:#29251f;color:#d8d1c5;padding:23px;text-align:center;font-size:12px;line-height:1.6">A+ Esthetic Frankfurt · Stiftstraße 14, 60313 Frankfurt am Main</td></tr>
    </table></td></tr></table></body></html>"""

    delivery = ReferralEmailDelivery(
        referrer_email=identity["email"],
        invited_email=invited_email,
        referral_code=referral_code,
        status="failed",
        ip_address=_client_ip(request),
    )
    try:
        _send_html_mail(
            subject,
            text,
            html_body,
            [invited_email],
            reply_to=[CLINIC_REPLY_EMAIL],
        )
        delivery.status = "sent"
        delivery.save()
    except Exception as exc:
        delivery.error = str(exc)[:500]
        delivery.save()
        return JsonResponse({"ok": False, "error": "referral_email_failed"}, status=503)

    return JsonResponse({
        "ok": True,
        "email_sent": True,
        "delivery_id": delivery.pk,
        "referral_code": referral_code,
    }, status=201)
