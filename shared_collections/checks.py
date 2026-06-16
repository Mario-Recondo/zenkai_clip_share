"""Startup guard: Collections requires a row-locking database backend.

The safe-delete / add-clip concurrency guarantees (see collection_plan.md) depend on
real ``SELECT ... FOR UPDATE`` row locks. SQLite silently ignores ``select_for_update``,
so the destructive add/delete race is NOT actually closed there and any concurrency
test run on SQLite passes while proving nothing. We therefore fail closed: if this app
is installed on a backend without row locking, ``manage.py check`` (and thus runserver /
migrate) errors out. This is intentional and has no opt-out — leaving it optional just
relocates the false-confidence trap.

Registered untagged so it runs on the default system-check pass (including runserver
startup), not only on database-tagged checks. It reads a static backend feature flag,
so it performs no database I/O.
"""

from django.core.checks import Error, register
from django.db import DEFAULT_DB_ALIAS, connections


@register()
def postgres_row_locking_required(app_configs, **kwargs):
    connection = connections[DEFAULT_DB_ALIAS]
    if connection.features.has_select_for_update:
        return []
    return [
        Error(
            "The 'shared_collections' (Collections) app requires a database backend "
            "that supports SELECT ... FOR UPDATE row locking (e.g. PostgreSQL); the "
            f"configured default backend ('{connection.vendor}') does not. The "
            "safe-delete and add-clip concurrency guarantees do not hold on it.",
            hint=(
                "Set DATABASE_URL to a PostgreSQL instance for development, CI, and "
                "production (SQLite is not supported while Collections is installed)."
            ),
            id="shared_collections.E001",
        )
    ]
