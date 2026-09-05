from urllib.parse import urlencode

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import rotate_token
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.cache import patch_cache_control
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.csrf import csrf_failure as django_csrf_failure
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods


def _no_store(response):
    patch_cache_control(
        response,
        no_cache=True,
        no_store=True,
        must_revalidate=True,
        private=True,
        max_age=0,
    )
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response


def _safe_next(request, raw_value):
    value = (raw_value or '').strip()
    if value and url_has_allowed_host_and_scheme(
        value,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return value
    return ''


@never_cache
@ensure_csrf_cookie
@require_http_methods(['GET', 'POST'])
def admin_login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return _no_store(redirect('booking:dashboard'))

    error = ''
    next_url = request.GET.get('next', '')
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        next_url = request.POST.get('next') or ''
        user = authenticate(request, username=username, password=password)
        if user and user.is_staff:
            login(request, user)
            destination = _safe_next(request, next_url)
            if destination:
                return _no_store(redirect(destination))
            return _no_store(redirect('booking:dashboard'))
        error = 'Anmeldung nicht möglich. Bitte prüfe deine Zugangsdaten.'

    response = render(
        request,
        'booking/admin_login.html',
        {'error': error, 'next': next_url},
    )
    return _no_store(response)


@never_cache
@require_http_methods(['GET'])
def app_admin_entry(request):
    """Top-level bridge from the native/web A+ app into the real Book administration.

    The A+ bearer token is deliberately supplied in the URL fragment. Fragments are
    not sent in HTTP requests, access logs or referrers. This tiny page moves it into
    an Authorization header and establishes a normal first-party Book staff session.
    """
    response = HttpResponse(
        """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light">
<title>A+ Esthetic · Verwaltung</title>
<style>
html,body{margin:0;min-height:100%;background:#fff;color:#29261f;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{min-height:100vh;display:grid;place-items:center;padding:24px;box-sizing:border-box;text-align:center}
.wrap{max-width:340px}.mark{width:52px;height:52px;margin:0 auto 14px;border-radius:50%;display:grid;place-items:center;background:#d8a73b;color:#fff;font:700 21px Georgia,serif;box-shadow:0 8px 24px #00000018}
h1{font:600 22px Georgia,serif;margin:0 0 7px}p{margin:0;color:#756f64;font-size:14px;line-height:1.45}.error{color:#9d2b22}.spinner{width:24px;height:24px;margin:18px auto;border:2px solid #e8dfce;border-top-color:#b98b2f;border-radius:50%;animation:s .8s linear infinite}@keyframes s{to{transform:rotate(360deg)}}
</style>
</head>
<body><main><div class="wrap"><div class="mark">A+</div><h1>Verwaltung</h1><p id="status">Book wird geöffnet…</p><div class="spinner" id="spinner"></div></div></main>
<script>
(async()=>{
 const status=document.getElementById('status');
 const spinner=document.getElementById('spinner');
 const raw=(location.hash||'').replace(/^#token=/,'');
 const token=raw?decodeURIComponent(raw):'';
 history.replaceState(null,'',location.pathname+location.search);
 if(!token){status.textContent='Admin-Sitzung fehlt. Bitte die Verwaltung erneut in der A+ App öffnen.';status.className='error';spinner.remove();return;}
 try{
   const r=await fetch('/verwaltung/app-sso/',{method:'POST',headers:{'Authorization':'Bearer '+token,'Accept':'application/json'},cache:'no-store',credentials:'same-origin'});
   const data=await r.json().catch(()=>({}));
   if(!r.ok||!data.ok)throw new Error(data.error||'admin_required');
   location.replace(data.redirect||'/verwaltung/kalender/');
 }catch(e){status.textContent='Admin-Zugang konnte nicht bestätigt werden. Bitte erneut aus der A+ App öffnen.';status.className='error';spinner.remove();}
})();
</script></body></html>""",
        content_type='text/html; charset=utf-8',
    )
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Frame-Options'] = 'DENY'
    return _no_store(response)


@csrf_exempt
@never_cache
@require_http_methods(['POST'])
def app_admin_sso(request):
    """Verify the A+ app bearer and log the actor into a dedicated Book staff identity."""
    from .app_admin_api import _verify_admin

    admin = _verify_admin(request)
    if not admin:
        return _no_store(JsonResponse({'ok': False, 'error': 'admin_required'}, status=403))

    external_id = str(admin.get('id') or '').strip()
    if not external_id:
        return _no_store(JsonResponse({'ok': False, 'error': 'admin_identity_missing'}, status=403))

    username = f'aplus_app_admin_{external_id}'[:150]
    user, _ = User.objects.get_or_create(username=username)
    changed = []
    email = str(admin.get('email') or '').strip()
    name = str(admin.get('name') or '').strip()
    first_name, _, last_name = name.partition(' ')
    desired = {
        'email': email,
        'first_name': first_name[:150],
        'last_name': last_name[:150],
        'is_active': True,
        'is_staff': True,
        'is_superuser': False,
    }
    for field, value in desired.items():
        if getattr(user, field) != value:
            setattr(user, field, value)
            changed.append(field)
    if user.has_usable_password():
        user.set_unusable_password()
        changed.append('password')
    if changed:
        user.save(update_fields=list(dict.fromkeys(changed)))

    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    request.session['aplus_app_admin'] = True
    request.session['aplus_admin_external_id'] = external_id
    authorization = str(request.headers.get('Authorization') or '').strip()
    if authorization.startswith('Bearer '):
        request.session['aplus_admin_authorization'] = authorization
    response = JsonResponse({'ok': True, 'redirect': '/verwaltung/kalender/'})
    # Non-sensitive UI marker only. Authorization still depends on the protected
    # server-side session; this cookie merely lets the shared Book JS expose the
    # A+ App entries in the existing drawer.
    response.set_cookie('aplus_admin_ui', '1', secure=request.is_secure(), samesite='Lax', max_age=60 * 60 * 24 * 30)
    return _no_store(response)


def admin_logout(request):
    logout(request)
    rotate_token(request)
    response = redirect('booking:admin_login')
    response.delete_cookie('aplus_admin_ui')
    return _no_store(response)


def csrf_failure(request, reason=''):
    """Recover cleanly from stale mobile login forms instead of showing Django's 403 page."""
    if request.path.rstrip('/') == '/verwaltung/login':
        if getattr(request, 'user', None) is not None and request.user.is_authenticated and request.user.is_staff:
            return _no_store(redirect('booking:dashboard'))

        rotate_token(request)
        params = {'csrf': 'refresh'}
        next_url = (request.POST.get('next') or request.GET.get('next') or '').strip()
        if next_url:
            params['next'] = next_url
        destination = f"{reverse('booking:admin_login')}?{urlencode(params)}"
        return _no_store(redirect(destination))

    return django_csrf_failure(request, reason=reason)