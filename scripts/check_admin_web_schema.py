"""Check the scoped UI release without writing the production database."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

executor = MigrationExecutor(connection)
assert ("booking", "0032_appointment_treatment_duration") in executor.loader.applied_migrations
assert not executor.migration_plan(executor.loader.graph.leaf_nodes())
