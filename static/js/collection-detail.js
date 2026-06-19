// Collection detail page: gear (management) menu, invite modal, and the
// Discord-style member list (desktop column with persisted collapse, mobile
// off-canvas drawer).
//
// Layout state lives in two attributes on .collection-layout so one value can't
// mean different things per breakpoint:
//   data-members-collapsed  -> desktop column hidden (persisted in localStorage)
//   data-drawer-open        -> mobile drawer slid in (never persisted)
(function () {
    'use strict';

    const desktop = window.matchMedia('(min-width: 64rem)');

    // ---- Gear dropdown ----
    const menu = document.querySelector('[data-collection-menu]');
    if (menu) {
        const trigger = menu.querySelector('[data-collection-trigger]');
        const panel = menu.querySelector('[data-collection-panel]');

        const onDocClick = (e) => {
            if (!menu.contains(e.target)) closeMenu();
        };
        const onKey = (e) => {
            if (e.key === 'Escape') {
                closeMenu();
                trigger.focus();
            }
        };

        function openMenu() {
            panel.hidden = false;
            trigger.setAttribute('aria-expanded', 'true');
            document.addEventListener('click', onDocClick);
            document.addEventListener('keydown', onKey);
        }
        function closeMenu() {
            panel.hidden = true;
            trigger.setAttribute('aria-expanded', 'false');
            document.removeEventListener('click', onDocClick);
            document.removeEventListener('keydown', onKey);
        }

        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            if (panel.hidden) openMenu();
            else closeMenu();
        });

        // ---- Invite modal (opened from a gear item) ----
        const modal = document.getElementById('invite-modal');
        const openInvite = menu.querySelector('[data-invite-open]');
        if (modal && openInvite) {
            const input = modal.querySelector('[name="username"]');
            const onModalKey = (e) => {
                if (e.key === 'Escape') closeModal();
            };

            function openModal() {
                closeMenu();
                modal.hidden = false;
                document.addEventListener('keydown', onModalKey);
                if (input) input.focus();
            }
            function closeModal() {
                modal.hidden = true;
                document.removeEventListener('keydown', onModalKey);
            }

            openInvite.addEventListener('click', openModal);
            // Backdrop click (outside the card) closes.
            modal.addEventListener('click', (e) => {
                if (e.target === modal) closeModal();
            });
            modal
                .querySelectorAll('[data-invite-cancel]')
                .forEach((btn) => btn.addEventListener('click', closeModal));
        }
    }

    // ---- Member list (column + drawer) ----
    const layout = document.querySelector('[data-collection-layout]');
    if (!layout) return;

    const STORAGE_KEY = 'zenkai:collection-members-collapsed';
    const toggle = document.querySelector('[data-members-toggle]');
    const backdrop = layout.querySelector('[data-members-backdrop]');
    const closeBtn = layout.querySelector('[data-members-close]');

    function isCollapsed() {
        try {
            return localStorage.getItem(STORAGE_KEY) === '1';
        } catch (e) {
            return false;
        }
    }
    function persistCollapsed(collapsed) {
        try {
            localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0');
        } catch (e) {
            /* private mode: preference just won't stick */
        }
    }

    function syncAria() {
        if (!toggle) return;
        const expanded = desktop.matches
            ? layout.getAttribute('data-members-collapsed') !== 'true'
            : layout.getAttribute('data-drawer-open') === 'true';
        toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    }

    // Apply the persisted desktop preference on load. The mobile drawer always
    // starts closed (the markup ships data-drawer-open="false").
    layout.setAttribute('data-members-collapsed', isCollapsed() ? 'true' : 'false');
    syncAria();

    const onDrawerKey = (e) => {
        if (e.key === 'Escape') closeDrawer();
    };
    function openDrawer() {
        layout.setAttribute('data-drawer-open', 'true');
        document.addEventListener('keydown', onDrawerKey);
        syncAria();
    }
    function closeDrawer() {
        layout.setAttribute('data-drawer-open', 'false');
        document.removeEventListener('keydown', onDrawerKey);
        syncAria();
    }

    if (toggle) {
        toggle.addEventListener('click', () => {
            if (desktop.matches) {
                const collapsed =
                    layout.getAttribute('data-members-collapsed') === 'true';
                layout.setAttribute(
                    'data-members-collapsed',
                    collapsed ? 'false' : 'true'
                );
                persistCollapsed(!collapsed);
                syncAria();
            } else if (layout.getAttribute('data-drawer-open') === 'true') {
                closeDrawer();
            } else {
                openDrawer();
            }
        });
    }
    if (backdrop) backdrop.addEventListener('click', closeDrawer);
    if (closeBtn) closeBtn.addEventListener('click', closeDrawer);

    // Crossing the breakpoint: close any open drawer so the desktop column
    // isn't left in a drawer-open state (and vice versa). The desktop column
    // visibility is driven by its own persisted attribute, untouched here.
    const onBreakpoint = () => {
        if (desktop.matches) closeDrawer();
        syncAria();
    };
    if (desktop.addEventListener) desktop.addEventListener('change', onBreakpoint);
    else desktop.addListener(onBreakpoint); // older Safari
})();
