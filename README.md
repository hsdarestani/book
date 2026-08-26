# A+esthetic Booking

Eigenständiger Buchungsdienst für A+esthetic unter `book.a-esthetic.de`.

## Architektur

- Django 5
- PostgreSQL in Produktion, SQLite für lokale Entwicklung und Tests
- Öffentliche deutsche Buchungsoberfläche
- API für Webseite und spätere Mobile-App-Integration
- Verwaltung über eine eigene Übersichtsseite plus gebrandete Django-Verwaltung
- Verfügbarkeitslogik mit Arbeitszeiten, Abwesenheiten, Puffern und Überschneidungsschutz
- Idempotente Terminbuchung gegen versehentliche Doppelübermittlungen

## Lokal starten

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_booking
python manage.py createsuperuser
python manage.py runserver
```

Buchung: `http://127.0.0.1:8000/`  
Verwaltung: `http://127.0.0.1:8000/verwaltung/`

## API

- `GET /api/health/`
- `GET /api/services/`
- `GET /api/staff/?service_id=...`
- `GET /api/availability/?service_id=...&staff_id=...&date=YYYY-MM-DD`
- `POST /api/appointments/`

`POST /api/appointments/` unterstützt `Idempotency-Key`, damit dieselbe Anfrage nicht doppelt angelegt wird.

## Produktion

Der Workflow `.github/workflows/ci-deploy.yml` testet jeden Push auf `main` und deployt anschließend per SSH mit den Repository-Secrets `HOST` und `PASS`. Auf dem Server werden PostgreSQL, Gunicorn, systemd und Nginx verwendet. Die Anwendung läuft intern auf `127.0.0.1:8017`.

Die produktive Umgebungsdatei liegt serverseitig unter `/etc/aesthetic-book.env` und wird nicht im Repository gespeichert. SMTP kann dort über `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` und `BOOKING_NOTIFICATION_EMAIL` aktiviert werden.

Beim ersten Deployment wird ein zufälliges Administrationskennwort erzeugt und nur serverseitig in `/root/aesthetic-book-admin.txt` gespeichert.
