"""Allow only the two additive SimplyBook migrations during rollout."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

executor = MigrationExecutor(connection)
executor.loader.check_consistent_history(connection)
assert ("booking", "0034_patient_form_notification_read") in executor.loader.applied_migrations
allowed = {("booking", "0035_appointment_returning_answer"), ("booking", "0036_simplybook_remote_end")}
plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
assert all(not backwards and (migration.app_label, migration.name) in allowed
           for migration, backwards in plan)
