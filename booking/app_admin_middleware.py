import re
from django.http import HttpResponseForbidden
from django.utils.html import escape

from .models import Service


class APlusAdminNavigationMiddleware:
    """Keep A+ management consistent and enforce read-only clinical access."""

    LUXURY_ASSETS = '''
<link rel="stylesheet" href="/static/booking/admin-luxury-v2.css?v=20260907-v2" data-aplus-luxury>
<link rel="stylesheet" href="/static/booking/admin-luxury-v3.css?v=20260907-v3" data-aplus-luxury-v3>
<link rel="stylesheet" href="/static/booking/admin-wallet-history-v4.css?v=20260907-v4" data-aplus-wallet-history-v4>
<link rel="stylesheet" href="/static/booking/admin-app-inset-v5.css?v=20260912-v20" data-aplus-app-inset-v20>
<link rel="stylesheet" href="/static/booking/admin-patient-controls-v6.css?v=20260907-v6" data-aplus-patient-controls-v6>
<link rel="stylesheet" href="/static/booking/admin-shell-v10.css?v=20260907-v10" data-aplus-admin-shell-v10>
<style data-aplus-inline-inset-v20>
@media (max-width:900px){
  body.sb-admin-body > main.sb-admin-shell,
  body.sb-admin-body > main.admin-shell,
  body.sb-admin-body .app-management-shell,
  body.sb-admin-body .command-shell{
    padding-left:max(24px,env(safe-area-inset-left))!important;
    padding-right:max(24px,env(safe-area-inset-right))!important;
  }
}
@media (max-width:520px){
  body.sb-admin-body > main.sb-admin-shell,
  body.sb-admin-body > main.admin-shell,
  body.sb-admin-body .app-management-shell,
  body.sb-admin-body .command-shell{
    padding-left:max(22px,env(safe-area-inset-left))!important;
    padding-right:max(22px,env(safe-area-inset-right))!important;
  }
}
</style>
<script defer src="/static/booking/admin-luxury-v2.js?v=20260907-v2" data-aplus-luxury></script>
<script defer src="/static/booking/admin-luxury-v3.js?v=20260907-v3" data-aplus-luxury-v3></script>
<script defer src="/static/booking/admin-points-wording-v12.js?v=20260908-v12" data-aplus-points-wording-v12></script>
<script defer src="/static/booking/admin-patient-controls-v6.js?v=20260907-v6" data-aplus-patient-controls-v6></script>
'''

    NON_CALENDAR_ASSETS = '''
<link rel="stylesheet" href="/static/booking/admin-scroll-recovery-v9.css?v=20260907-v10" data-aplus-scroll-recovery-v10>
<script defer src="/static/booking/admin-fast-drawer-v7.js?v=20260907-v8" data-aplus-fast-drawer-v7></script>
<script defer src="/static/booking/admin-scroll-recovery-v9.js?v=20260907-v9" data-aplus-scroll-recovery-v9></script>
'''

    PATIENT_ASSETS = '''
<link rel="stylesheet" href="/static/booking/admin-patient-detail-v7.css?v=20260907-v11" data-aplus-patient-detail-v7>
<script defer src="/static/booking/admin-native-camera-v11.js?v=20260908-v13" data-aplus-native-camera-v11></script>
'''

    CALENDAR_ASSETS = '''
<link rel="stylesheet" href="/static/booking/admin-calendar-stability-v8.css?v=20260907-v8" data-aplus-calendar-stability-v8>
'''

    FINAL_FERRARI_ASSETS = '''
<link rel="stylesheet" href="/static/booking/admin-ferrari-v17.css?v=20260922-v17" data-aplus-ferrari-v17>
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

    PATIENT_MOBILE_SHELL_DOCTOR = '''
<header class="sb-mobile-bar app-mobile-bar">
  <button type="button" class="sb-icon-button" data-drawer-open aria-label="Menü öffnen">☰</button>
  <strong class="sb-mobile-title">Patientenakte</strong>
  <span class="sb-icon-button app-management-dot" aria-hidden="true">A+</span>
