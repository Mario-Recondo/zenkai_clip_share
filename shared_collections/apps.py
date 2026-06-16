from django.apps import AppConfig


class SharedCollectionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "shared_collections"
    verbose_name = "Collections"

    def ready(self):
        # Register the row-locking (Postgres) system check.
        from . import checks  # noqa: F401
