"""Refuse rollout unless the live Book schema is already current."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
e = MigrationExecutor(connection)
e.loader.check_consistent_history(connection)
assert ("booking", "0034_patient_form_notification_read") in e.loader.applied_migrations
assert not e.migration_plan(e.loader.graph.leaf_nodes())
