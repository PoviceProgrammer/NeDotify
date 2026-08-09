// NeDotify вЂ” Search Module Redesign
import { createTrackElement, renderIcons } from './utils.js?v=19';
import { getCurrentTrack } from './player.js?v=19';
import { 
    loadArtistProfile, 
    ArtistPhotoComponent, 
    ArtistBioComponent, 
    ArtistAlbumsComponent, 
    ArtistTracksComponent 
} from './artist_profile.js?v=19';

let searchDebounce = null;
let currentSource = 'youtube'; // Default source is YouTube Music as shown in screenshot 1
let currentType = 'tracks';    // Default filter is 'Треки' as shown in screenshot 1
let allResults = [];
let currentSearchQuery = '';   // Track the latest query sent

let isViewingArtistProfile = false;

// Platform SVGs map for updating button icon dynamically
const PLATFORM_SVGS = {
    youtube: `<svg class="platform-svg" viewBox="0 0 24 24" width="20" height="20"><circle cx="12" cy="12" r="10" fill="#FF0000"/><polygon points="9.5,7.5 16.5,12 9.5,16.5" fill="#FFFFFF"/></svg>`,
    soundcloud: `<svg class="platform-svg" viewBox="0 0 24 24" width="20" height="20" fill="#FF5500"><path d="M11.56 8.87c-.24 0-.47.02-.7.06A6.17 6.17 0 0 0 5 13.5c0 .17.01.34.03.51A4.24 4.24 0 0 0 1 18.25 4.25 4.25 0 0 0 5.25 22.5h13.5A5.25 5.25 0 0 0 24 17.25a5.24 5.24 0 0 0-4.05-5.11 6.17 6.17 0 0 0-8.39-3.27z"/></svg>`,
    spotify: `<svg class="platform-svg" viewBox="0 0 24 24" width="20" height="20" fill="#1DB954"><path d="M12 0C5.376 0 0 5.376 0 12s5.376 12 12 12 12-5.376 12-12S18.624 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.02 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.48-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.3 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.18-1.2-.18-1.38-.72-.18-.6.18-1.2.72-1.38 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/></svg>`
};

export function initSearch() {
    const input = document.getElementById('search-input');
    const clearBtn = document.getElementById('search-clear');
    const platformBtn = document.getElementById('search-platform-btn');
    const platformDropdown = document.getElementById('search-platform-dropdown');
    const activeIconSpan = document.getElementById('search-platform-active-icon');

    if (input) {
        input.addEventListener('input', (e) => {
            isViewingArtistProfile = false;
            const query = e.target.value.trim();
            clearTimeout(searchDebounce);

            if (clearBtn) clearBtn.classList.toggle('visible', query.length > 0);

            if (query.length > 0) {
                showLoading();
                searchDebounce = setTimeout(() => {
                    allResults = [];
                    currentSearchQuery = query;
                    api('search', query, currentSource);
                }, 300);
            } else {
                currentSearchQuery = '';
                showPlaceholder();
            }
        });
    }

    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            isViewingArtistProfile = false;
            if (input) input.value = '';
            if (clearBtn) clearBtn.classList.remove('visible');
            allResults = [];
            currentSearchQuery = '';
            showPlaceholder();
        });
    }

    // Toggle Platform Dropdown
    if (platformBtn && platformDropdown) {
        platformBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            platformDropdown.classList.toggle('hidden');
        });

        // Close on outside click
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.search-platform-wrapper')) {
                platformDropdown.classList.add('hidden');
            }
        });
    }

    // Platform Dropdown Selection (YouTube, SoundCloud, Spotify ONLY)
    document.querySelectorAll('.platform-item').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const selectedSource = btn.dataset.source;
            if (!selectedSource || !PLATFORM_SVGS[selectedSource]) return;

            currentSource = selectedSource;

            // Update active icon on platform button
            if (activeIconSpan) {
                activeIconSpan.innerHTML = PLATFORM_SVGS[selectedSource];
            }

            // Update active state in dropdown
            document.querySelectorAll('.platform-item').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            // Hide dropdown
            if (platformDropdown) platformDropdown.classList.add('hidden');

            // Re-trigger search if query exists
            const query = input?.value.trim();
            if (query && query.length > 0) {
                isViewingArtistProfile = false;
                allResults = [];
                currentSearchQuery = query;
                showLoading();
                api('search', query, currentSource);
            }
        });
    });

    // Sub-type Filters: Все, Треки, Плейлисты, Альбомы, Артисты
    document.querySelectorAll('.type-filter-btn[data-type]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.type-filter-btn[data-type]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentType = btn.dataset.type;

            if (isViewingArtistProfile && currentType !== 'artists') {
                isViewingArtistProfile = false;
            }

            if (currentType === 'artists') {
                const query = input?.value.trim() || currentSearchQuery;
                if (query) {
                    searchArtistProfile(query);
                } else {
                    const container = document.getElementById('search-results');
                    if (container) {
                        container.innerHTML = '<div class="empty-state">Введите имя артиста для поиска профиля</div>';
                    }
                }
            } else if (allResults.length > 0) {
                renderResults(allResults);
            }
        });
    });

    renderIcons();
}

// Global accessor to navigate to an artist profile
export function searchArtistProfile(artistName) {
    isViewingArtistProfile = true;
    const input = document.getElementById('search-input');
    const clearBtn = document.getElementById('search-clear');
    if (input) {
        input.value = artistName;
        if (clearBtn) clearBtn.classList.add('visible');
    }
    
    // Set active type filter to "Артисты"
    document.querySelectorAll('.type-filter-btn[data-type]').forEach(b => {
        b.classList.toggle('active', b.dataset.type === 'artists');
    });
    currentType = 'artists';
    currentSearchQuery = artistName;
    allResults = [];

    // Switch to search page
    if (window.showPage) {
        window.showPage('search');
    }

    showLoadingArtist(artistName);
    loadArtistProfile(artistName, document.getElementById('search-results'));
}

