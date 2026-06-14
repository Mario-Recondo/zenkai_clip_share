/*
 * Client-side idle-timeout UX. The server (IdleLogoutMiddleware) is the real
 * security boundary; this just makes the timeout visible and gives the user a
 * chance to stay signed in.
 *
 * While the user is active, throttled keepalive pings keep the server-side clock
 * fresh so an active user never sees the modal. After data-warning ms of genuine
 * inactivity a countdown modal appears; if it elapses we submit a logout form.
 * During the warning, mouse/keyboard activity is ignored — only the explicit
 * buttons act — so a stray bump can't silently keep an unattended session alive.
 */
(function () {
    'use strict';

    const cfg = document.getElementById('idle-timeout');
    if (!cfg) return; // only rendered for authenticated users

    const TIMEOUT = parseInt(cfg.dataset.timeout, 10); // inactivity until logout (ms)
    const WARNING = parseInt(cfg.dataset.warning, 10); // lead time before logout (ms)
    const PING_URL = cfg.dataset.pingUrl;

    const modal = document.getElementById('idle-modal');
    const countdownEl = document.getElementById('idle-countdown');
    const stayBtn = document.getElementById('idle-stay');
    const logoutBtn = document.getElementById('idle-logout');
    const logoutForm = document.getElementById('idle-logout-form');

    // Ping at most this often while active. Kept below the active window so the
    // server stamp can't go stale, and clamped to a sane range.
    const PING_THROTTLE = Math.min(60000, Math.max(15000, (TIMEOUT - WARNING) / 2));

    let lastActivity = Date.now();
    let lastPing = 0;
    let warning = false;

    function ping() {
        lastPing = Date.now();
        fetch(PING_URL, { headers: { Accept: 'application/json' } })
            .then(function (res) {
                // Redirected/!ok means the session already died server-side.
                if (res.redirected || !res.ok) toLogin();
            })
            .catch(function () { /* transient; the 1s check still guards us */ });
    }

    function toLogin() {
        window.location.assign('/login/?timeout=1');
    }

    function logoutNow() {
        if (logoutForm) logoutForm.submit();
        else toLogin();
    }

    function onActivity() {
        if (warning) return; // during the warning only the buttons count
        lastActivity = Date.now();
        if (Date.now() - lastPing > PING_THROTTLE) ping();
    }

    function stayLoggedIn() {
        warning = false;
        modal.hidden = true;
        lastActivity = Date.now();
        ping();
    }

    function check() {
        const idle = Date.now() - lastActivity;
        if (idle >= TIMEOUT) {
            logoutNow();
            return;
        }
        if (idle >= TIMEOUT - WARNING) {
            if (!warning) {
                warning = true;
                modal.hidden = false;
            }
            countdownEl.textContent = Math.ceil((TIMEOUT - idle) / 1000);
        } else if (warning) {
            warning = false;
            modal.hidden = true;
        }
    }

    ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart'].forEach(function (evt) {
        window.addEventListener(evt, onActivity, { passive: true });
    });
    stayBtn.addEventListener('click', stayLoggedIn);
    logoutBtn.addEventListener('click', logoutNow);

    setInterval(check, 1000);
})();
