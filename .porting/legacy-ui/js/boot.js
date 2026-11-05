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
    if (window.lucide) {
        window.lucide.createIcons();
    }
});
