class APlusAdminNavigationMiddleware:
    """Keep verified A+ app admins inside one consistent Book management shell."""

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
<link rel="stylesheet" href="/static/booking/admin-patient-detail-v7.css?v=20260907-v9" data-aplus-patient-detail-v7>
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
  <div class="sb-drawer-brand">
    <img src="/static/booking/logo.png" alt="A+ Esthetic">
    <div><strong>A+ Esthetic</strong><span>Management</span></div>
  </div>
  <nav class="sb-drawer-nav app-focused-nav">
    <div class="lux-nav-label">A+ MANAGEMENT</div>
    <a href="/verwaltung/kalender/"><span>▣</span>Kalender</a>
    <a href="/verwaltung/buchungen/"><span>✓</span>Buchungen</a>
    <a href="/verwaltung/kunden/"><span>♙</span>Kunden</a>
    <a href="/verwaltung/app/patients/" class="is-active"><span>▤</span>Patientenakten</a>
    <a href="/verwaltung/app/wallet/"><span>€</span>A+ Wallet</a>
    <a href="/verwaltung/app/reviews/"><span>★</span>Google Bewertungen</a>
    <a href="/verwaltung/app/referrals/"><span>↗</span>Empfehlungen</a>
    <div class="lux-nav-break"></div>
    <a href="/verwaltung/logout/"><span>↪</span>Abmelden</a>
  </nav>
</aside>
'''

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith('/verwaltung/'):
            return response
        if not request.session.get('aplus_app_admin'):
            return response
        if response.status_code != 200 or 'text/html' not in response.get('Content-Type', ''):
            return response
        try:
            html = response.content.decode(response.charset or 'utf-8')
        except (AttributeError, UnicodeDecodeError):
            return response

        is_calendar = request.path.startswith('/verwaltung/kalender/') or request.path == '/verwaltung/'
        is_patient = request.path.startswith('/verwaltung/patienten/') or request.path.startswith('/verwaltung/app/patients/')

        # Shared visual layer for all verified management pages.
        if 'data-aplus-luxury' not in html and '</head>' in html:
            html = html.replace('</head>', self.LUXURY_ASSETS + '</head>', 1)

        # Calendar remains isolated from the heavy patient/detail layer.
        if is_calendar:
            if 'data-aplus-calendar-stability-v8' not in html and '</head>' in html:
                html = html.replace('</head>', self.CALENDAR_ASSETS + '</head>', 1)
            if '<body class="' in html and 'aplus-calendar-page' not in html:
                html = html.replace('<body class="', '<body class="aplus-calendar-page ', 1)
            # Date/provider navigation should be a normal page load. Removing
            # the old #kalender anchor prevents Android from restoring the page
            # halfway down the long timeline and makes navigation feel instant.
            html = html.replace('#kalender"', '"')
        else:
            if 'data-aplus-scroll-recovery-v10' not in html and '</head>' in html:
                html = html.replace('</head>', self.NON_CALENDAR_ASSETS + '</head>', 1)
            # Patient-only form/drawer geometry must not leak into Buchungen or
            # Kunden; it used to leave a full-height layer that could intercept
            # touch scrolling on Android WebView.
            if is_patient and 'data-aplus-patient-detail-v7' not in html and '</head>' in html:
                html = html.replace('</head>', self.PATIENT_ASSETS + '</head>', 1)

        # Legacy patient detail used its own desktop-only header. Give it exactly
        # the same mobile app bar + drawer as the rest of management instead of
        # allowing navigation and spacing to change when a customer is opened.
        if request.path.startswith('/verwaltung/patienten/') and 'data-drawer' not in html:
            html = html.replace(
                'content="width=device-width,initial-scale=1"',
                'content="width=device-width,initial-scale=1,viewport-fit=cover"',
                1,
            )
            body_start = html.find('<body')
            if body_start >= 0:
                body_open_end = html.find('>', body_start)
                if body_open_end >= 0:
                    html = html[:body_open_end + 1] + self.PATIENT_MOBILE_SHELL + html[body_open_end + 1:]

        # The calendar view switcher is a calendar-only control. Remove it on the
        # server as well as in JS so it never flashes on Buchungen/Kunden pages.
        if not is_calendar:
            html = html.replace(
                '<button type="button" class="sb-icon-button" data-view-menu-open aria-label="Ansicht ändern">⋯</button>',
                '<span class="sb-icon-button" aria-hidden="true"></span>',
            )
            start = html.find('<div class="sb-view-menu" data-view-menu')
            if start >= 0:
                end = html.find('</div>', start)
                if end >= 0:
                    html = html[:start] + html[end + len('</div>'):]

        response.content = html.encode(response.charset or 'utf-8')
        if response.has_header('Content-Length'):
            response['Content-Length'] = str(len(response.content))
        return response
