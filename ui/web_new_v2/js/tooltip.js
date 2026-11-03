// App-wide hover tooltips.
//
// One shared #app-tooltip node is driven by a delegated mouseover listener, so
// buttons created later (track rows, context menus, settings pages) are covered
// without re-binding anything.
//
// Text source, in priority order:
//   1. the `title` attribute (as before — native tooltips are suppressed while
//      hovering by temporarily moving the value aside, then restored);
//   2. `aria-label`, but ONLY on an icon-only element (no visible text), so
//      labelled buttons don't get a redundant copy of their own caption;
//   3. `data-tip` for anything that wants an explicit tooltip that differs
//      from both attributes above.
// Opt out per element with data-no-app-tooltip (inherited by descendants).
//
// Loaded as a plain script from index.html (CSP: no inline script), before
// main.js, so early UI gets tooltips too.
(function () {
    if (window.__nedotifyTooltip) return;
    window.__nedotifyTooltip = true;

    var SHOW_DELAY_MS = 350;
    var GAP = 8;

    var tip = null;
    var timer = null;
    var anchor = null;

    function ensureTip() {
        if (!tip) {
            tip = document.createElement('div');
            tip.id = 'app-tooltip';
            tip.setAttribute('role', 'tooltip');
            tip.setAttribute('aria-hidden', 'true');
            document.body.appendChild(tip);
        }
        return tip;
    }

    function tooltipText(el) {
        if (el.closest('[data-no-app-tooltip]')) return null;
        var explicit = el.getAttribute('data-tip');
        if (explicit && explicit.trim()) return explicit.trim();
        var title = el.getAttribute('title');
        if (title && title.trim()) return title.trim();
        var label = el.getAttribute('aria-label');
        // Icon-only elements have no visible caption to echo.
        if (label && label.trim() && !el.textContent.trim()) return label.trim();
        return null;
    }

    function suppressNativeTitle(el) {
        if (!el.hasAttribute('title')) return;
        el.__nedotifyTitle = el.getAttribute('title');
        el.removeAttribute('title');
    }

    function restoreNativeTitle(el) {
        if (el && el.__nedotifyTitle != null) {
            el.setAttribute('title', el.__nedotifyTitle);
            el.__nedotifyTitle = null;
        }
    }

    function positionFor(el) {
        var t = ensureTip();
        var rect = el.getBoundingClientRect();
        var vw = document.documentElement.clientWidth;
        var vh = document.documentElement.clientHeight;
        var tw = t.offsetWidth;
        var th = t.offsetHeight;
        var left = rect.left + rect.width / 2 - tw / 2;
        left = Math.max(8, Math.min(left, vw - tw - 8));
        var top = rect.bottom + GAP;
        if (top + th > vh - 8) top = rect.top - th - GAP; // flip above
        top = Math.max(8, top);
        t.style.left = Math.round(left) + 'px';
        t.style.top = Math.round(top) + 'px';
    }

    function show(el) {
        var text = tooltipText(el);
        if (!text) return;
        anchor = el;
        suppressNativeTitle(el);
        clearTimeout(timer);
        timer = setTimeout(function () {
            var t = ensureTip();
            t.textContent = text;
            t.classList.add('visible');
            positionFor(el);
        }, SHOW_DELAY_MS);
    }

    function hide() {
        clearTimeout(timer);
        timer = null;
        restoreNativeTitle(anchor);
        anchor = null;
        if (tip) tip.classList.remove('visible');
    }

    document.addEventListener('mouseover', function (e) {
        var el = hoverTarget(e);
        if (!el || el === anchor) return;
        if (el.disabled) { hide(); return; }
        hide();
        show(el);
    });

    // Some embedded runtimes deliver mousemove without the derived boundary
    // events; re-resolving the anchor on every move keeps hover tooltips
    // working there too. mouseover remains the primary path.
    document.addEventListener('mousemove', function (e) {
        var el = hoverTarget(e);
        if (!el) { if (anchor) hide(); return; }
        if (el === anchor) return;
        if (el.disabled) { hide(); return; }
        hide();
        show(el);
    });

    function hoverTarget(e) {
        if (!e.target || !e.target.closest) return null;
        var el = e.target.closest('[data-tip], [title], [aria-label]');
        if (!el) return null;
        if (el.closest('#app-tooltip, #toast-container')) return null;
        return el;
    }

    document.addEventListener('mouseout', function (e) {
        if (!anchor) return;
        var to = e.relatedTarget;
        if (to && anchor.contains(to)) return; // moved within the same anchor
        if (to && to.closest && to.closest('[data-tip], [title], [aria-label]') === anchor) return;
        hide();
    });

    // Any layout change while a tooltip is up invalidates its position.
    window.addEventListener('scroll', hide, true);
    window.addEventListener('resize', hide);
    document.addEventListener('mousedown', hide, true);
    window.addEventListener('blur', hide);
})();
