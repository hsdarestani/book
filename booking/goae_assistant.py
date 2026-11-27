"""Page-scoped GOÄ guidance. Workers AI receives only predefined topic text."""
import json
import os
import re
from urllib.error import URLError
from urllib.request import Request, urlopen

from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .app_management_views import _local_view_only


GUIDANCE = {
    'entry': 'Behandlung wählen, Patient und Leistungsdatum im Formular ergänzen. Tatsächlich erbrachte Positionen, Auslagen und Steuerstatus prüfen. Danach die GOÄ-Berechnung prüfen und den Entwurf speichern.',
    'factor': 'Nach §§ 5 und 12 GOÄ braucht das Überschreiten des jeweiligen Schwellenwerts eine individuelle schriftliche Begründung je Leistung. Prüfen Sie die Gebührenkategorie. Oberhalb des Höchstsatzes ist eine abweichende Vereinbarung nur unter den Voraussetzungen des § 2 GOÄ möglich.',
    'material': 'Nach §§ 10 und 12 GOÄ nur tatsächlich entstandene, berechnungsfähige Auslagen ohne Pauschale erfassen. Bei einer einzelnen Auslage über 25,56 Euro Beleg oder Nachweis beifügen. Ohne Auslage 0,00 eintragen.',
    'analog': 'Nach §§ 6 und 12 GOÄ muss eine selbständige, im Verzeichnis fehlende Leistung verständlich beschrieben werden. Eine nach Art, Kosten und Zeitaufwand gleichwertige Position muss ärztlich geprüft und als entsprechende GOÄ-Ziffer ausgewiesen werden.',
    'tax': 'Die Befreiung nach § 4 Nr. 14 UStG hängt vom Zweck der Leistung ab. Den Steuerstatus und gegebenenfalls die dokumentierte medizinische Indikation fachlich prüfen.',
    'total': 'Der Wunschbetrag ist eine Orientierung. Prüfen Sie die tatsächlich erbrachten Leistungen, Faktoren und Auslagen. Bei einer Abweichung können Sie den serverseitig berechneten Betrag ausdrücklich übernehmen.',
}


def explain_topic(topic):
    account = os.getenv('CLOUDFLARE_ACCOUNT_ID', '')
    token = os.getenv('CLOUDFLARE_AI_API_TOKEN', '')
    if not token or not re.fullmatch(r'[0-9a-f]{32}', account, flags=re.I):
        return None
    remote = Request(
        f'https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/meta/llama-3.1-8b-instruct',
        data=json.dumps({
            'messages': [
                {'role': 'system', 'content': 'Schreibe eine kurze deutsche Bedienhilfe für einen GOÄ-Rechnungsentwurf. Verwende ausschließlich die vorgegebenen Fakten. Keine Ziffern, Grenzwerte, neuen Rechtsaussagen, Diagnosen oder Freigaben hinzufügen. Antworte mit höchstens zwei Sätzen ohne Markdown.'},
                {'role': 'user', 'content': GUIDANCE[topic]},
            ],
            'max_tokens': 140,
            'temperature': 0.1,
        }).encode(),
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urlopen(remote, timeout=6) as response:
            payload = json.loads(response.read(15000))
        answer = payload['result']['response']
    except (OSError, URLError, ValueError, KeyError, TypeError):
        return None
    return answer.strip() if payload.get('success') is True and isinstance(answer, str) and 0 < len(answer.strip()) <= 650 else None


@never_cache
@require_POST
def goae_assistant(request):
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'message': 'Bitte erneut im Praxismanagement anmelden.'}, status=401)
    if not request.user.is_staff or _local_view_only(request):
        return JsonResponse({'ok': False, 'message': 'Keine Berechtigung für den Rechnungsassistenten.'}, status=403)
    try:
        data = json.loads(request.body) if len(request.body) <= 256 else None
        topic = data.get('topic') if isinstance(data, dict) and data.keys() == {'topic'} else None
    except (ValueError, UnicodeError):
        topic = None
    if not isinstance(topic, str) or topic not in GUIDANCE:
        return JsonResponse({'ok': False, 'message': 'Bitte ein Thema im GOÄ-Assistenten auswählen.'}, status=400)
    key = f'goae-assistant:v1:{topic}'
    answer = cache.get(key)
    if answer is None and cache.add(f'goae-assistant:pending:{topic}', True, 10):
        answer = explain_topic(topic)
        cache.set(key, answer or '', timeout=3600 if answer else 45)
    return JsonResponse({'ok': True, 'answer': answer or GUIDANCE[topic], 'ai': bool(answer)})
