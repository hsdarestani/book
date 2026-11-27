import json
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from .goae_assistant import GUIDANCE


@override_settings(ALLOWED_HOSTS=['testserver'])
class GoaeAssistantTests(TestCase):
    url = '/verwaltung/api/goae-assistant/'

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.staff = get_user_model().objects.create_user('goae-assistant-staff', is_staff=True)

    def test_requires_staff_and_csrf(self):
        self.assertEqual(self.client.post(self.url, {'topic': 'entry'}, content_type='application/json').status_code, 401)
        other = get_user_model().objects.create_user('goae-assistant-patient')
        self.client.force_login(other)
        self.assertEqual(self.client.post(self.url, {'topic': 'entry'}, content_type='application/json').status_code, 403)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.staff)
        self.assertEqual(protected.post(self.url, {'topic': 'entry'}, content_type='application/json').status_code, 403)

    @patch('booking.goae_assistant.urlopen')
    @patch.dict('os.environ', {'CLOUDFLARE_ACCOUNT_ID': 'a' * 32, 'CLOUDFLARE_AI_API_TOKEN': 'test-token'})
    def test_provider_receives_only_predefined_guidance(self, remote):
        self.client.force_login(self.staff)
        rejected = self.client.post(self.url, {'topic': 'material', 'patient': 'Synthetic patient'}, content_type='application/json')
        self.assertEqual(rejected.status_code, 400)
        remote.assert_not_called()
        response = MagicMock()
        response.read.return_value = b'{"success":true,"result":{"response":"Auslage und Beleg im Formular erfassen."}}'
        remote.return_value.__enter__.return_value = response
        result = self.client.post(self.url, {'topic': 'material'}, content_type='application/json')
        self.assertTrue(result.json()['ai'])
        self.assertIn('no-store', result['Cache-Control'])
        payload = json.loads(remote.call_args.args[0].data)
        self.assertEqual(payload['messages'][-1]['content'], GUIDANCE['material'])
        self.assertNotIn('Synthetic', str(payload))

    @patch('booking.goae_assistant.explain_topic', return_value=None)
    def test_provider_failure_keeps_guidance_available(self, provider):
        self.client.force_login(self.staff)
        for _ in range(2):
            result = self.client.post(self.url, {'topic': 'factor'}, content_type='application/json')
            self.assertEqual(result.json(), {'ok': True, 'answer': GUIDANCE['factor'], 'ai': False})
        provider.assert_called_once_with('factor')
