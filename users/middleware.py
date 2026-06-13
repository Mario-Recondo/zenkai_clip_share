"""Idle-session auto-logout.

Logs an authenticated user out after a period of inactivity. Any request resets
the clock (we treat every request as activity, including background polling such
as clip-status.js). Enforcement is purely server-side: on the first request past
the idle limit the session is flushed and the user is redirected to the login
page with ``?timeout=1`` so the template can explain why.

Idle state lives in the session as ``last_activity`` (epoch seconds). To avoid a
session-store write on *every* request (sessions are DB-backed), the timestamp is
only re-stamped once it is older than ``STAMP_THROTTLE_SECONDS`` — a 60s write
granularity that's invisible against a 20-minute window.
"""

import time

from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse

# Re-stamp the activity timestamp at most this often (seconds). Bounds session
# DB writes to ~one per minute per active user instead of one per request.
STAMP_THROTTLE_SECONDS = 60

# Fallback if SESSION_IDLE_TIMEOUT is not configured (seconds) — 20 minutes.
DEFAULT_IDLE_TIMEOUT = 1200

SESSION_KEY = 'last_activity'


class IdleLogoutMiddleware:
    """Flush an authenticated session after SESSION_IDLE_TIMEOUT of inactivity."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            idle_limit = getattr(settings, 'SESSION_IDLE_TIMEOUT', DEFAULT_IDLE_TIMEOUT)
            now = time.time()
            last = request.session.get(SESSION_KEY)

            # The stored stamp trails real activity by up to STAMP_THROTTLE_SECONDS
            # (we only write it that often). Add that slack to the limit so we never
            # log someone out *before* idle_limit of genuine inactivity — we'd rather
            # keep them in up to ~60s longer than cut them off early.
            if last is not None and now - last > idle_limit + STAMP_THROTTLE_SECONDS:
                logout(request)
                return redirect(f"{reverse('login')}?timeout=1")

            # Throttled re-stamp: only touch the session (and incur a write) when the
            # timestamp is missing or older than the throttle window.
            if last is None or now - last > STAMP_THROTTLE_SECONDS:
                request.session[SESSION_KEY] = now

        return self.get_response(request)
