"""Allow only the backwards-compatible Phase A schema change."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

executor = MigrationExecutor(connection)
target = ("booking", "0032_appointment_treatment_duration")
baseline = ("booking", "0031_merge_native_and_simplybook")
assert baseline in executor.loader.applied_migrations
plan = [(migration.app_label, migration.name, backwards)
        for migration, backwards in executor.migration_plan(executor.loader.graph.leaf_nodes())]
expected = [] if target in executor.loader.applied_migrations else [(*target, False)]
assert plan == expected
