import os

from django.http import HttpResponse
from django.utils.cache import patch_vary_headers


_DEFAULT_ORIGINS = {
    'https://esthetic.smarbiz.sbs',
    'https://a-esthetic.de',
    'https://www.a-esthetic.de',
    'capacitor://localhost',
    'ionic://localhost',
    'http://localhost',
    'https://localhost',
}


def _allowed_origins():
    configured = {
        value.strip()
        for value in os.getenv('BOOKING_CORS_ORIGINS', '').split(',')
        if value.strip()
    }
    return _DEFAULT_ORIGINS | configured


class MobileApiCorsMiddleware:
    """Allow the A+ app/web shell to call the booking mobile API directly.

    The mobile endpoints are bearer-token authenticated and CSRF-exempt. Keeping
    CORS scoped to /api/mobile/ lets the customer app talk straight to the
    booking service/database without routing back through the Customer Club
    server first.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        origin = request.headers.get('Origin', '').strip()
        mobile_api = request.path.startswith('/api/mobile/')
        allowed = mobile_api and origin in _allowed_origins()

        if request.method == 'OPTIONS' and allowed:
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)

        if allowed:
            response['Access-Control-Allow-Origin'] = origin
            response['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response['Access-Control-Allow-Headers'] = 'Authorization, Content-Type, Idempotency-Key'
            response['Access-Control-Max-Age'] = '86400'
            patch_vary_headers(response, ('Origin',))

        return response
