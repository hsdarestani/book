class APlusAdminNavigationMiddleware:
    """Keep verified A+ app admins inside one consistent Book management shell."""

    LUXURY_ASSETS = '''
<link rel="stylesheet" href="/static/booking/admin-luxury-v2.css?v=20260907-v2" data-aplus-luxury>
<script defer src="/static/booking/admin-luxury-v2.js?v=20260907-v2" data-aplus-luxury></script>
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