</header>
<div class="sb-drawer-backdrop" data-drawer-backdrop></div>
<aside class="sb-drawer app-focused-drawer" data-drawer aria-hidden="true">
  <div class="sb-drawer-brand"><img src="/static/booking/logo.png" alt="A+ Esthetic"><div><strong>A+ Esthetic</strong><span>Doctor</span></div></div>
  <nav class="sb-drawer-nav app-focused-nav">
    <div class="lux-nav-label">MEINE VERWALTUNG</div>
    <a href="/verwaltung/arzt/?section=dashboard"><span>⌂</span>Dashboard</a>
    <a href="/verwaltung/arzt/?section=calendar"><span>▣</span>Kalender</a>
    <a href="/verwaltung/arzt/?section=bookings"><span>▤</span>Meine Buchungen</a>
    <a href="/verwaltung/arzt/?section=customers"><span>♙</span>Meine Patienten</a>
    <a href="/verwaltung/arzt/?section=settings"><span>◷</span>Arbeitszeiten</a>
    <div class="lux-nav-break"></div>
    <a href="/verwaltung/logout/"><span>↪</span>Abmelden</a>
  </nav>
</aside>
'''

    # This inline finalizer is intentionally after every deferred or dynamically
    # loaded legacy A+ menu. Several generations of menu scripts still coexist
    # in deployed browsers and may rebuild the DOM after the role-aware script.
    # The middleware enforces permissions independently of this UX safeguard.
    DOCTOR_NAV_GUARD = """
<script data-aplus-doctor-nav-finalizer>
(() => {
  'use strict';
  const isDoctor = document.documentElement.dataset.doctorRole === '1'
    || document.body?.dataset.doctorCalendar === '1';
  if (!isDoctor) return;
  const entries = [
    ['dashboard', '⌂', 'Dashboard'],
    ['calendar', '▣', 'Kalender'],
    ['bookings', '▤', 'Meine Buchungen'],
    ['customers', '♙', 'Meine Patienten'],
    ['settings', '◷', 'Arbeitszeiten'],
  ];
  const keys = new Set(entries.map(item => item[0]));
  const href = section => '/verwaltung/arzt/?section=' + section;
  function selectedSection() {
    if (/^\\/verwaltung\\/patienten\\//.test(location.pathname)) return 'customers';
    const section = new URLSearchParams(location.search).get('section') || 'calendar';
    return keys.has(section) ? section : 'calendar';
  }
  function expectedLinks() {
    return entries.map(([key, icon, name]) =>
      '<a href="' + href(key) + '" data-aplus-nav="' + key
      + '" class="' + (selectedSection() === key ? 'is-active' : '') + '"><span>'
      + icon + '</span>' + name + '</a>'
    ).join('');
  }
  const logout = '<a href="/verwaltung/logout/" data-aplus-nav="logout"><span>↪</span>Abmelden</a>';
  let updating = false;
  function validLinks(nav) {
    const links = [...nav.querySelectorAll('a[href]')];
    if (links.length !== entries.length + 1) return false;
    return entries.every(([key], i) =>
      links[i].getAttribute('href') === href(key)
      && links[i].dataset.aplusNav === key
    ) && links[entries.length].getAttribute('href') === '/verwaltung/logout/';
  }
  function validDesktop(nav) {
    const links = [...nav.querySelectorAll('a[href]')];
    return links.length === entries.length &&
      entries.every(([key], i) => links[i].getAttribute('href') === href(key));
  }
  function reconcile() {
    if (updating) return;
    updating = true;
    try {
      document.documentElement.dataset.adminPage = selectedSection();
      const drawer = document.querySelector('[data-drawer]');
      const nav = drawer?.querySelector('.sb-drawer-nav');
      if (drawer && nav && (!validLinks(nav)
          || !nav.classList.contains('aplus-unified-nav'))) {
        drawer.classList.add('aplus-unified-drawer');
        nav.classList.add('aplus-unified-nav');
        nav.innerHTML = '<div class="lux-nav-label">MEINE VERWALTUNG</div>'
          + expectedLinks() + '<div class="lux-nav-break"></div>' + logout;
      }
      const brand = drawer?.querySelector('.sb-drawer-brand span');
      if (brand && brand.textContent !== 'Doctor') brand.textContent = 'Doctor';
      document.querySelectorAll('.admin-topbar .admin-nav').forEach(nav => {
        if (!validDesktop(nav)) {
          nav.classList.add('aplus-unified-desktop-nav');
          nav.innerHTML = entries.map(([key, , name]) =>
            '<a href="' + href(key) + '" class="'
            + (selectedSection() === key ? 'is-active' : '') + '">' + name + '</a>'
          ).join('');
        }
      });
    } finally {
      updating = false;
    }
  }
  let scheduled = false;
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    queueMicrotask(() => {
      scheduled = false;
      reconcile();
    });
  }
  // A legacy deferred or dynamically injected management script can overwrite
  // the drawer after load. Repair only if its permitted link set changed.
  const observer = new MutationObserver(schedule);
  observer.observe(document.body, {subtree: true, childList: true});
  document.addEventListener('DOMContentLoaded', schedule);
  window.addEventListener('pageshow', schedule);
  window.addEventListener('popstate', schedule);
  document.addEventListener('click', event => {
    const link = event.target.closest?.('[data-drawer] a[href], .admin-topbar .admin-nav a[href]');
    if (!link) return;
    const target = new URL(link.href, location.origin);
    const allowed = target.origin === location.origin
      && (target.pathname === '/verwaltung/logout/' ||
          (target.pathname === '/verwaltung/arzt/' &&
           keys.has(target.searchParams.get('section'))));
    if (!allowed) {
      event.preventDefault();
      event.stopImmediatePropagation();
      reconcile();
      return;
    }
    if (link.closest('[data-drawer]')) {
      const drawer = document.querySelector('[data-drawer]');
      drawer?.classList.remove('is-open');
      drawer?.setAttribute('aria-hidden', 'true');
      document.querySelector('[data-drawer-backdrop]')?.classList.remove('is-open');
      document.documentElement.classList.remove('drawer-open');
      document.body.classList.remove('drawer-open');
    }
  }, true);
  reconcile();
})();
</script>
"""

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

    @staticmethod
    def _qamar_scope(request):
        if not APlusAdminNavigationMiddleware._view_only(request):
            return False
        profile = getattr(request.user, 'aesthetic_access', None)
        return bool(
            profile and profile.staff_id and profile.staff
            and profile.staff.display_name.strip().casefold() == 'qamar hameed'
        )

    def __call__(self, request):
        view_only = self._view_only(request)
        qamar_scope = self._qamar_scope(request)
        if qamar_scope:
            # One full-featured admin shell, but only Qamar's scoped routes.
            # Other view-only team members retain their own prior access.
            allowed = {
                '/verwaltung/arzt/', '/verwaltung/logout/', '/verwaltung/login/',
                '/verwaltung/app/', '/verwaltung/app-sso/',
                '/verwaltung/api/calendar-day/', '/verwaltung/api/day-availability/',
            }
            # Customer IDs are additionally checked in the view and file
            # endpoint. Do not allow shared app/patient API routes here.
            own_patient_route = bool(re.fullmatch(
                r'/verwaltung/patienten/[0-9]+/(?:datei/[0-9a-fA-F-]{36}/(?:(?:ansicht|vorschau)/)?)?',
                request.path,
            ))
            if request.path.startswith('/admin/') or (
                request.path.startswith('/verwaltung/')
                and request.path not in allowed and not own_patient_route
            ):
                return HttpResponseForbidden('Dieser Zugang ist auf eigene Termine beschränkt.')
        if (
            view_only
            and request.path.startswith('/verwaltung/')
            and request.method not in {'GET', 'HEAD', 'OPTIONS'}
            and request.path not in {'/verwaltung/app-sso/', '/verwaltung/arzt/', '/verwaltung/api/day-availability/'}
            and not (qamar_scope and own_patient_route)
        ):
            return HttpResponseForbidden('Dieser Zugang ist nur zum Ansehen freigeschaltet.')

        response = self.get_response(request)
        if not request.path.startswith('/verwaltung/'):
            return response
        if response.status_code != 200 or 'text/html' not in response.get('Content-Type', ''):
            return response

        # Admin HTML must never be reused from the Android WebView disk cache.
        # Public static files are versioned separately; this only governs
        # private, per-user pages including Punkte and patient details.
        response['Cache-Control'] = 'private, no-store, no-cache, max-age=0, must-revalidate'
        response['Pragma'] = 'no-cache'

        # The file viewer has its own compact same-tab controls. Injecting the
        # legacy patient drawer here would overlay them inside mobile WebViews.
        if request.resolver_match and request.resolver_match.url_name == 'patient_record_view':
            return response

        # View-only local staff still get the visual marker even without A+ SSO.
        # Verified clinician sessions use the same management theme regardless
        # of whether they arrived by SSO or a staff session.
        is_aplus = bool(request.session.get('aplus_app_admin')) or qamar_scope
        if not is_aplus and not self._view_only(request):
            return response
        try:
            html = response.content.decode(response.charset or 'utf-8')
        except (AttributeError, UnicodeDecodeError):
            return response

        is_calendar = (
            request.path.startswith('/verwaltung/kalender/')
            or request.path == '/verwaltung/'
            or qamar_scope and request.path == '/verwaltung/arzt/'
        )
        is_patient = request.path.startswith('/verwaltung/patienten/') or request.path.startswith('/verwaltung/app/patients/')

        if is_aplus and 'data-aplus-luxury' not in html and '</head>' in html:
            assets = self.LUXURY_ASSETS
            if qamar_scope:
                # Explicit cache bust for older installed WebViews / browser CSS+JS.
                assets = assets.replace(
                    'admin-luxury-v2.js?v=20260907-v2',
                    'admin-luxury-v2.js?v=20261020-doctor-role-v2',
                )
            html = html.replace('</head>', assets + '</head>', 1)

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
                    html = (
                    html[:body_open_end + 1]
                    + (self.PATIENT_MOBILE_SHELL_DOCTOR if qamar_scope else self.PATIENT_MOBILE_SHELL)
                    + html[body_open_end + 1:]
                )

        if is_aplus and not is_calendar:
            # Dashboard templates are also used for bookings and customers.
            # Replace the entire mobile calendar bar on those pages: relying
            # on the old exact three-dot button no longer works after the
            # reference-based iPhone calendar header redesign.
            html = re.sub(
                r'<header class="sb-mobile-bar sb-reference-calendar-bar">.*?</header>',
                '<header class="sb-mobile-bar">'
                '<button type="button" class="sb-icon-button" data-drawer-open aria-label="Menü öffnen">☰</button>'
                '<strong class="sb-mobile-title">Verwaltung</strong>'
                '<span class="sb-icon-button" aria-hidden="true"></span></header>',
                html,
                count=1,
                flags=re.S,
            )
            html = html.replace('<button type="button" class="sb-icon-button" data-view-menu-open aria-label="Ansicht ändern">⋯</button>', '<span class="sb-icon-button" aria-hidden="true"></span>')
            html = html.replace('<button type="button" class="sb-subtle-button" data-view-menu-open>Ansicht ▾</button>', '')
            start = html.find('<div class="sb-view-menu" data-view-menu')
            if start >= 0:
                end = html.find('</div>', start)
                if end >= 0:
                    html = html[:start] + html[end + len('</div>'):]

        # Avoid DB access on pages without service options; for pages with
        # options, a single regex pass replaces one full HTML scan per service.
        if '<option value="' in html:
            service_labels = {
                str(service.pk): (escape(service.name), service.duration_minutes)
                for service in Service.objects.filter(active=True).only('pk', 'name', 'duration_minutes')
            }
            if service_labels:
                pattern = re.compile(r'<option value="(\d+)"( selected)?>([^<]*)</option>')

                def add_service_duration(match):
                    service = service_labels.get(match.group(1))
                    if service is None or match.group(3) != service[0]:
                        return match.group(0)
                    return (
                        f'<option value="{match.group(1)}"{match.group(2) or ""}>'
                        f'{service[0]} · {service[1]} Min.</option>'
                    )

                html = pattern.sub(add_service_duration, html)

        if is_aplus and 'data-aplus-ferrari-v17' not in html and '</head>' in html:
            html = html.replace('</head>', self.FINAL_FERRARI_ASSETS + '</head>', 1)

        if self._view_only(request) and not qamar_scope and '<body' in html:
            body_start = html.find('<body')
            body_end = html.find('>', body_start)
            if body_end >= 0 and 'data-aplus-view-only' not in html[body_start:body_end]:
                html = html[:body_end] + ' data-aplus-view-only="1"' + html[body_end:]

        if qamar_scope and '</body>' in html and 'data-aplus-doctor-nav-finalizer' not in html:
            html = html.replace('</body>', self.DOCTOR_NAV_GUARD + '</body>', 1)
            response['Cache-Control'] = 'private, no-store, max-age=0'

        # The opt-in management theme follows legacy SSO styles. Calendar
        # templates never opt in and retain their original asset order.
        if 'data-clinic-design="calm"' in html or 'data-clinic-design="premium"' in html:
            theme = re.search(r'<link[^>]+data-clinic-design-sheet[^>]*>', html)
            if theme:
                html = html.replace(theme.group(0), '', 1)
                html = html.replace('</head>', theme.group(0) + '</head>', 1)

        # Shared navigation is isolated from calendar contents and comes after
        # the old SSO theme, just like the opt-in management stylesheet.
        navigation = re.search(r'<link[^>]+data-clinic-navigation-sheet[^>]*>', html)
        if navigation:
            html = html.replace(navigation.group(0), '', 1)
            html = html.replace('</head>', navigation.group(0) + '</head>', 1)

        # A+ premium design must win the CSS cascade after all legacy/SSO
        # sheets. Asset paths are intentionally literal: unit tests render
        # templates before collectstatic creates the WhiteNoise manifest.
        if 'data-clinic-design="premium"' in html:
            premium_links = re.findall(
                r'<link[^>]+href="[^"]*/booking/clinic-premium-(?:v1|all-v2|dashboard-v3|signature-surfaces-v1)\.css[^"]*"[^>]*>',
                html,
            )
            for link in premium_links:
                html = html.replace(link, '', 1)
            if premium_links and '</head>' in html:
                html = html.replace('</head>', ''.join(premium_links) + '</head>', 1)

        # The patient/wallet finish is part of their server-side templates,
        # independent of whether authentication arrived through A+ SSO.
        # Reposition it after any premium CSS reordered above. Never inject
        # a duplicate URL or rely on client-side theme activation.
        if request.path.startswith(('/verwaltung/app/patients/', '/verwaltung/app/wallet/')):
            finish = re.search(r'<link[^>]+data-clinic-mobile-finish-v4[^>]*>', html)
            if finish and '</head>' in html:
                html = html.replace(finish.group(0), '', 1)
                html = html.replace('</head>', finish.group(0) + '</head>', 1)

        response.content = html.encode(response.charset or 'utf-8')
        if response.has_header('Content-Length'):
            response['Content-Length'] = str(len(response.content))
        return response
