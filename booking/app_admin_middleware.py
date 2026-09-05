class APlusAdminNavigationMiddleware:
    """Add A+ App management to the existing Book drawer for verified app admins.

    Book remains the canonical UI. We inject only navigation chrome into rendered
    admin HTML; authorization for every A+ management page still comes from the
    protected Django session and the upstream A+ bearer stored server-side.
    """

    DRAWER_MARKER = '<a href="/verwaltung/logout/"><span>↪</span>Logout</a>'
    APP_NAV = '''<div class="app-nav-label">A+ APP</div>
    <a href="/verwaltung/app/club/"><span>♟</span>Customer Club</a>
    <a href="/verwaltung/app/packages/"><span>▤</span>Pakete</a>
    <a href="/verwaltung/app/rewards/"><span>◆</span>Rewards</a>
    <a href="/verwaltung/app/notifications/"><span>◉</span>Push & Mitteilungen</a>
    <a href="/verwaltung/app/referrals/"><span>↗</span>Empfehlungen</a>
    <a href="/verwaltung/app/modules/"><span>⊞</span>App-Module</a>
    <a href="/verwaltung/app/devices/"><span>◫</span>Konten & Geräte</a>
    '''
    DESKTOP_MARKER = '<a href="#einstellungen">Einstellungen</a>'
    STYLE = '''<style id="aplus-app-nav-style">
    .sb-drawer-nav .app-nav-label{padding:15px 16px 6px;font-size:10px;font-weight:800;letter-spacing:.16em;color:#9b9386}
    .sb-drawer-nav .app-nav-label+ a{margin-top:1px}
    </style>'''

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
        if 'href="/verwaltung/app/club/"' in html:
            return response
        if self.DRAWER_MARKER in html:
            html = html.replace(self.DRAWER_MARKER, self.APP_NAV + self.DRAWER_MARKER, 1)
        if self.DESKTOP_MARKER in html:
            html = html.replace(
                self.DESKTOP_MARKER,
                self.DESKTOP_MARKER + '<a href="/verwaltung/app/club/">A+ App</a>',
                1,
            )
        if '</head>' in html and 'id="aplus-app-nav-style"' not in html:
            html = html.replace('</head>', self.STYLE + '</head>', 1)
        response.content = html.encode(response.charset or 'utf-8')
        if response.has_header('Content-Length'):
            response['Content-Length'] = str(len(response.content))
        return response