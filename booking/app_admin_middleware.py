class APlusAdminNavigationMiddleware:
    """Keep verified A+ app admins inside one focused Book management shell."""

    DRAWER_MARKER = '<a href="/verwaltung/logout/"><span>↪</span>Logout</a>'
    APP_NAV = '''<div class="app-nav-label">A+ APP</div>
    <a href="/verwaltung/app/wallet/"><span>€</span>A+ Wallet</a>
    <a href="/verwaltung/app/reviews/"><span>★</span>Google Bewertungen</a>
    <a href="/verwaltung/app/referrals/"><span>↗</span>Empfehlungen</a>
    '''
    STYLE = '''<style id="aplus-app-nav-style">
    .sb-drawer-nav .app-nav-label{padding:15px 16px 6px;font-size:10px;font-weight:800;letter-spacing:.16em;color:#9b9386}
    .sb-drawer-nav .app-nav-label+ a{margin-top:1px}
    </style>'''

    REMOVE = (
        '<a href="#uebersicht"><span>▦</span>Dashboard</a>',
        '<button type="button" data-open-note><span>✎</span>Notizen</button>',
        '<a href="#einstellungen"><span>⚙</span>Einstellungen</a>',
        '<a href="#information"><span>ⓘ</span>Information</a>',
        '<a href="#uebersicht">Übersicht</a>',
        '<a href="#einstellungen">Einstellungen</a>',
    )

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

        # App-management pages already own their exact focused drawer. Never inject
        # another A+ block into them.
        is_app_management = request.path.startswith('/verwaltung/app/') and not request.path.startswith('/verwaltung/app-sso/')

        for marker in self.REMOVE:
            html = html.replace(marker, '')
        html = html.replace('<a href="#kunden"><span>♙</span>Kunden</a>', '<a href="#kunden"><span>▤</span>Patientenakten</a>')
        html = html.replace('<a href="#kunden">Kunden</a>', '<a href="#kunden">Patientenakten</a>')

        if not is_app_management and 'href="/verwaltung/app/wallet/"' not in html and self.DRAWER_MARKER in html:
            html = html.replace(self.DRAWER_MARKER, self.APP_NAV + self.DRAWER_MARKER, 1)
        if not is_app_management and 'href="/verwaltung/app/wallet/"' not in html and '</nav>' in html:
            # Desktop nav has no logout marker. Add one compact App entry after
            # Patientenakten; the drawer remains the full three-item A+ menu.
            desktop = '<a href="#kunden">Patientenakten</a>'
            if desktop in html:
                html = html.replace(desktop, desktop + '<a href="/verwaltung/app/wallet/">A+ Wallet</a>', 1)

        if '</head>' in html and 'id="aplus-app-nav-style"' not in html:
            html = html.replace('</head>', self.STYLE + '</head>', 1)
        response.content = html.encode(response.charset or 'utf-8')
        if response.has_header('Content-Length'):
            response['Content-Length'] = str(len(response.content))
        return response
