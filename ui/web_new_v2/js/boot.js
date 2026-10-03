// Boot-time work that used to live in inline <script> blocks in index.html.
// A Content-Security-Policy of script-src 'self' blocks inline scripts, so this
// file exists to keep that policy strict rather than relaxing it.

// Web fonts are a progressive enhancement: the stylesheet is attached one second
// after load so a blocked or slow font CDN can never delay first paint.
window.addEventListener('load', function () {
    setTimeout(function () {
        var link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = 'https://fonts.googleapis.com/css2'
            + '?family=Inter:wght@300;400;500;600;700;800'
            + '&family=Outfit:wght@300;400;500;600;700;800'
            + '&family=Roboto:wght@300;400;500;700'
            + '&family=Montserrat:wght@400;500;600;700;800'
            + '&family=Plus+Jakarta+Sans:wght@400;500;600;700;800'
            + '&display=swap';
        document.head.appendChild(link);
    }, 1000);
});

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
