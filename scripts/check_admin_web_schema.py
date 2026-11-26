"""Require the two reviewed additive Book migrations and no other pending change."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

executor = MigrationExecutor(connection)
assert ("booking", "0032_appointment_treatment_duration") in executor.loader.applied_migrations
allowed = [
    ("booking", "0033_office_intake_assignment_lock", False),
    ("booking", "0034_patient_form_notification_read", False),
]
expected = [item for item in allowed if item[:2] not in executor.loader.applied_migrations]
actual = [(migration.app_label, migration.name, backwards)
          for migration, backwards in executor.migration_plan(executor.loader.graph.leaf_nodes())]
assert actual == expected