window.searchArtistProfile = searchArtistProfile;

export function onSearchResults(data) {
    if (isViewingArtistProfile) {
        return; // Don't overwrite active artist profile view
    }
    if (data.query && currentSearchQuery && data.query !== currentSearchQuery) {
        return; // Stale result — ignore
    }
    if (data.tracks && data.tracks.length > 0) {
        // STRICT RULE: Exclude Yandex Music completely!
        const filteredTracks = data.tracks.filter(t => (t.source || '').toLowerCase() !== 'yandex');
        if (filteredTracks.length > 0) {
            allResults = allResults.concat(filteredTracks);
            renderResults(allResults);
        }
    } else {
        const container = document.getElementById('search-results');
        if (container && container.querySelector('.spinner') && allResults.length === 0) {
            container.innerHTML = '<div class="empty-state">Ничего не найдено</div>';
        }
    }
}

function renderResults(tracks) {
    const container = document.getElementById('search-results');
    if (!container) return;

    if (!tracks || tracks.length === 0) {
        container.innerHTML = '<div class="empty-state">Ничего не найдено</div>';
        return;
    }

    container.innerHTML = '';

    // Filter by selected sub-type (all, tracks, playlists, albums, artists)
    let displayTracks = tracks;
    if (currentType === 'artists') {
        const artistSuggest = document.createElement('div');
        artistSuggest.style.cssText = 'padding: 16px 20px; margin-bottom: 20px; border-radius: 16px; background: rgba(var(--primary-rgb), 0.08); border: 1px solid rgba(var(--primary-rgb), 0.15); display: flex; justify-content: space-between; align-items: center; animation: fadeIn 0.3s ease;';
        artistSuggest.innerHTML = `
            <div style="display:flex; align-items:center; gap:12px; font-size:14px; color:var(--text-main)">
                <i data-lucide="user" style="width:20px;height:20px;color:var(--primary)"></i>
                <span>Посмотреть подробный профиль исполнителя <strong>"${currentSearchQuery}"</strong></span>
            </div>
            <button class="type-filter-btn active" style="margin: 0; padding: 6px 16px; font-size:12px;">Открыть профиль</button>
        `;
        artistSuggest.querySelector('button').addEventListener('click', () => {
            searchArtistProfile(currentSearchQuery);
        });
        container.appendChild(artistSuggest);
    }

    // Suggestion banner for artist profile in 'all' view
    if (currentType === 'all' && currentSearchQuery) {
        const artistSuggest = document.createElement('div');
        artistSuggest.style.cssText = 'padding: 12px 16px; margin-bottom: 16px; border-radius: 14px; background: rgba(var(--primary-rgb), 0.08); border: 1px solid rgba(var(--primary-rgb), 0.15); display: flex; justify-content: space-between; align-items: center; animation: fadeIn 0.3s ease;';
        artistSuggest.innerHTML = `
            <div style="display:flex; align-items:center; gap:10px; font-size:13px; color:var(--text-main)">
                <i data-lucide="user" style="width:16px;height:16px;color:var(--primary)"></i>
                <span>Посмотреть профиль исполнителя <strong>"${currentSearchQuery}"</strong></span>
            </div>
            <button class="type-filter-btn active" style="margin: 0; padding: 4px 12px; font-size:11px;">Открыть</button>
        `;
        artistSuggest.querySelector('button').addEventListener('click', () => {
            searchArtistProfile(currentSearchQuery);
        });
        container.appendChild(artistSuggest);
    }

    const list = document.createElement('div');
    list.className = 'track-list';
    displayTracks.forEach((track, i) => {
        list.appendChild(createTrackElement(track, i, displayTracks, getCurrentTrack()));
    });
    container.appendChild(list);
    renderIcons();
}

function showLoading() {
    const container = document.getElementById('search-results');
    if (container) {
        container.innerHTML = '<div class="empty-state"><div class="spinner"></div><span>Поиск...</span></div>';
    }
}

function showLoadingArtist(query) {
    const container = document.getElementById('search-results');
    if (!container) return;

    container.innerHTML = '';
    const wrapper = document.createElement('div');
    wrapper.className = 'artist-profile-layout';

    const leftCol = document.createElement('div');
    leftCol.className = 'artist-col-left skeleton-active';

    const rightCol = document.createElement('div');
    rightCol.className = 'artist-col-right skeleton-active';

    wrapper.appendChild(leftCol);
    wrapper.appendChild(rightCol);
    container.appendChild(wrapper);

    leftCol.appendChild(ArtistPhotoComponent.renderSkeleton());
    leftCol.appendChild(ArtistBioComponent.renderSkeleton());
    rightCol.appendChild(ArtistAlbumsComponent.renderSkeleton());
    rightCol.appendChild(ArtistTracksComponent.renderSkeleton());
    renderIcons();
}

function showPlaceholder() {
    const container = document.getElementById('search-results');
    if (container) {
        container.innerHTML = '<div class="empty-state"><i data-lucide="search" style="width:40px;height:40px;opacity:0.3"></i><span>Введите запрос для поиска музыки</span></div>';
        renderIcons();
    }
}

function api(method, ...args) {
    if (window.pywebview && window.pywebview.api) {
        return window.pywebview.api[method](...args);
    }
}





