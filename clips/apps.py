from django.apps import AppConfig
from django.db.models.signals import post_migrate


class ClipsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "clips"

    def ready(self):
        # Register the scheduled orphan-media cleanup after migrations run, so the
        # django_q Schedule table is guaranteed to exist. Idempotent: re-runs just
        # refresh the row, never duplicate it.
        post_migrate.connect(_ensure_orphan_reaper_schedule, sender=self)


def _ensure_orphan_reaper_schedule(sender, **kwargs):
    """Ensure the daily orphan-media reaper schedule exists (no new infra —
    django-q2 already runs scheduled jobs via the qcluster worker)."""
    from django_q.models import Schedule

    Schedule.objects.update_or_create(
        name="reap-orphan-media",
        defaults={
            "func": "clips.services.reap_orphan_media",
            "schedule_type": Schedule.DAILY,
            "repeats": -1,  # run indefinitely
        },
    )
