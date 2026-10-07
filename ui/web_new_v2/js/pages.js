// NeDotify - Pages Navigation Module
import { renderIcons } from './utils.js';

const pageTitles = {
    home: 'Главная',
    search: 'Поиск',
    library: 'Библиотека',
    player: 'Плеер',
    settings: 'Настройки',
    profile: 'Профиль'
};

let currentBasePage = 'home';

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
    document.querySelectorAll('.nav-item[data-page]').forEach(item => {
        item.addEventListener('click', () => {
            showPage(item.dataset.page);
        });
    });

    initSidebarCollapse();

    const settingsView = document.getElementById('view-settings');
    if (settingsView) {
        settingsView.addEventListener('click', (e) => {
            if (e.target === settingsView) {
                closeSettings();
            }
        });
    }

    // Esc key to close settings overlay
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (settingsView && settingsView.classList.contains('active')) {
                closeSettings();
            }
        }
    });
}

export function showPage(pageId) {
    if (pageId === 'settings') {
        const settingsView = document.getElementById('view-settings');
        if (settingsView) {
            if (settingsView.classList.contains('active')) {
                closeSettings();
                return;
            }
            settingsView.classList.add('active');

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

    currentBasePage = pageId;

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
    if (settingsView) settingsView.classList.remove('active');

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



