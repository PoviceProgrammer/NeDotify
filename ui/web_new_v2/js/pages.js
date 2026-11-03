// NeDotify - Pages Navigation Module
import { renderIcons, openModalFocusTrap, closeModalFocusTrap } from './utils.js';

const pageTitles = {
    home: 'Главная',
    search: 'Поиск',
    library: 'Библиотека',
    player: 'Плеер',
    settings: 'Настройки',
    profile: 'Профиль',
    artist: 'Исполнитель'
};

let currentBasePage = 'home';
let previousPage = 'search';
let pageStyleRequest = 0;
let settingsBackground = [];

const SIDEBAR_COLLAPSED_KEY = 'nedotify_sidebar_collapsed';

/**
 * Collapse the nav rail to icons only, or expand it back.
 *
 * The title in the rail head is the toggle: clicking "NeDotify" collapses to
 * icons, and in the collapsed state the title is the initial "N", so clicking
 * that expands again. The nav items are untouched throughout - they stay
 * clickable while collapsed, which is the whole point of the rail.
 *
 * @param {boolean} [collapsed] Force a state; omit to toggle.
 * @returns {boolean} the resulting collapsed state.
 */
export function setSidebarCollapsed(collapsed) {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return false;

    const next = typeof collapsed === 'boolean'
        ? collapsed
        : !sidebar.classList.contains('is-collapsed');

    sidebar.classList.toggle('is-collapsed', next);
    const collapseButton = document.getElementById('sidebar-collapse');
    if (collapseButton) {collapseButton.setAttribute('aria-label',next ? 'Развернуть панель разделов' : 'Свернуть панель разделов');collapseButton.setAttribute('aria-expanded',String(!next));}

    const logo = document.getElementById('sidebar-logo');
    if (logo) {
        // The tooltip has to describe the action the click will perform, not the
        // current state, and it is the only affordance left once collapsed.
        logo.title = next ? 'Развернуть панель разделов' : 'Свернуть панель разделов';
        logo.setAttribute('aria-expanded', String(!next));
    }

    try {
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, JSON.stringify(next));
    } catch (e) { /* private mode / quota - the rail still works for this session */ }

    return next;
}

export function isSidebarCollapsed() {
    const sidebar = document.getElementById('sidebar');
    return !!sidebar && sidebar.classList.contains('is-collapsed');
}

export function getPreviousPage() {
    return previousPage;
}

function initSidebarCollapse() {
    const logo = document.getElementById('sidebar-logo');
    if (!logo) return;

    // Restore before paint of the first frame so the rail does not visibly jump
    // from expanded to collapsed on launch.
    let stored = null;
    try {
        stored = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    } catch (e) { /* ignore */ }
    if (stored !== null) {
        setSidebarCollapsed(JSON.parse(stored) === true);
    } else {
        setSidebarCollapsed(false);
    }

    logo.addEventListener('click', () => setSidebarCollapsed());
    // Keyboard parity for the role="button" the markup declares.
    logo.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setSidebarCollapsed();
        }
    });
}

export function initPages() {
    document.querySelectorAll('[data-macos-page]').forEach(button=>button.addEventListener('click',()=>showPage(button.dataset.macosPage)));
    document.querySelectorAll('.nav-item[data-page]').forEach(item => {
        item.addEventListener('click', () => {
            showPage(item.dataset.page);
        });
    });

    initSidebarCollapse();

    const settingsView = document.getElementById('view-settings');
    if (settingsView) {
        // Escape clipping and stacking contexts of the current page. The base
        // view keeps its DOM, scroll positions and playback state underneath.
        document.body.appendChild(settingsView);
        document.getElementById('settings-close')?.addEventListener('click', closeSettings);
    }

    const btnBackArtist = document.getElementById('btn-back-artist');
    if (btnBackArtist && !btnBackArtist._hasBackListener) {
        btnBackArtist._hasBackListener = true;
        btnBackArtist.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const target = (previousPage && previousPage !== 'artist') ? previousPage : 'search';
            showPage(target);
        });
    }
}

export function showPage(pageId) {
    const request = ++pageStyleRequest;
    const stylesReady = window.NeDotifyStyles?.ensureForPage?.(pageId);
    if (stylesReady && typeof stylesReady.then === 'function') {
        return stylesReady.then(() => {
            if (request === pageStyleRequest) showPageReady(pageId);
        });
    }
    return showPageReady(pageId);
}

