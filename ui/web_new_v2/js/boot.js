// Boot-time work that used to live in inline <script> blocks in index.html.
// A Content-Security-Policy of script-src 'self' blocks inline scripts, so this
// file exists to keep that policy strict rather than relaxing it.

// Optional picker faces use local WOFF2 files with bundled SIL OFL licenses.
// Load this stylesheet only when the picker is opened. Both startup and choosing
// a font remain usable offline, and the strict same-origin CSP stays intact.
(function () {
    var PICKER_FONT_HREF = 'assets/fonts/picker/fontfaces.css';

    window.NeDotifyEnsurePickerFonts = function () {
        if (document.getElementById('nedotify-picker-fonts')) return;
        var link = document.createElement('link');
        link.id = 'nedotify-picker-fonts';
        link.rel = 'stylesheet';
        link.href = PICKER_FONT_HREF;
        document.head.appendChild(link);
    };
})();

document.addEventListener('DOMContentLoaded', function () {
    var gfonts = document.getElementById('gfonts-stylesheet');
    if (gfonts && gfonts.media === 'print') {
        gfonts.media = 'all';
    }
    if (window.lucide) {
        window.lucide.createIcons();
    }
});

// Global toast bridge is owned by notifications.js, loaded before boot.

// Renderer liveness heartbeat. The Python watchdog (main.py) reloads the
// renderer when this pulse stops while the page is visible - the self-heal
// for the recurring WebView2 "black window with a live process" failure.
// Hidden pages throttle timers, so the state is reported and enforcement
// pauses while hidden.
(function () {
    if (window.__nedotifyHeartbeatArmed) return;
    window.__nedotifyHeartbeatArmed = true;
    var beat = function () {
        try {
            window.pywebview?.api?.frontend_heartbeat?.(
                document.visibilityState === 'visible' ? 'visible' : 'hidden');
        } catch (e) { /* bridge not injected yet - the next tick retries */ }
    };
    var lastVisibleAt = Date.now();
    var kickCompositor = function () {
        try { void document.body.offsetHeight; window.dispatchEvent(new Event('resize')); } catch (e) {}
    };
    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'visible') {
            var gap = Date.now() - lastVisibleAt;
            lastVisibleAt = Date.now();
            // Force a compositor repaint after a long hidden stretch: WebView2
            // sometimes leaves a stale/white surface after restore.
            if (gap > 5000) kickCompositor();
            beat();
        } else {
            lastVisibleAt = Date.now();
        }
    });
    // Document Events The bridge event is the reliable restore signal: native
    // visibilitychange can stay silent while WebView2 has the occlusion
    // calculation disabled, and every minimize→restore passes through it.
    document.addEventListener('nedotify:window_visibility_changed', function (e) {
        if (e && e.detail && e.detail.hidden === false) {
            lastVisibleAt = Date.now();
            kickCompositor();
        }
    });
    setInterval(beat, 4000);
    // First beat may race the bridge injection; retry shortly after load.
    setTimeout(beat, 2500);
})();
