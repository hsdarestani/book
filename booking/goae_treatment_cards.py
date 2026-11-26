"""Presentation groups only; never derive tariff mappings from booking names.

The four existing clinically reviewed proposal families remain separate from
the booking identities. Exact known aliases consolidate the visible cards;
unknown names remain available for individual GOÄ entry and clinical review.
"""
import re
import unicodedata


def _normalize(value):
    value = unicodedata.normalize('NFKC', str(value)).casefold()
    return ' '.join(re.findall(r'\w+', value))


_GROUPS = (
    ('botox', 'Botox', 'Faltenbehandlung', '✳', ('Botox', 'Botox Neupatient', 'Botox Bestandspatient', 'Botox-Behandlung', 'Botox-Behandlung (Neupatient)', 'Botox-Behandlung (Bestandspatient)')),
    ('hyaluron', 'Hyaluron', 'Filler', '◉', ('Hyaluron', 'Hyaluronsäure-Behandlung', 'Hyaluronsäure-Behandlungen')),
    ('prp', 'PRP', 'Eigenblut', '♧', ('PRP', 'PRP-Behandlung', 'Eigenblutbehandlung')),
    ('lipolysis', 'Lipolyse', 'Injektionslipolyse', '◎', ('Lipolyse', 'Injektionslipolyse', 'Lipolyse-Injektion')),
    ('laser', 'Laser-Haarentfernung', '', '◇', ('Laser-Haarentfernung', 'Dauerhafte Haarentfernung (Alexandrit - Nd:YAG)', 'Dauerhafte Haarentfernung')),
    ('rf', 'RF-Microneedling', '', '◇', ('RF-Microneedling', 'RF Microneedling')),
    ('infusion', 'Infusionstherapie', '', '◇', ('Infusionstherapie', 'Infusionstherapien')),
    ('skinbooster', 'Skinbooster', '', '◇', ('Skinbooster', 'Skinbooster-Unterspritzung')),
    ('consultation', 'Erstberatung', '', '◇', ('Erstberatung', 'Ästhetische Erstberatung')),
    ('followup', 'Kontrolltermin', '', '◇', ('Kontrolltermin', 'Kontrolle')),
    ('body', 'Body-Contouring', '', '◇', ('Body-Contouring', 'Body-Contouring (TempSure)')),
)
_ALIASES = {_normalize(name): group[0] for group in _GROUPS for name in group[4]}
_PRESETS = {'botox', 'hyaluron', 'prp', 'lipolysis'}


def treatment_cards(services, treatment_map):
    """Return a single deduplicated UI list without mutating any booking row."""
    found = {}
    for item in services:
        name = item['name'].strip()
        key = _ALIASES.get(_normalize(name), 'service:' + _normalize(name))
        found.setdefault(key, name)
    cards = []
    for key, title, subtitle, icon, _aliases in _GROUPS:
        if key in found or key in _PRESETS:
            # Family aliases are NOT approval for the actual billed positions.
            preset = key if key in _PRESETS and treatment_map.get(key) else ''
            cards.append(dict(key=key, title=title, subtitle=subtitle, icon=icon, preset=preset))
        found.pop(key, None)
    for key, title in found.items():
        cards.append(dict(key=key, title=title, subtitle='', icon='◇', preset=''))
    return cards