let pageTransition=null,transitionRevision=0;
function showPageReady(pageId) {
    const target=document.getElementById('view-'+pageId);
    if(!target)return;
    const revision=++transitionRevision;
    pageTransition?.skipTransition();
    if(pageId==='settings'||target.classList.contains('active')||window.matchMedia('(prefers-reduced-motion: reduce)').matches)return activatePage(pageId);
    if(!document.startViewTransition){
        const previous=document.querySelector('.view-page.active:not(#view-settings)');
        const exit=previous?.animate?.([{opacity:1,transform:'translateX(0)'},{opacity:0,transform:'translateX(-18px)'}],{duration:140,easing:'ease-out'});
        return Promise.resolve(exit?.finished).catch(()=>{}).then(()=>{
            if(revision!==transitionRevision)return;
            activatePage(pageId);target.animate?.([{opacity:0,transform:'translateX(24px)'},{opacity:1,transform:'translateX(0)'}],{duration:220,easing:'cubic-bezier(.2,.7,.2,1)'});
        });
    }
    const transition=document.startViewTransition(()=>{if(revision===transitionRevision)activatePage(pageId);});
    pageTransition=transition;
    transition.ready.catch(()=>{}); // skipTransition rejects ready during fast navigation.
    transition.finished.then(()=>{if(pageTransition===transition)pageTransition=null;}).catch(()=>{});
    return transition.updateCallbackDone;
}
function activatePage(pageId) {
    if (pageId === 'settings') {
        const title=document.getElementById('title-text');if(title)title.textContent='Настройки';
        const settingsView = document.getElementById('view-settings');
        if (settingsView) {
            if (settingsView.classList.contains('active')) {
                closeSettings();
                return;
            }
            settingsView.classList.add('active');
            settingsView.setAttribute('aria-modal', 'true');
            settingsBackground = Array.from(document.querySelectorAll('.view-page:not(#view-settings), #sidebar, #player-bar'))
                .map(node => [node, node.inert]);
            for (const [node] of settingsBackground) node.inert = true;
            openModalFocusTrap(settingsView, {onClose:closeSettings, initialFocus:'#settings-search'});
            window.dispatchEvent(new CustomEvent('nedotify:settings_visibility', {detail:{open:true}}));

            const activeNavBtn = document.querySelector('.settings-nav-btn.active') || document.querySelector('.settings-nav-btn[data-panel="appearance"]');
            const activePanelId = activeNavBtn ? 'settings-' + activeNavBtn.dataset.panel : 'settings-appearance';
            document.querySelectorAll('.settings-panel').forEach(p => {
                const isActive = p.id === activePanelId;
                p.classList.toggle('active', isActive);
                p.style.display = isActive ? 'block' : 'none';
            });
        }

        document.querySelectorAll('.nav-item[data-page]').forEach(item => {
            item.classList.toggle('active', item.dataset.page === 'settings');
        });

        if (window.NeDotify?.loadSettings) window.NeDotify.loadSettings();
        renderIcons();
        return;
    }

    // Close settings overlay if open
    closeSettings();

    if (pageId === 'artist') {
        if (currentBasePage && currentBasePage !== 'artist') {
            previousPage = currentBasePage;
        }
    } else {
        currentBasePage = pageId;
    }

    // Hide all pages except target
    document.querySelectorAll('.view-page').forEach(p => {
        if (p.id !== 'view-settings') {
            p.classList.toggle('active', p.id === 'view-' + pageId);
        }
    });

    // Update nav
    document.querySelectorAll('.nav-item[data-page]').forEach(item => {
        item.classList.toggle('active', item.dataset.page === pageId);
    });

    // Update title bar
    const titleEl = document.getElementById('title-text');
    if (titleEl) titleEl.textContent = pageTitles[pageId] || 'NeDotify';

    // Back button wiring ensure
    const btnBackArtist = document.getElementById('btn-back-artist');
    if (btnBackArtist && !btnBackArtist._hasBackListener) {
        btnBackArtist._hasBackListener = true;
        btnBackArtist.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const target = (previousPage && previousPage !== 'artist') ? previousPage : 'search';
            showPage(target);
        });
    }

    // Trigger page-specific loading
    if (window.NeDotify) {
        if (pageId === 'home' && window.NeDotify.loadHome) window.NeDotify.loadHome();
        if (pageId === 'profile' && window.NeDotify.loadProfile) window.NeDotify.loadProfile();
        if (pageId === 'library' && window.NeDotify.loadLibrary) window.NeDotify.loadLibrary();
    }
    if (pageId === 'player' && window.NeDotify?.loadCurrentTrackLyrics) {
        window.NeDotify.loadCurrentTrackLyrics();
    }

    renderIcons();
    window.dispatchEvent(new CustomEvent('nedotify:page_changed', { detail: pageId }));
}

export function closeSettings() {
    const settingsView = document.getElementById('view-settings');
    if (settingsView?.classList.contains('active')) {
        settingsView.classList.remove('active');
        settingsView.removeAttribute('aria-modal');
        for (const [node, wasInert] of settingsBackground) node.inert = wasInert;
        settingsBackground = [];
        closeModalFocusTrap(settingsView);
        window.dispatchEvent(new CustomEvent('nedotify:settings_visibility', {detail:{open:false}}));
    }

    // Restore active nav item for currentBasePage
    document.querySelectorAll('.nav-item[data-page]').forEach(item => {
        item.classList.toggle('active', item.dataset.page === currentBasePage);
    });

    const titleEl = document.getElementById('title-text');
    if (titleEl) titleEl.textContent = pageTitles[currentBasePage] || 'NeDotify';
}

// Global accessors
window.showPage = showPage;
window.closeSettings = closeSettings;
window.setSidebarCollapsed = setSidebarCollapsed;
window.isSidebarCollapsed = isSidebarCollapsed;
