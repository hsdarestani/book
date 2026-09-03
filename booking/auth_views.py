from urllib.parse import urlencode

from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import rotate_token
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.cache import patch_cache_control
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.csrf import csrf_failure as django_csrf_failure
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
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
    # A restored mobile-browser login page can survive longer than the CSRF token.
    # Never keep authenticated staff on that page; send them straight to the app.
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


def admin_logout(request):
    logout(request)
    rotate_token(request)
    return _no_store(redirect('booking:admin_login'))


def csrf_failure(request, reason=''):
    """Recover cleanly from stale mobile login forms instead of showing Django's 403 page."""
    if request.path.rstrip('/') == '/verwaltung/login':
        if getattr(request, 'user', None) is not None and request.user.is_authenticated and request.user.is_staff:
            return _no_store(redirect('booking:dashboard'))

        # The login form may have come back from the browser back/forward cache with
        # an old hidden token. Rotate once and force a fresh GET with a fresh form.
        rotate_token(request)
        params = {'csrf': 'refresh'}
        next_url = (request.POST.get('next') or request.GET.get('next') or '').strip()
        if next_url:
            params['next'] = next_url
        destination = f"{reverse('booking:admin_login')}?{urlencode(params)}"
        return _no_store(redirect(destination))

    return django_csrf_failure(request, reason=reason)
