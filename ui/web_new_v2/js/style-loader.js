// Keep the shared shell render-blocking; fetch heavier view packs only when
// their page is opened. Each authored stylesheet slot is activated once.
(() => {
    const root = document.documentElement;
    const loaded = new Map();
    const nodes = new Map();
    const versions = '20261024_macos_player';
    // The placeholders in index.html preserve the authored cascade order. They
    // have no href and issue no request until a page needs that pack.
    const deferred = {
        search: `css/components/search-refresh.css?v=${versions}`,
        library: `css/components/library-refresh.css?v=${versions}`,
        downloads: `css/components/downloads-view.css?v=${versions}`,
        featureTools: `css/components/feature-tools.css?v=${versions}`,
        settings: `css/components/settings-refresh.css?v=${versions}`,
        profile: `css/components/profile-refresh.css?v=${versions}`,
        stylePicker: `css/components/ui-style-picker.css?v=${versions}`,
        macosTokens: `MACos_ui/tokens.css?v=${versions}`,
        macosInterface: `MACos_ui/interface.css?v=${versions}`,
        macosSettings: `MACos_ui/settings.css?v=${versions}`,
        macosLibrary: `MACos_ui/library.css?v=${versions}`,
    };
    const pagePacks = {
        search: ['search'],
        library: ['library', 'downloads'],
        // BUG-U3-004: мёртвый ключ 'playlist-details' удалён вместе со страницей.
        profile: ['profile'],
        settings: ['featureTools', 'settings', 'stylePicker'],
    };

    for (const key of Object.keys(deferred))
        nodes.set(key, document.querySelector(`link[data-nedotify-deferred-style="${key}"]`));

    function load(key) {
        if (loaded.has(key)) return loaded.get(key);
        const href = deferred[key];
        const link = nodes.get(key);
        if (!link) {
            console.warn('Missing deferred stylesheet slot:', key);
            return Promise.resolve(false);
        }
        const promise = new Promise(resolve => {
            link.onload = () => { link.media = 'all'; resolve(true); };
            link.onerror = () => {
                console.warn('Could not load view stylesheet:', href);
                resolve(false);
            };
            link.href = href;
        });
        loaded.set(key, promise);
        return promise;
    }

    function ensureForPage(page) {
        const names = [...(pagePacks[page] || [])];
        if (root.dataset.uiStyle === 'macos') {
            names.push('macosTokens', 'macosInterface');
            if (page === 'library') names.push('macosLibrary');
            if (page === 'settings') names.push('macosSettings');
        }
        return Promise.all(names.map(load));
    }

    function ensureMacStyle() {
        if (root.dataset.uiStyle !== 'macos') return Promise.resolve([]);
        root.classList.add('css-loading');
        return Promise.all(['macosTokens', 'macosInterface'].map(load))
            .finally(() => root.classList.remove('css-loading'));
    }

    root.classList.add('css-loading');
    const boot = Promise.all([ensureForPage('home'), ensureMacStyle()])
        .finally(() => root.classList.remove('css-loading'));

    new MutationObserver(() => {
        if (root.dataset.uiStyle === 'macos') {
            const activeView = document.querySelector('#view-settings.active')
                || document.querySelector('.view-page.active');
            const page = activeView?.id?.replace(/^view-/, '') || 'home';
            root.classList.add('css-loading');
            ensureForPage(page).finally(() => root.classList.remove('css-loading'));
        }
    }).observe(root, {attributes: true, attributeFilter: ['data-ui-style']});

    window.NeDotifyStyles = Object.freeze({ensureForPage, ready: boot});
})();
