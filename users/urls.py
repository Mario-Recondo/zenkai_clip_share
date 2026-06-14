from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path(
        "dashboard/",
        RedirectView.as_view(pattern_name="clip-list", permanent=False),
        name="dashboard",
    ),
    path("register/", views.register, name="register"),
    path("avatar/", views.avatar_update, name="avatar-update"),
    # Idle-timeout support: keepalive ping + countdown-elapsed logout.
    path("session/ping/", views.session_ping, name="session-ping"),
    path(
        "session/timeout-logout/",
        views.session_timeout_logout,
        name="session-timeout-logout",
    ),
]
