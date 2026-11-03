// Boot-time work that used to live in inline <script> blocks in index.html.
// A Content-Security-Policy of script-src 'self' blocks inline scripts, so this
// file exists to keep that policy strict rather than relaxing it.

// Fonts offered by the Settings > Appearance font picker (Inter, Outfit,
// Roboto, Montserrat, Plus Jakarta Sans). These are NOT the app's own faces -
// DM Sans and Sora are self-hosted in assets/fonts/ and are declared by
// css/fonts.css, so the UI renders correctly with no network at all.
//
// This used to be an unconditional request fired one second after `load`. It is
// now lazy and on demand. The picker is opt-in, so a cold start no longer pays
// for a stylesheet most sessions never need, and an offline install no longer
// issues a request that can only fail.
//
// It stays remote rather than bundled because five extra families would add
// roughly a megabyte to the installer for a rarely-used panel; that trade is
// the reason `https://fonts.googleapis.com` must remain in `style-src` in
// index.html. Dropping it there silently breaks picking any of these fonts.
(function () {
    var PICKER_FONT_HREF = 'https://fonts.googleapis.com/css2'
        + '?family=Inter:wght@300;400;500;600;700;800'
        + '&family=Outfit:wght@300;400;500;600;700;800'
        + '&family=Roboto:wght@300;400;500;700'
        + '&family=Montserrat:wght@400;500;600;700;800'
        + '&family=Plus+Jakarta+Sans:wght@400;500;600;700;800'
        + '&display=swap';

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
