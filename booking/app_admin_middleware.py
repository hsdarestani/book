class APlusAdminNavigationMiddleware:
    """Keep verified A+ app admins inside one consistent Book management shell."""

    LUXURY_ASSETS = '''
<link rel="stylesheet" href="/static/booking/admin-luxury-v2.css?v=20260907-v2" data-aplus-luxury>
<link rel="stylesheet" href="/static/booking/admin-luxury-v3.css?v=20260907-v3" data-aplus-luxury-v3>
<link rel="stylesheet" href="/static/booking/admin-wallet-history-v4.css?v=20260907-v4" data-aplus-wallet-history-v4>
<script defer src="/static/booking/admin-luxury-v2.js?v=20260907-v2" data-aplus-luxury></script>
<script defer src="/static/booking/admin-luxury-v3.js?v=20260907-v3" data-aplus-luxury-v3></script>
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

        # One asset layer owns the drawer and non-calendar visual system across
        # legacy Book pages, focused A+ pages, wallet and patient detail pages.
        # The actual calendar grid/timeline is deliberately left untouched.
        if 'data-aplus-luxury' not in html and '</head>' in html:
            html = html.replace('</head>', self.LUXURY_ASSETS + '</head>', 1)

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
        if not request.path.startswith('/verwaltung/kalender/'):
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
