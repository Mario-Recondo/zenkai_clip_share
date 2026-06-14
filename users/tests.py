import time

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from users.middleware import STAMP_THROTTLE_SECONDS

# DEBUG=False under tests turns on the production HTTPS redirect; disable it so the
# test client's http requests aren't 301'd before our middleware runs. Pin the idle
# limit to a clear value so the timing math in these tests is obvious.
IDLE_LIMIT = 1000
_TEST_OVERRIDES = override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_IDLE_TIMEOUT=IDLE_LIMIT,
)

# First request past this (idle limit + throttle slack) triggers logout.
DEADLINE = IDLE_LIMIT + STAMP_THROTTLE_SECONDS

LOGIN_KEY = '_auth_user_id'
ACTIVITY_KEY = 'last_activity'


@_TEST_OVERRIDES
class IdleLogoutMiddlewareTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='gamer', password='pw12345!')
        # A protected page that exercises an authenticated request.
        self.url = reverse('clip-list')

    def _set_activity(self, seconds_ago):
        """Pre-seed last_activity to a point in the past, then persist the session."""
        session = self.client.session
        session[ACTIVITY_KEY] = time.time() - seconds_ago
        session.save()

    def test_fresh_session_stamps_activity_and_allows(self):
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(ACTIVITY_KEY, self.client.session)

    def test_idle_past_limit_logs_out_and_redirects(self):
        self.client.force_login(self.user)
        self._set_activity(DEADLINE + 5)
        resp = self.client.get(self.url)
        # Bounced to login with the inactivity flag, and the session is flushed.
        self.assertRedirects(resp, '/login/?timeout=1')
        self.assertNotIn(LOGIN_KEY, self.client.session)

    def test_active_within_limit_stays_logged_in(self):
        self.client.force_login(self.user)
        self._set_activity(100)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(LOGIN_KEY, self.client.session)

    def test_within_throttle_slack_not_logged_out_early(self):
        # Between the idle limit and the +throttle slack: must NOT log out yet, since
        # the stored stamp can trail real activity by up to the throttle window.
        self.client.force_login(self.user)
        self._set_activity(IDLE_LIMIT + (STAMP_THROTTLE_SECONDS // 2))
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(LOGIN_KEY, self.client.session)

    def test_recent_activity_is_not_rewritten(self):
        # Within the throttle window → middleware must skip the session write.
        self.client.force_login(self.user)
        stamp = time.time() - (STAMP_THROTTLE_SECONDS // 2)
        session = self.client.session
        session[ACTIVITY_KEY] = stamp
        session.save()
        self.client.get(self.url)
        self.assertEqual(self.client.session[ACTIVITY_KEY], stamp)

    def test_stale_activity_is_refreshed(self):
        # Older than the throttle window but within the idle limit → re-stamped.
        self.client.force_login(self.user)
        stamp = time.time() - (STAMP_THROTTLE_SECONDS + 30)
        session = self.client.session
        session[ACTIVITY_KEY] = stamp
        session.save()
        self.client.get(self.url)
        self.assertGreater(self.client.session[ACTIVITY_KEY], stamp)

    def test_anonymous_request_is_unaffected(self):
        # No auth: middleware must no-op (no crash, no timeout redirect, no stamp).
        resp = self.client.get(reverse('register'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(ACTIVITY_KEY, self.client.session)


@_TEST_OVERRIDES
class LoginTimeoutBannerTests(TestCase):
    def test_banner_shown_with_timeout_param(self):
        resp = self.client.get('/login/?timeout=1')
        self.assertContains(resp, 'logged out due to inactivity')

    def test_banner_absent_without_param(self):
        resp = self.client.get(reverse('login'))
        self.assertNotContains(resp, 'logged out due to inactivity')


@_TEST_OVERRIDES
class SessionKeepaliveTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='gamer', password='pw12345!')

    def test_ping_requires_login(self):
        resp = self.client.get(reverse('session-ping'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp['Location'])

    def test_ping_returns_ok_and_refreshes_clock(self):
        self.client.force_login(self.user)
        # Seed a stale-but-not-expired stamp; the ping should re-stamp it.
        stamp = time.time() - (STAMP_THROTTLE_SECONDS + 30)
        session = self.client.session
        session[ACTIVITY_KEY] = stamp
        session.save()

        resp = self.client.get(reverse('session-ping'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'ok': True})
        self.assertGreater(self.client.session[ACTIVITY_KEY], stamp)

    def test_ping_past_deadline_is_logged_out(self):
        self.client.force_login(self.user)
        self._set_idle_past_deadline()
        resp = self.client.get(reverse('session-ping'))
        # Middleware intercepts before the view: bounced to login, session gone.
        self.assertRedirects(resp, '/login/?timeout=1')
        self.assertNotIn(LOGIN_KEY, self.client.session)

    def _set_idle_past_deadline(self):
        session = self.client.session
        session[ACTIVITY_KEY] = time.time() - (DEADLINE + 5)
        session.save()


@_TEST_OVERRIDES
class SessionTimeoutLogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='gamer', password='pw12345!')

    def test_post_logs_out_and_redirects_with_notice(self):
        self.client.force_login(self.user)
        resp = self.client.post(reverse('session-timeout-logout'))
        self.assertRedirects(resp, '/login/?timeout=1')
        self.assertNotIn(LOGIN_KEY, self.client.session)

    def test_get_not_allowed(self):
        # GET must not show the notice without ending a session.
        self.client.force_login(self.user)
        resp = self.client.get(reverse('session-timeout-logout'))
        self.assertEqual(resp.status_code, 405)
        self.assertIn(LOGIN_KEY, self.client.session)


@_TEST_OVERRIDES
class IdleWarningModalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='gamer', password='pw12345!')

    def test_modal_and_config_rendered_for_authenticated_user(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('clip-list'))
        self.assertContains(resp, 'id="idle-modal"')
        # Config carries the configured timings in milliseconds.
        self.assertContains(resp, f'data-timeout="{IDLE_LIMIT * 1000}"')
        # Login redirect is resolved server-side, not hardcoded in JS.
        self.assertContains(resp, 'data-login-url="/login/?timeout=1"')
        self.assertContains(resp, 'js/idle-timeout.js')

    def test_modal_absent_for_anonymous_user(self):
        resp = self.client.get(reverse('login'))
        self.assertNotContains(resp, 'id="idle-modal"')
