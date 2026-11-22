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

    let press = null;
    const releases = new WeakMap();
    const canDeformButton = () => enabled() &&
        !document.documentElement.classList.contains('perf-low');

    function finishPress() {
        if (!press) return;
        const {button, scale, translate} = press;
        press = null;
        button.removeAttribute('data-matte-pressed');
        button.style.removeProperty('scale');
        button.style.removeProperty('translate');
        if (!canDeformButton() || !button.isConnected || button.disabled) return;
        releases.set(button, button.animate([
            {scale, translate, '--matte-depth': '.23'},
            {scale: '1.008', translate: '0px 0px', '--matte-depth': '.025', offset: .75},
            {scale: '1', translate: '0px 0px', '--matte-depth': '0'},
        ], {duration: 220, easing: 'cubic-bezier(.2,.75,.3,1)'}));
    }

    function beginPress(event, pointer) {
        if (press || !(event.target instanceof Element)) return;
        const button = event.target.closest('button');
        if (!button || button.matches(':disabled, [aria-disabled="true"]') ||
            getComputedStyle(button).getPropertyValue('--matte-button').trim() !== '1') return;
        releases.get(button)?.cancel();
        const bounds = button.getBoundingClientRect();
        if (!bounds.width || !bounds.height) return;
        const x = pointer ? event.clientX : bounds.left + bounds.width / 2;
        const y = pointer ? event.clientY : bounds.top + bounds.height / 2;
        button.style.setProperty('--matte-x', `${(x - bounds.left) / bounds.width * 100}%`);
        button.style.setProperty('--matte-y', `${(y - bounds.top) / bounds.height * 100}%`);
        press = {button, x, y, input: pointer ? event.pointerId : event.key,
            scale: '1', translate: '0px 0px'};
        button.setAttribute('data-matte-pressed', '');
        if (canDeformButton()) {
            press.scale = '.98';
            button.style.scale = press.scale;
        }
    }

    const capture = {capture: true, passive: true};
    window.addEventListener('pointerdown', event => {
        if (event.isPrimary && event.button === 0) beginPress(event, true);
    }, capture);
    window.addEventListener('pointermove', event => {
        if (press?.input !== event.pointerId) return;
        if (event.pointerType === 'mouse' && !(event.buttons & 1)) {
            finishPress();
            return;
        }
        if (!canDeformButton()) return;
        const limit = delta => Math.max(-1, Math.min(1, delta / 28));
        const x = limit(event.clientX - press.x);
        const y = limit(event.clientY - press.y);
        press.scale = `${.98 + Math.abs(x) * .055} ${.98 + Math.abs(y) * .055}`;
        press.translate = `${x * 3}px ${y * 3}px`;
        press.button.style.scale = press.scale;
        press.button.style.translate = press.translate;
    }, capture);
    for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
        window.addEventListener(type, event => {
            if (press?.input === event.pointerId) finishPress();
        }, capture);
    }
    window.addEventListener('keydown', event => {
        if (!event.repeat && (event.key === ' ' || event.key === 'Enter')) beginPress(event, false);
    }, capture);
    window.addEventListener('keyup', event => {
        if (press?.input === event.key) finishPress();
    }, capture);
    window.addEventListener('focusout', event => {
        if (typeof press?.input === 'string' && press.button === event.target) finishPress();
    }, capture);
    window.addEventListener('blur', finishPress);
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) finishPress();
    });

    window.NeDotifyMotion = {swap, remove, reveal, cover, listPositions, settleList};
})();
