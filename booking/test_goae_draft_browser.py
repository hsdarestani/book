from importlib.util import find_spec
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings


@skipUnless(find_spec('playwright'), 'Chromium browser regression')
@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class GoaeDraftBrowserTests(StaticLiveServerTestCase):
    @patch('booking.app_management_views._billing_api')
    def test_pdf_button_downloads_standalone_invoice(self, billing):
        from io import BytesIO
        from reportlab.pdfgen.canvas import Canvas
        from playwright.sync_api import expect, sync_playwright

        billing.return_value = {'ok': True, 'customers': [{'id': 42, 'name': 'Synthetic Patient'}],
                                'treatments': {'hyaluron': ['2442', '1', '5']}}
        admin = get_user_model().objects.create_user(username='pdf-browser-fixture', is_staff=True)
        self.client.force_login(admin)
        output = BytesIO()
        canvas = Canvas(output)
        canvas.drawString(48, 740, 'Synthetic invoice document')
        canvas.save()
        pdf = output.getvalue()
        calls = []

        def intercept(route):
            request = route.request
            if request.url == self.live_server_url + '/verwaltung/api/goae-quote/':
                route.fulfill(json={'ok': True, 'total_cents': 26000, 'tax_cents': 0, 'items': []})
            elif request.url == self.live_server_url + '/verwaltung/api/goae-pdf-preview/':
                calls.append(request.post_data_json)
                route.fulfill(status=200, content_type='application/pdf', body=pdf)
            elif request.url.startswith(self.live_server_url + '/'):
                route.continue_()
            else:
                route.abort()

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context(accept_downloads=True)
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                                  'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                                  'url': self.live_server_url}])
            context.route('**/*', intercept)
            page = context.new_page()
            page.add_init_script('window.print = () => {throw new Error("Browser printing is forbidden")};')
            page.goto(self.live_server_url + '/verwaltung/app/invoices/', wait_until='load')
            page.locator('#goae-rechnung > details > summary').click()
            page.locator('[data-mlr-details]').evaluate('(details) => { details.open = true }')
            page.locator('.clinic-patient-trigger').click()
            page.locator('.clinic-patient-option').first.click()
            page.locator('[data-material]').fill('0,00')
            for checkbox in page.locator('[data-g="clinical_confirmed"]').all():
                checkbox.check()
            with page.expect_download() as event:
                page.locator('[data-print-simulation]').click()
            download = event.value
            self.assertEqual(download.suggested_filename, 'GOAE-Rechnungsentwurf.pdf')
            self.assertEqual(download.path().read_bytes(), pdf)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]['target_total_cents'], 26000)
            expect(page.locator('[data-goae-feedback]')).to_contain_text('heruntergeladen')
            browser.close()

    @patch('booking.app_management_views._billing_api')
    def test_lost_draft_response_allows_same_key_retry(self, billing):
        from playwright.sync_api import expect, sync_playwright

        billing.return_value = {'ok': True, 'customers': [{'id': 42, 'name': 'Synthetic Patient'}],
                                'treatments': {'hyaluron': ['2442', '1', '5']}}
        admin = get_user_model().objects.create_user(username='goae-browser-fixture', is_staff=True)
        self.client.force_login(admin)
        path = '/verwaltung/app/invoices/'
        requests = []
        quotes = []
        quote_path = '/verwaltung/api/goae-quote/'

        def intercept(route):
            request = route.request
            if request.url == self.live_server_url + quote_path and request.method == 'POST':
                quotes.append(request.post_data)
                route.fulfill(json={'ok': True, 'total_cents': 26000, 'tax_cents': 0, 'items': []})
            elif request.url == self.live_server_url + '/verwaltung/api/goae-patient-search/':
                route.fulfill(json={'ok': True, 'patients': [{'id': 84, 'name': 'Remote Synthetic'}]})
            elif request.url == self.live_server_url + path and request.method == 'POST':
                requests.append(request.post_data)
                if len(requests) == 1:
                    route.abort()
                else:
                    route.fulfill(json={'ok': True, 'location': path + '?notice=goae_draft'})
            elif request.url.startswith(self.live_server_url + '/'):
                route.continue_()
            else:
                route.abort()

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context()
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                                  'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                                  'url': self.live_server_url}])
            context.route('**/*', intercept)
            page = context.new_page()
            page.goto(self.live_server_url + path, wait_until='load')
            page.locator('#goae-rechnung > details > summary').click()
            page.locator('[data-mlr-details]').evaluate('(details) => { details.open = true }')
            page.locator('.clinic-patient-trigger').click()
            page.locator('[data-filter-patient-select=goaePatient]').fill('Synthetic Remote')
            expect(page.locator('[data-patient-search-status=goaePatient]')).to_contain_text('1 passende Patienten')
            page.locator('.clinic-patient-option').first.click()
            expect(page.locator('#goaePatient')).to_have_value('84')
            page.locator('[data-material]').fill('0,00')
            for item in page.locator('[data-g="clinical_confirmed"]').all():
                item.check()
            save = page.locator('.mlr-save')
            save.click()
            message = page.locator('[data-goae-feedback]')
            expect(message).to_contain_text('Speicherung konnte nicht bestätigt werden.')
            expect(save).to_be_enabled()
            self.assertEqual(len(requests), 1)
            save.click()
            page.wait_for_url(self.live_server_url + path + '?notice=goae_draft', timeout=8000)
            browser.close()
        self.assertEqual(len(quotes), 1)
        self.assertEqual(len(requests), 2)
        ids = [body.split('name="draft_request_id"\r\n\r\n')[1].split('\r\n')[0] for body in requests]
        self.assertEqual(ids[0], ids[1])
