// Account dropdown + change-avatar modal.
//
// The dropdown is a click-to-toggle menu (closes on outside-click / Escape).
// "Change avatar" opens a modal whose file picker shows a live preview instead
// of a filename; saving POSTs via fetch and swaps the nav thumbnail in place,
// no page reload. The CSRF token rides along in the form's FormData.
(function () {
    'use strict';

    const menu = document.querySelector('[data-account-menu]');
    if (!menu) return;

    const trigger = menu.querySelector('[data-account-trigger]');
    const panel = menu.querySelector('[data-account-panel]');

    // ---- Dropdown ----
    function openMenu() {
        panel.hidden = false;
        trigger.setAttribute('aria-expanded', 'true');
        document.addEventListener('click', onDocClick);
        document.addEventListener('keydown', onMenuKey);
    }

    function closeMenu() {
        panel.hidden = true;
        trigger.setAttribute('aria-expanded', 'false');
        document.removeEventListener('click', onDocClick);
        document.removeEventListener('keydown', onMenuKey);
    }

    function onDocClick(e) {
        if (!menu.contains(e.target)) closeMenu();
    }

    function onMenuKey(e) {
        if (e.key === 'Escape') {
            closeMenu();
            trigger.focus();
        }
    }

    trigger.addEventListener('click', function (e) {
        e.stopPropagation();
        if (panel.hidden) openMenu();
        else closeMenu();
    });

    // ---- Change-avatar modal ----
    const modal = document.getElementById('avatar-modal');
    const form = document.getElementById('avatar-form');
    const input = document.getElementById('avatar-input');
    const preview = document.getElementById('avatar-preview');
    const errorBox = document.getElementById('avatar-error');
    const saveBtn = form ? form.querySelector('[data-avatar-save]') : null;
    const navAvatar = document.getElementById('nav-avatar');
    const openBtn = menu.querySelector('[data-avatar-open]');

    let previewUrl = null;

    function showError(msg) {
        errorBox.textContent = msg;
        errorBox.hidden = !msg;
    }

    function resetPreviewUrl() {
        if (previewUrl) {
            URL.revokeObjectURL(previewUrl);
            previewUrl = null;
        }
    }

    function openModal() {
        closeMenu();
        showError('');
        modal.hidden = false;
        document.addEventListener('keydown', onModalKey);
    }

    function closeModal() {
        modal.hidden = true;
        form.reset();
        resetPreviewUrl();
        showError('');
        saveBtn.disabled = true;
        document.removeEventListener('keydown', onModalKey);
    }

    function onModalKey(e) {
        if (e.key === 'Escape') closeModal();
    }

    if (openBtn) openBtn.addEventListener('click', openModal);

    modal.addEventListener('click', function (e) {
        // Click on the backdrop (outside the card) closes the modal.
        if (e.target === modal) closeModal();
    });

    const cancelBtn = form.querySelector('[data-avatar-cancel]');
    cancelBtn.addEventListener('click', closeModal);

    input.addEventListener('change', function () {
        const file = input.files && input.files[0];
        showError('');
        resetPreviewUrl();
        if (!file) {
            saveBtn.disabled = true;
            return;
        }
        previewUrl = URL.createObjectURL(file);
        preview.innerHTML =
            '<img src="' + previewUrl + '" alt="" class="size-16 shrink-0 rounded-full object-cover">';
        saveBtn.disabled = false;
    });

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        showError('');
        saveBtn.disabled = true;

        fetch(form.action, {
            method: 'POST',
            body: new FormData(form),
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        })
            .then(function (res) {
                return res.json().then(function (data) {
                    return { ok: res.ok, data: data };
                });
            })
            .then(function (result) {
                if (!result.ok) {
                    showError(result.data.error || 'Could not update avatar.');
                    saveBtn.disabled = false;
                    return;
                }
                // Swap the nav thumbnail live (replaces image or letter badge).
                navAvatar.innerHTML =
                    '<img src="' + result.data.url + '" alt="" class="size-8 shrink-0 rounded-full object-cover">';
                closeModal();
            })
            .catch(function () {
                showError('Something went wrong. Please try again.');
                saveBtn.disabled = false;
            });
    });
})();
