from django.apps import AppConfig
from django.db.models.signals import post_migrate


class ClipsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "clips"

    def ready(self):
        # Register the scheduled orphan-media cleanup on post_migrate. A full
        # migrate emits this after every app is migrated, so django_q's table
        # normally exists — but a targeted/selective migrate (e.g. `migrate clips`
        # on a fresh DB, where clips precedes django_q in INSTALLED_APPS) can fire
        # it first. The handler guards for that. Idempotent: re-runs refresh the
        # row, never duplicate it.
        post_migrate.connect(_ensure_orphan_reaper_schedule, sender=self)


def _ensure_orphan_reaper_schedule(sender, using=None, **kwargs):
    """Ensure the daily orphan-media reaper schedule exists (no new infra —
    django-q2 already runs scheduled jobs via the qcluster worker).

    Skips silently if django_q isn't installed or its table hasn't been created
    yet on this database, so a selective migrate can't fail here — a later full
    migrate re-fires this and registers the schedule.
    """
    from django.apps import apps as django_apps
    from django.db import DEFAULT_DB_ALIAS, connections

    if not django_apps.is_installed("django_q"):
        return

    from django_q.models import Schedule

    connection = connections[using or DEFAULT_DB_ALIAS]
    if Schedule._meta.db_table not in connection.introspection.table_names():
        return

    Schedule.objects.using(connection.alias).update_or_create(
        name="reap-orphan-media",
        defaults={
            "func": "clips.services.reap_orphan_media",
            "schedule_type": Schedule.DAILY,
            "repeats": -1,  # run indefinitely
        },
    )
