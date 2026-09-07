from django.http import HttpResponseForbidden
from django.utils.html import escape

from .models import Service


class APlusAdminNavigationMiddleware:
    """Keep A+ management consistent and enforce read-only clinical access."""

    LUXURY_ASSETS = '''
<link rel="stylesheet" href="/static/booking/admin-luxury-v2.css?v=20260907-v2" data-aplus-luxury>
<link rel="stylesheet" href="/static/booking/admin-luxury-v3.css?v=20260907-v3" data-aplus-luxury-v3>
<link rel="stylesheet" href="/static/booking/admin-wallet-history-v4.css?v=20260907-v4" data-aplus-wallet-history-v4>
<link rel="stylesheet" href="/static/booking/admin-app-inset-v5.css?v=20260907-v6" data-aplus-app-inset-v6>
<link rel="stylesheet" href="/static/booking/admin-patient-controls-v6.css?v=20260907-v6" data-aplus-patient-controls-v6>
<link rel="stylesheet" href="/static/booking/admin-shell-v10.css?v=20260907-v10" data-aplus-admin-shell-v10>
<script defer src="/static/booking/admin-luxury-v2.js?v=20260907-v2" data-aplus-luxury></script>
<script defer src="/static/booking/admin-luxury-v3.js?v=20260907-v3" data-aplus-luxury-v3></script>
<script defer src="/static/booking/admin-patient-controls-v6.js?v=20260907-v6" data-aplus-patient-controls-v6></script>
'''

    NON_CALENDAR_ASSETS = '''
<link rel="stylesheet" href="/static/booking/admin-scroll-recovery-v9.css?v=20260907-v10" data-aplus-scroll-recovery-v10>
<script defer src="/static/booking/admin-fast-drawer-v7.js?v=20260907-v8" data-aplus-fast-drawer-v7></script>
<script defer src="/static/booking/admin-scroll-recovery-v9.js?v=20260907-v9" data-aplus-scroll-recovery-v9></script>
'''

    PATIENT_ASSETS = '''
<link rel="stylesheet" href="/static/booking/admin-patient-detail-v7.css?v=20260907-v11" data-aplus-patient-detail-v7>
<script defer src="/static/booking/admin-native-camera-v11.js?v=20260907-v11" data-aplus-native-camera-v11></script>
'''

    CALENDAR_ASSETS = '''
<link rel="stylesheet" href="/static/booking/admin-calendar-stability-v8.css?v=20260907-v8" data-aplus-calendar-stability-v8>
'''

    PATIENT_MOBILE_SHELL = '''
<header class="sb-mobile-bar app-mobile-bar">
  <button type="button" class="sb-icon-button" data-drawer-open aria-label="Menü öffnen">☰</button>
  <strong class="sb-mobile-title">Patientenakten</strong>
  <span class="sb-icon-button app-management-dot" aria-hidden="true">A+</span>
</header>
<div class="sb-drawer-backdrop" data-drawer-backdrop></div>
<aside class="sb-drawer app-focused-drawer" data-drawer aria-hidden="true">
  <div class="sb-drawer-brand"><img src="/static/booking/logo.png" alt="A+ Esthetic"><div><strong>A+ Esthetic</strong><span>Management</span></div></div>
  <nav class="sb-drawer-nav app-focused-nav">
    <div class="lux-nav-label">A+ MANAGEMENT</div>
    <a href="/verwaltung/dashboard/"><span>⌂</span>Dashboard</a>
    <a href="/verwaltung/kalender/"><span>▣</span>Kalender</a>
    <a href="/verwaltung/buchungen/"><span>✓</span>Buchungen</a>
    <a href="/verwaltung/kunden/"><span>♙</span>Kunden</a>
    <a href="/verwaltung/app/patients/" class="is-active"><span>▤</span>Patientenakten</a>
    <a href="/verwaltung/app/wallet/"><span>◆</span>A+ Punkte</a>
    <a href="/verwaltung/app/reviews/"><span>★</span>Google Bewertungen</a>
    <a href="/verwaltung/app/referrals/"><span>↗</span>Empfehlungen</a>
    <div class="lux-nav-break"></div>
    <a href="/verwaltung/logout/"><span>↪</span>Abmelden</a>
  </nav>
</aside>
'''

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _view_only(request):
        if not getattr(request, 'user', None) or not request.user.is_authenticated:
            return False
        try:
            profile = request.user.aesthetic_access
        except Exception:
            profile = None
        return bool(profile and profile.view_only)

    def __call__(self, request):
        if request.path.startswith('/verwaltung/') and request.method not in {'GET', 'HEAD', 'OPTIONS'} and self._view_only(request):
            return HttpResponseForbidden('Dieser Zugang ist nur zum Ansehen freigeschaltet.')

        response = self.get_response(request)
        if not request.path.startswith('/verwaltung/'):
            return response
        if response.status_code != 200 or 'text/html' not in response.get('Content-Type', ''):
            return response

        # View-only local staff still get the visual marker even without A+ SSO.
        is_aplus = bool(request.session.get('aplus_app_admin'))
        if not is_aplus and not self._view_only(request):
            return response
        try:
            html = response.content.decode(response.charset or 'utf-8')
        except (AttributeError, UnicodeDecodeError):
            return response

        is_calendar = request.path.startswith('/verwaltung/kalender/') or request.path == '/verwaltung/'
        is_patient = request.path.startswith('/verwaltung/patienten/') or request.path.startswith('/verwaltung/app/patients/')

        if is_aplus and 'data-aplus-luxury' not in html and '</head>' in html:
            html = html.replace('</head>', self.LUXURY_ASSETS + '</head>', 1)

        if is_aplus and is_calendar:
            if 'data-aplus-calendar-stability-v8' not in html and '</head>' in html:
                html = html.replace('</head>', self.CALENDAR_ASSETS + '</head>', 1)
            if '<body class="' in html and 'aplus-calendar-page' not in html:
                html = html.replace('<body class="', '<body class="aplus-calendar-page ', 1)
            html = html.replace('#kalender"', '"')
        elif is_aplus:
            if 'data-aplus-scroll-recovery-v10' not in html and '</head>' in html:
                html = html.replace('</head>', self.NON_CALENDAR_ASSETS + '</head>', 1)
            if is_patient and 'data-aplus-patient-detail-v7' not in html and '</head>' in html:
                html = html.replace('</head>', self.PATIENT_ASSETS + '</head>', 1)

        if request.path.startswith('/verwaltung/patienten/') and 'data-drawer' not in html and is_aplus:
            html = html.replace('content="width=device-width,initial-scale=1"', 'content="width=device-width,initial-scale=1,viewport-fit=cover"', 1)
            body_start = html.find('<body')
            if body_start >= 0:
                body_open_end = html.find('>', body_start)
                if body_open_end >= 0:
                    html = html[:body_open_end + 1] + self.PATIENT_MOBILE_SHELL + html[body_open_end + 1:]

        if is_aplus and not is_calendar:
            html = html.replace('<button type="button" class="sb-icon-button" data-view-menu-open aria-label="Ansicht ändern">⋯</button>', '<span class="sb-icon-button" aria-hidden="true"></span>')
            html = html.replace('<button type="button" class="sb-subtle-button" data-view-menu-open>Ansicht ▾</button>', '')
            start = html.find('<div class="sb-view-menu" data-view-menu')
            if start >= 0:
                end = html.find('</div>', start)
                if end >= 0:
                    html = html[:start] + html[end + len('</div>'):]

        # Duration is operationally important when staff create/edit a reservation.
        # Only labels are enriched; calendar geometry/colours are deliberately untouched.
        for service in Service.objects.filter(active=True).only('pk', 'name', 'duration_minutes'):
            name = escape(service.name)
            label = f'{name} · {service.duration_minutes} Min.'
            html = html.replace(f'<option value="{service.pk}">{name}</option>', f'<option value="{service.pk}">{label}</option>')
            html = html.replace(f'<option value="{service.pk}" selected>{name}</option>', f'<option value="{service.pk}" selected>{label}</option>')

        if self._view_only(request) and '<body' in html:
            body_start = html.find('<body')
            body_end = html.find('>', body_start)
            if body_end >= 0 and 'data-aplus-view-only' not in html[body_start:body_end]:
                html = html[:body_end] + ' data-aplus-view-only="1"' + html[body_end:]

        response.content = html.encode(response.charset or 'utf-8')
        if response.has_header('Content-Length'):
            response['Content-Length'] = str(len(response.content))
        return response
