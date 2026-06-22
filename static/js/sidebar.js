/*
 * Side-navbar behaviour.
 *
 * Desktop: the in-rail toggle collapses the sidebar to an icon rail. The state
 * is persisted in localStorage and pre-applied to <html> before first paint by
 * an inline script in base.html, so it survives full-page navigations without a
 * flash.
 *
 * Mobile (< 1024px): the header burger opens an off-canvas drawer. It closes on
 * backdrop tap, Escape, tapping a nav link, or toggling the burger again. Focus
 * moves into the drawer on open, is trapped while open, and returns to the
 * burger on close.
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'zenkai:sidebar-collapsed';
    var root = document.documentElement;
    var sidebar = document.getElementById('app-sidebar');
    if (!sidebar) return;

    var desktopToggle = sidebar.querySelector('[data-sidebar-toggle]');
    var openBtn = document.querySelector('[data-sidebar-open]');
    var backdrop = document.querySelector('[data-sidebar-close]');

    // ---- Desktop collapse (persisted) ----
    function syncToggleAria() {
        if (!desktopToggle) return;
        var collapsed = root.classList.contains('sidebar-collapsed');
        desktopToggle.setAttribute('aria-expanded', String(!collapsed));
        desktopToggle.setAttribute('aria-label', collapsed ? 'Expand navigation' : 'Collapse navigation');
    }
    syncToggleAria();

    if (desktopToggle) {
        desktopToggle.addEventListener('click', function () {
            var collapsed = root.classList.toggle('sidebar-collapsed');
            try { localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0'); } catch (e) {}
            syncToggleAria();
        });
    }

    // ---- Mobile drawer ----
    function isOpen() {
        return root.classList.contains('sidebar-open');
    }

    function focusableItems() {
        return sidebar.querySelectorAll('a[href], button:not([disabled])');
    }

    function openDrawer() {
        root.classList.add('sidebar-open');
        if (openBtn) openBtn.setAttribute('aria-expanded', 'true');
        document.addEventListener('keydown', onKeydown);
        var items = focusableItems();
        if (items.length) items[0].focus();
    }

    function closeDrawer() {
        root.classList.remove('sidebar-open');
        document.removeEventListener('keydown', onKeydown);
        if (openBtn) {
            openBtn.setAttribute('aria-expanded', 'false');
            openBtn.focus();
        }
    }

    function onKeydown(e) {
        if (e.key === 'Escape') {
            closeDrawer();
            return;
        }
        if (e.key === 'Tab') {
            var items = focusableItems();
            if (!items.length) return;
            var first = items[0];
            var last = items[items.length - 1];
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        }
    }

    if (openBtn) {
        openBtn.addEventListener('click', function () {
            if (isOpen()) closeDrawer();
            else openDrawer();
        });
    }

    if (backdrop) {
        backdrop.addEventListener('click', closeDrawer);
    }

    // Tapping a nav link navigates; close the drawer so it isn't left open
    // behind the next page (also covers in-page anchors).
    sidebar.addEventListener('click', function (e) {
        if (isOpen() && e.target.closest('.sidebar__item')) {
            closeDrawer();
        }
    });

    // If the viewport grows to desktop while the drawer is open, tidy up.
    var mq = window.matchMedia('(min-width: 1024px)');
    function onBreakpoint() {
        if (mq.matches && isOpen()) closeDrawer();
    }
    if (mq.addEventListener) mq.addEventListener('change', onBreakpoint);
    else if (mq.addListener) mq.addListener(onBreakpoint);
})();
