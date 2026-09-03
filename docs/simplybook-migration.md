# SimplyBook migration

The migration is intentionally idempotent and preserves a private raw JSON backup on the production server.

Safety rules:
- Imported SimplyBook services are archival (`bookable=False`) and do not appear in public booking.
- Imported appointments use stable `simplybook-<booking-id>` idempotency keys.
- No customer booking emails are sent during migration.
- The source provider is kept as an isolated admin-calendar provider because SimplyBook exposes the historical records under one generic provider rather than the current individual clinicians.
- Existing local customers are matched by e-mail when possible; the complete unmerged source client payload remains in the private raw backup.

A full dry run completed before the production marker was committed.
