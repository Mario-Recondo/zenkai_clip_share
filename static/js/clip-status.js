/*
 * Polls the clip status endpoint for any element carrying
 * data-poll-status="<endpoint url>" while its clip transcodes.
 *
 * data-poll-mode="card" (default): patch the clip card in place — drop the
 * "Processing" badge and swap in the thumbnail when READY.
 * data-poll-mode="page": reload the page on a terminal status (used on the
 * watch page, where the placeholder becomes the full player).
 */
(function () {
    'use strict';

    const INTERVAL_MS = 4000;
    const MAX_POLLS = 150; // give up after ~10 minutes

    document.querySelectorAll('[data-poll-status]').forEach(function (el) {
        let polls = 0;
        const timer = setInterval(async function () {
            if (++polls > MAX_POLLS) {
                clearInterval(timer);
                return;
            }
            let data;
            try {
                const res = await fetch(el.dataset.pollStatus, {
                    headers: { Accept: 'application/json' },
                });
                if (!res.ok) return;
                data = await res.json();
            } catch (err) {
                return; // transient network error — keep polling
            }
            if (data.status === 'PENDING' || data.status === 'PROCESSING') return;
            clearInterval(timer);
            if ((el.dataset.pollMode || 'card') === 'page') {
                window.location.reload();
            } else {
                updateCard(el, data);
            }
        }, INTERVAL_MS);
    });

    function updateCard(el, data) {
        const badge = el.querySelector('.js-status-badge');
        if (data.status === 'READY') {
            if (badge) badge.remove();
            const media = el.querySelector('.js-media');
            if (media && data.thumbnail_url) {
                const img = document.createElement('img');
                img.src = data.thumbnail_url;
                img.alt = '';
                img.loading = 'lazy';
                img.className =
                    'size-full object-cover transition-transform duration-300 group-hover:scale-105';
                media.replaceWith(img);
            }
        } else if (badge) {
            badge.textContent = 'Failed';
            badge.classList.remove('bg-ink-950/90', 'text-ink-300');
            badge.classList.add('bg-red-950/90', 'text-red-300');
        }
    }
})();
