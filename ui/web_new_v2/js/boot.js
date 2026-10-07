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

// Global toast bridge (early, no module dependency): renders every
// window 'nedotify:toast' event into #toast-container. Without this,
// the ~50 dispatch sites across js/ are silent.
(function () {
    if (window.__nedotifyToastBridgeArmed) return;
    window.__nedotifyToastBridgeArmed = true;
    function renderToast(msg, type) {
        if (!msg) return;
        var container = document.getElementById('toast-container');
        if (!container) return;
        while (container.children.length >= 4) {
            if (container.firstElementChild) container.firstElementChild.remove();
            else break;
        }
        var toast = document.createElement('div');
        toast.className = 'toast ' + (type || 'info');
        toast.textContent = msg;
        container.appendChild(toast);
        setTimeout(function () { try { toast.remove(); } catch (e) {} }, 4000);
    }
    window.addEventListener('nedotify:toast', function (e) {
        var d = (e && e.detail) || {};
        renderToast(d.msg || d.message, d.type);
    });
})();
