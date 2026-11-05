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
    window.NeDotifyMotion = {swap, remove};
})();
