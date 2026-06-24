from django.apps import AppConfig


class SharedCollectionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "shared_collections"
    verbose_name = "Collections"

    def ready(self):
        from clips.access import register_view_provider

        from . import checks  # noqa: F401  (row-locking / Postgres system check)
        from .permissions import grants_view_via_collection

        # Plug collection-based view access into the clip's visibility rule
        # (Clip.is_viewable_by) without clips importing this feature app.
        register_view_provider(grants_view_via_collection)
