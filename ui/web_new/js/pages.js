// NeDotify - Pages Navigation Module
import { renderIcons } from './utils.js?v=20260814_9';

const pageTitles = {
    home: 'Главная',
    search: 'Поиск',
    library: 'Библиотека',
    player: 'Плеер',
    settings: 'Настройки',
    profile: 'Профиль'
};

let currentBasePage = 'home';

export function initPages() {
    document.querySelectorAll('.nav-item[data-page]').forEach(item => {
        item.addEventListener('click', () => {
            showPage(item.dataset.page);
        });
    });

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



