// Shared, finite motion. State changes never wait for an exit animation.
(() => {
    let transition = null, revision = 0, owner = null;
    const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    function swap(panel, update) {
        transition?.skipTransition();
        if (owner) owner.panel.style.viewTransitionName = owner.previous;
        transition = null; owner = null;
        const token = ++revision;
        if (!panel || !panel.isConnected || reduced() || !document.startViewTransition || document.hidden) {
            update(); return;
        }
        // Top-layer elements (native <dialog> and [popover]) are obscured by document-level View Transitions.
        if (panel.closest('dialog, [popover]')) {
            update();
            if (panel.animate) {
                try {
                    panel.getAnimations?.().forEach(a => a.cancel());
                    panel.animate([
                        { opacity: 0, transform: 'translateY(6px)' },
                        { opacity: 1, transform: 'none' }
                    ], { duration: 160, easing: 'cubic-bezier(.2,.75,.2,1)' });
                } catch (_) {}
            }
            return;
        }
        const previous = panel.style.viewTransitionName;
        panel.style.viewTransitionName = 'panel-content';
        owner = {panel, previous};
        const current = document.startViewTransition(() => { if (revision === token) update(); });
        transition = current;
        current.finished.catch(() => {}).finally(() => {
            // A rapid second selection owns the panel until it finishes.
            if (revision === token) { panel.style.viewTransitionName = previous; transition = null; owner = null; }
        });
    }
    function remove(menu) {
        if (!menu || menu.dataset.motionLeaving) return;
        if (reduced() || !menu.animate || !menu.isConnected) { menu?.remove(); return; }
        menu.dataset.motionLeaving = 'true';
        menu.inert = true;
        menu.setAttribute('aria-hidden', 'true');
        menu.style.pointerEvents = 'none';
        // Release lookup IDs immediately so reopening cannot target a retiring menu.
        menu.removeAttribute('id');
        menu.querySelectorAll('[id]').forEach(node => node.removeAttribute('id'));
        const animation = menu.animate([
            {opacity: 1, transform: 'translateY(0) scale(1)'},
            {opacity: 0, transform: 'translateY(5px) scale(.975)'},
        ], {duration: 150, easing: 'cubic-bezier(.4,0,1,1)', fill: 'forwards'});
        const timer = setTimeout(() => menu.remove(), 200);
        animation.finished.catch(() => {}).finally(() => { clearTimeout(timer); menu.remove(); });
    }
    const active = new WeakMap();
    function enabled() {
        return !reduced() && !document.hidden &&
            !document.documentElement.classList.contains('battery-saver-active') &&
            !document.body?.classList.contains('unfocused-animations-disabled');
    }

    function play(node, frames, duration) {
        if (!node?.animate) return;
        active.get(node)?.cancel();
        if (!enabled() || !node.isConnected || node.checkVisibility?.({checkVisibilityCSS: true}) === false) return;
        const animation = node.animate(frames, {
            duration, easing: 'cubic-bezier(.2,.75,.25,1)'
        });
        animation.id = 'nedotify-motion';
        active.set(node, animation);
    }

    // A running WAAPI translate is part of getBoundingClientRect(). Measuring a
    // row mid-shift therefore reports a position that never existed in layout,
    // and settleList would animate from that wrong delta. Cancel our own motion
    // (never unrelated CSS animations) before the caller reads geometry.
    function cancelRowMotion(row) {
        const animation = active.get(row);
        if (!animation) return;
        try { animation.cancel(); } catch (_) {}
        active.delete(row);
    }

    function reveal(node, offset = 4) {
        play(node, [
            {opacity: .55, translate: `0 ${offset}px`},
            {opacity: 1, translate: 'none'}
        ], 160);
    }

    // Artwork changes are larger than a row reveal: a short fade plus a 1.5%
    // scale reads as a new sleeve landing without moving the surrounding layout.
    function cover(node) {
        play(node, [
            {opacity: .35, transform: 'scale(1.015)'},
            {opacity: 1, transform: 'none'}
        ], 220);
    }

    function listPositions(list, viewport = list) {
        const positions = new Map();
        if (!enabled() || !list?.isConnected || list.checkVisibility?.({checkVisibilityCSS: true}) === false) return positions;
        // Measure layout, not a snapshot of an unfinished shift.
        for (const row of list.children) cancelRowMotion(row);
        const visible = viewport.getBoundingClientRect();
        const rows = list.children;
        let low = 0, high = rows.length;
        while (low < high) {
            const middle = Math.floor((low + high) / 2);
            if (rows[middle].getBoundingClientRect().bottom <= visible.top) low = middle + 1;
            else high = middle;
        }
        for (let index = low; index < Math.min(rows.length, low + 16); index++) {
            const row = rows[index];
            const {top} = row.getBoundingClientRect();
            if (top >= visible.bottom) break;
            if (row.dataset.motionKey) positions.set(row.dataset.motionKey, {row, top});
        }
        return positions;
    }

    function settleList(list, before, viewport = list) {
        if (!before?.size) {
            reveal(list);
            return;
        }
        const after = listPositions(list, viewport);
        for (const [key, {row, top}] of after) {
            const previous = before.get(key)?.top;
            if (previous === undefined) reveal(row);
            else if (Math.abs(previous - top) > 1) {
                play(row, [{translate: `0 ${previous - top}px`}, {translate: 'none'}], 190);
            }
        }
    }

    window.NeDotifyMotion = {swap, remove, reveal, cover, listPositions, settleList};
})();
