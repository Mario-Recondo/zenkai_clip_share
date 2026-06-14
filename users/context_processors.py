from django.conf import settings


def idle_timeout(request):
    """Expose idle-logout timings (in milliseconds) to templates so the
    client-side warning modal can mirror IdleLogoutMiddleware's server-side
    limit. Values are read fresh from settings so env overrides take effect."""
    return {
        "idle_timeout_ms": settings.SESSION_IDLE_TIMEOUT * 1000,
        "idle_warning_ms": getattr(settings, "SESSION_IDLE_WARNING", 120) * 1000,
    }
