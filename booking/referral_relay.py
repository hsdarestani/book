import html
import json
import re
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .emails import CLINIC_REPLY_EMAIL, _send_html_mail
from .referral_models import ReferralEmailDelivery


ME_URL = "https://esthetic.smarbiz.sbs/api/mobile/me/"
REFERRAL_CODE_RE = re.compile(r"^APLUS-[A-F0-9]{10}$")


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
    forwarded = str(request.META.get("HTTP_CF_CONNECTING_IP") or request.META.get("HTTP_X_FORWARDED_FOR") or "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()[:45]
    return str(request.META.get("REMOTE_ADDR") or "")[:45] or None


@csrf_exempt
@require_http_methods(["POST"])
def referral_email(request):
    identity = _verify_customer_club_token(request)
    if not identity:
        return JsonResponse({"ok": False, "error": "customer_club_auth_required"}, status=401)

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
    invite_url = f"https://esthetic.smarbiz.sbs/?ref={referral_code}"
    subject = f"{referrer_name} lädt Sie zu A+ Esthetic ein"
    text = (
        f"Hallo,\n\n{referrer_name} hat Sie zum A+ Esthetic Customer Club eingeladen.\n\n"
        f"Einladung öffnen: {invite_url}\n\n"
        "Mit freundlichen Grüßen\nA+ Esthetic"
    )
    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:620px;margin:auto;color:#172027">
      <div style="font-size:28px;font-weight:800;letter-spacing:.04em;margin-bottom:20px">A+ ESTHETIC</div>
      <h1 style="font-size:25px;margin:0 0 14px">Eine persönliche Einladung</h1>
      <p style="font-size:16px;line-height:1.6"><strong>{safe_name}</strong> hat Sie zum A+ Esthetic Customer Club eingeladen.</p>
      <p style="margin:26px 0"><a href="{invite_url}" style="display:inline-block;background:#172027;color:#fff;text-decoration:none;padding:14px 22px;border-radius:12px;font-weight:700">Einladung öffnen</a></p>
      <p style="font-size:13px;line-height:1.5;color:#66717a">Diese Einladung wurde von einem verifizierten A+ Esthetic Mitglied an diese E-Mail-Adresse gesendet. Falls Sie keine Einladung erwartet haben, können Sie diese Nachricht ignorieren.</p>
    </div>
    """

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
