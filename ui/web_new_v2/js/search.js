import { initSearchDiscovery, setDiscoveryMode } from './search-discovery.js';
// NeDotify — Search Module Redesign
import { createTrackElement, renderIcons, filterVisibleTracks, escapeHtml, getCoverFallbackGradient, openModalFocusTrap, closeModalFocusTrap, artistAvatarHtml, showToast } from './utils.js';
import { getCurrentTrack } from './player.js';
import {
    loadArtistProfile, cancelArtistProfileRequests,
    ArtistPhotoComponent,
    ArtistBioComponent,
    ArtistAlbumsComponent,
    ArtistTracksComponent
} from './artist_profile.js';

let searchDebounce = null;
let currentType = 'all'; // The discovery page starts with all catalog results.
let allResults = [];
let currentSearchQuery = '';   // Track the latest query sent
let searchBatchRafId = null;
let lastResultKey = null;
let searchHeaderResizeObserver = null;
let searchSuggestionGeneration = 0;
let suggestionRequestKey = '';
let correctionContext = null;
let searchIsOffline = false;
let activeSearchRequestId = null;
let searchPending = false;
let visibleSearchCount = 12;
let searchRequestGeneration = 0;

let isViewingArtistProfile = false;

function syncSearchHeaderHeight() {
    const view = document.getElementById('view-search');
    const header = view?.querySelector('.search-header-container');
    if (!view || !header) return;
    const height = Math.ceil(header.getBoundingClientRect().height);
    if (height > 0) view.style.setProperty('--search-header-height', `${height}px`);
}

function setSearchLayout(hasQuery) {
    const view = document.getElementById('view-search');
    if (!view) return;
    view.classList.toggle('search-active', Boolean(hasQuery));
    view.classList.toggle('search-empty', !hasQuery);
    syncSearchHeaderHeight();
}

export function initSearch() {
    const input = document.getElementById('search-input');
    const clearBtn = document.getElementById('search-clear');

    const searchHeader = document.querySelector('.search-header-container');
    if (searchHeader && typeof ResizeObserver !== 'undefined') {
        searchHeaderResizeObserver?.disconnect();
        searchHeaderResizeObserver = new ResizeObserver(syncSearchHeaderHeight);
        searchHeaderResizeObserver.observe(searchHeader);
    }
    setSearchLayout(Boolean(input?.value.trim()));

    document.getElementById('search-submit')?.addEventListener('click', () => {
        if (input?.value.trim()) input.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter',bubbles:true}));
        else input?.focus();
    });

    if (input) {
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                input.blur();
                const query = e.target.value.trim();
                if (query === currentSearchQuery && searchPending) return;
                if (query.length > 0) {
                    setSearchLayout(true);
                    saveSearchQuery(query);
                    const dropdown = document.getElementById('search-suggestions-dropdown');
                    if (dropdown) dropdown.classList.add('hidden');
                    clearTimeout(searchDebounce);
                    showLoading();
                    allResults = [];
                    currentSearchQuery = query;
                    runSearchQuery(query);
                }
            } else if (e.key === 'Escape') {
                const dropdown = document.getElementById('search-suggestions-dropdown');
                if (dropdown) dropdown.classList.add('hidden');
            }
        });

        input.addEventListener('input', (e) => {
            searchPending = false;
            activeSearchRequestId = null;
            Promise.resolve(window.pywebview?.api?.cancel_search?.()).catch(() => {});
            cancelArtistProfileRequests();
            isViewingArtistProfile = false;
            const query = e.target.value.trim();
            setSearchLayout(Boolean(query));
            clearTimeout(searchDebounce);
            currentSearchQuery = query;

            if (clearBtn) clearBtn.classList.toggle('visible', query.length > 0);

            if (query.length > 0) {
                const sugg = document.getElementById('search-suggestions-dropdown');
                if (sugg) sugg.classList.add('hidden');
                showLoading();
                searchDebounce = setTimeout(() => {
                    allResults = [];
                    currentSearchQuery = query;
                    runSearchQuery(query);
                }, 200);
            } else {
                currentSearchQuery = '';
                showPlaceholder();
            }
        });
    }

    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            Promise.resolve(window.pywebview?.api?.cancel_search?.()).catch(() => {});
            clearTimeout(searchDebounce);
            cancelArtistProfileRequests();
            lastResultKey = null;
            isViewingArtistProfile = false;
            if (input) input.value = '';
            if (clearBtn) clearBtn.classList.remove('visible');
            allResults = [];
            currentSearchQuery = '';
            setSearchLayout(false);
            showPlaceholder();
        });
    }

    // Sub-type Filters: Все, Треки, Плейлисты, Альбомы, Артисты
    document.querySelectorAll('.type-filter-btn[data-type]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.type-filter-btn[data-type]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentType = btn.dataset.type;
            syncTypeButtons();
            cancelArtistProfileRequests();
            clearTimeout(searchDebounce);
            setDiscoveryMode('history');

            if (isViewingArtistProfile && currentType !== 'artists') {
                isViewingArtistProfile = false;
            }

            if (currentType === 'artists') {
                const query = input?.value.trim() || currentSearchQuery;
                if (query) {
                    // S4-001: the tab holds a QUERY, not a confirmed artist
                    // entity - require the candidate confirmation step.
                    searchArtistProfile(query, null, { require_candidates: true });
                } else {
                    const container = document.getElementById('search-results');
                    if (container) {
                        container.innerHTML = '<div class="empty-state">Введите имя артиста для поиска</div>';
                    }
                }
            } else {
                const query = input?.value.trim() || currentSearchQuery;
                if (query) {
                    showLoading();
                    allResults = [];
                    currentSearchQuery = query;
                    runSearchQuery(query);
                } else {
                    showPlaceholder();
                }
            }
        });
    });

    initSearchDiscovery(searchArtistProfile);
    setupSmartSearchSuggestions();
    renderIcons();
}

// Global accessor to navigate to an artist profile
// S4-001: callers that pass a free-text QUERY (not a confirmed artist entity)
// must set { require_candidates: true } so the backend offers candidates
// instead of auto-opening the profile of a channel that merely matches the text.
const KNOWN_COLLAB_GROUPS = new Set([
    'tyler, the creator',
    'earth, wind & fire',
    'crosby, stills, nash & young',
    'crosby, stills & nash',
    'simon & garfunkel',
    'hall & oates',
    'daryl hall & john oates',
    'emerson, lake & palmer',
    'kool & the gang',
    'kc & the sunshine band',
    'blood, sweat & tears',
    'above & beyond',
    'florence + the machine',
    'florence and the machine',
    'huey lewis & the news',
    'tom petty and the heartbreakers',
    'bob marley & the wailers',
    'joan jett & the blackhearts',
    'marina and the diamonds'
]);

export function cleanArtistQuery(name) {
    if (!name || typeof name !== 'string') return '';
    let cleaned = name.replace(/\s*-\s*Topic\b/gi, '')
                      .replace(/\bVEVO\b/gi, '')
                      .replace(/\bOfficial\b/gi, '')
                      .replace(/\bRecords\b/gi, '')
                      .trim();

    // Check if known group that contains punctuation / ampersand
    if (KNOWN_COLLAB_GROUPS.has(cleaned.toLowerCase())) {
        return cleaned;
    }

    // Handle collaboration strings: " feat. ", " ft. ", " featuring ", " & ", " x ", etc.
    const parts = cleaned.split(/\s*(?:,|&|\+|;|\bx\b|\bfeat\.?|\bft\.?|\bfeaturing\b)\s*/i)
                         .map(s => s.trim())
                         .filter(Boolean);
    if (parts.length > 0) {
        return parts[0];
    }
    return cleaned;
}

export function searchArtistProfile(artistName, context = null, options = null) {
    if (!artistName || artistName === 'Unknown') return;

    // Dismiss any open modal overlay immediately so artist view is visible
    document.querySelectorAll('.modal-overlay, #album-modal-container, #playlist-modal-container').forEach(m => {
        m.style.display = 'none';
        closeModalFocusTrap(m);
    });

    const cleanName = options?.require_candidates ? String(artistName).trim() : cleanArtistQuery(artistName);
    if (!cleanName) return;

    const artistRef = { ...(context ? { context } : {}), ...((options && typeof options === 'object') ? options : {}) };
    artistRef.rawName = artistName;
    if (context && typeof context === 'object') artistRef.hintTrack = context;

    // Switch to dedicated artist view (#view-artist), leaving search results and input untouched
    if (window.showPage) {
        window.showPage('artist');
    } else if (window.NeDotify?.showPage) {
        window.NeDotify.showPage('artist');
    }

    const artistContainer = document.getElementById('view-artist');
    loadArtistProfile(cleanName, artistContainer, artistRef);
}

window.searchArtistProfile = searchArtistProfile;

function trackDedupKey(t) {
    const src = String(t.source || '').toLowerCase().trim();
    const sid = String(t.source_id || t.id || '').trim();
    if (src && sid) return `${src}::${sid}`;
    const title = String(t.title || '').toLowerCase().trim();
    const artist = String(t.artist || '').toLowerCase().trim();
    const dur = t.duration ? String(Math.round(Number(t.duration)) || '') : '';
    return `fallback::${title}__${artist}__${dur}`;
}

export function onSearchResults(data) {
    if (!currentSearchQuery || !data) return;
    if (data.request_id != null && data.request_id !== activeSearchRequestId) return;
    if (data.query && data.query !== currentSearchQuery) return;
    if (typeof data.offline === 'boolean') searchIsOffline = data.offline;
    if (data && data.source === '__completion__') {
        searchPending = false;
        if (data.query && data.query !== currentSearchQuery) {
            return; // Stale completion — a newer query is already in flight
        }
        const container = document.getElementById('search-results');
        if (container && container.querySelector('.spinner') && allResults.length === 0) {
            container.innerHTML = '<div class="empty-state">Ничего не найдено</div>';
            renderCorrectionContext(container);
            renderOfflineSearchNote(container);
        }
        if (allResults.length === 0 && !isViewingArtistProfile) offerSearchCorrections();
        return;
    }
    // Don't let provider bursts overwrite an active artist profile, but allow explicit type switches
    if (isViewingArtistProfile && data && data.type !== 'artists' && currentType === 'artists') {
        return;
    }
    if (data.query && data.query !== currentSearchQuery) {
        return; // Stale result — ignore
    }
    if (data.type && currentType !== 'all' && data.type !== currentType) return;
    const resultKey = `${data.query || ''}|${data.type || currentType}`;
    if (resultKey !== lastResultKey) {
        lastResultKey = resultKey;
        allResults = [];
    }
    const incoming = Array.isArray(data.tracks) ? data.tracks : [];
    if (incoming.length > 0) {
        const filteredTracks = filterVisibleTracks(incoming);
        if (filteredTracks.length > 0) {
            const seen = new Set(allResults.map(trackDedupKey));
            for (const t of filteredTracks) {
                const key = trackDedupKey(t);
                if (!seen.has(key)) {
                    seen.add(key);
                    allResults.push(t);
                }
            }
            // Rank exact matches ahead of title and artist matches.
            if (currentSearchQuery) {
                const fold = (s) => String(s || '').toLowerCase().replace(/ё/g, 'е');
                const query = fold(currentSearchQuery);
                const rank = (t) => {
                    const title = fold(t.title), artist = fold(t.artist);
                    if (!query) return 3;
                    if (title === query || (artist + ' - ' + title) === query) return 0;
                    if (title.startsWith(query) || title.includes(query)) return 1;
                    if (artist.includes(query)) return 2;
                    return 3;
                };
                allResults = allResults
                    .map((t, i) => [t, i])
                    .sort((a, b) => (rank(a[0]) - rank(b[0])) || (a[1] - b[1]))
                    .map(([t]) => t);
            }
            renderResults(allResults);
            return;
        }
    }
    // Empty chunk: keep spinner until completion sentinel arrives
}

function renderResults(tracks) {
    if (searchBatchRafId) {
        cancelAnimationFrame(searchBatchRafId);
        searchBatchRafId = null;
    }

    const container = document.getElementById('search-results');
    if (!container) return;

    if (!tracks || tracks.length === 0) {
        container.innerHTML = '<div class="empty-state">Ничего не найдено</div>';
        return;
    }

    const renderKey = `${lastResultKey}|${currentType}`;
    const trackList = container.querySelector('.track-list');
    const isSameRequest = container._renderKey === renderKey;
    container._renderKey = renderKey;


    if (['all', 'tracks'].includes(currentType) && isSameRequest && trackList) {
        const children = trackList.children;
        let canAppend = children.length > 0 && children.length <= tracks.length;
        if (canAppend) {
            for (let j = 0; j < children.length; j++) {
                const childTrack = children[j]._trackData;
                if (!childTrack || trackDedupKey(childTrack) !== trackDedupKey(tracks[j])) {
                    canAppend = false;
                    break;
                }
            }
        }
        if (canAppend) {
            for (let j = 0; j < children.length; j++) {
                children[j]._tracksArray = tracks;
            }
            renderSearchResultsBatch(container, tracks, false);
            return;
        }
        // Streaming search re-sorted or reordered results (BUG-WIN-006):
        // Re-render track-list cleanly without blowing away header context/banners
        renderSearchResultsBatch(container, tracks, true);
        return;
    }


    container.innerHTML = '';
    renderCorrectionContext(container);
    renderOfflineSearchNote(container);

    // Filter by selected sub-type (all, tracks, playlists, albums, artists)
    let displayTracks = tracks;

    if (currentType === 'playlists') {
        const playlistMap = new Map();
        tracks.forEach((t, idx) => {
            if (t.type === 'playlist') {
                const key = String(t.source_id || t.id || idx);
                if (!playlistMap.has(key)) playlistMap.set(key, t);
            }
        });
        const playlistList = Array.from(playlistMap.values());
        if (playlistList.length > 0) {
            renderPlaylistGrid(playlistList, container);
            renderIcons();
            return;
        }
        container.innerHTML = '<div class="empty-state">Плейлисты не найдены</div>';
        return;
    }

    if (currentType === 'albums') {
        const albums = new Map();
        for (const item of tracks) {
            if (item.type !== 'album' || (item.source !== 'local' && !item.source_id)) continue;
            const key = item.source === 'local' ? `local:${item.artist}:${item.title}` : `${item.source}:${item.source_id}`;
            if (!albums.has(key)) albums.set(key, item);
        }
        if (albums.size) renderAlbumGrid([...albums.values()], container);
        else container.innerHTML = '<div class="empty-state">Альбомы не найдены</div>';
        renderIcons();
        return;
    }
    if (currentType === 'artists') return;

    // Suggestion banner for artist profile in 'all' view
    if (currentType === 'all' && currentSearchQuery) {
        const artistSuggest = document.createElement('div');
        artistSuggest.style.cssText = 'padding: 12px 16px; margin-bottom: 16px; border-radius: 14px; background: rgba(var(--primary-rgb), 0.08); border: 1px solid rgba(var(--primary-rgb), 0.15); display: flex; justify-content: space-between; align-items: center; animation: fadeIn 0.3s ease;';
        artistSuggest.innerHTML = `
            <div style="display:flex; align-items:center; gap:10px; font-size:13px; color:var(--text-main)">
                <i data-lucide="user" style="width:16px;height:16px;color:var(--primary)"></i>
                <span>Посмотреть профиль исполнителя <strong>"${escapeHtml(currentSearchQuery)}"</strong></span>
            </div>
            <button class="type-filter-btn active" style="margin: 0; padding: 4px 12px; font-size:11px;">Открыть</button>
        `;
        artistSuggest.querySelector('button').addEventListener('click', () => {
            // S4-001: the banner invites a profile for a free-text query, so the
            // click must go through the candidate confirmation, not auto-open.
            searchArtistProfile(currentSearchQuery, null, { require_candidates: true });
        });
        container.appendChild(artistSuggest);
    }

    renderSearchResultsBatch(container, displayTracks);
}

const SEARCH_BATCH_SIZE = 12;

function renderSearchResultsBatch(container, displayTracks, replace = false) {
    if (searchBatchRafId) {
        cancelAnimationFrame(searchBatchRafId);
        searchBatchRafId = null;
    }

    let list = container.querySelector('.track-list');
    if (!list) {
        list = document.createElement('div');
        list.className = 'track-list';
        container.appendChild(list);
    }
    if (replace) {
        list.innerHTML = '';
    }



    container.querySelector('.search-more-results')?.remove();
    container.querySelector('.search-artists-shelf')?.remove();
    list.replaceChildren();
    const fragment = document.createDocumentFragment();
    const end = Math.min(displayTracks.length, visibleSearchCount);
    for (let index = 0; index < end; index++) fragment.appendChild(createTrackElement(displayTracks[index], index, displayTracks, getCurrentTrack()));
    list.appendChild(fragment);
    renderIcons(list);
    if (end < displayTracks.length) {
        const more = document.createElement('button');
        more.className = 'home-pill search-more-results';
        more.textContent = `Показать больше (${displayTracks.length - end})`;
        more.addEventListener('click',()=>{visibleSearchCount += SEARCH_BATCH_SIZE;renderSearchResultsBatch(container,displayTracks);});
        container.appendChild(more);
    }
    if (currentType === 'all') {
        const artists = new Map();
        for (const track of displayTracks) {
            const people = track.artists?.length ? track.artists : [{name:track.artist}];
            for (const person of people) {
                const name = typeof person === 'string' ? person : person.name;
                if (!name || artists.size >= 8) continue;
                const key = `${track.source}:${person.id || person.browseId || name.toLowerCase()}`;
                if (!artists.has(key)) artists.set(key,{name,track});
            }
        }
        if (artists.size) {
            const shelf = document.createElement('section');
            shelf.className = 'search-artists-shelf';
            shelf.innerHTML = '<h2>Исполнители</h2><div class="search-artists-cards"></div>';
            for (const {name,track} of artists.values()) {
                const button = document.createElement('button');
                button.className = 'search-artist-card';
                button.innerHTML = `${artistAvatarHtml(name)}<strong>${escapeHtml(name)}</strong>`;
                button.addEventListener('click',()=>searchArtistProfile(name,{source:track.source,source_id:track.source_id}));
                shelf.lastElementChild.appendChild(button);
            }
            container.appendChild(shelf);
        }
    }
}

function renderAlbumGrid(albums, container) {
    const albumGrid = document.createElement('div');
    albumGrid.className = 'album-cards-grid';
    albumGrid.style.cssText = 'display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 18px; margin-bottom: 24px; animation: fadeIn 0.3s ease;';

    const colors = [
        'linear-gradient(135deg, #f53d3d 0%, #ff803b 100%)',
        'linear-gradient(135deg, #7b2cbf 0%, #e0aaff 100%)',
        'linear-gradient(135deg, #240b36 0%, #c31432 100%)',
        'linear-gradient(135deg, #0f2027 0%, #203a43 100%)',
        'linear-gradient(135deg, #11998e 0%, #38ef7d 100%)',
        'linear-gradient(135deg, #ff007f 0%, #ff80b3 100%)',
        'linear-gradient(135deg, #0052d4 0%, #4364f7 100%)',
        'linear-gradient(135deg, #fc4a1a 0%, #f7b733 100%)',
        'linear-gradient(135deg, #1a2a6c 0%, #b21f1f 100%)',
        'linear-gradient(135deg, #8a2387 0%, #e94057 100%)'
    ];

    albums.forEach((album, idx) => {
        const title = album.title || album.album || 'Unknown Album';
        const artist = album.artist || 'Unknown Artist';
        const cover = album.cover_url || album.cover_path || album.cover || '';
        const year = album.year ? `${album.year} г.` : '';
        const trackCountStr = album.track_count ? `${album.track_count} треков` : 'Альбом';
        const sourceLabel = album.source === 'local' ? 'Из библиотеки' : (album.source === 'youtube' ? 'YouTube Music' : 'iTunes');
        const metaStr = [year, trackCountStr, sourceLabel].filter(Boolean).join(' • ');

        let hash = 0;
        for (let i = 0; i < title.length; i++) hash = ((hash << 5) - hash) + title.charCodeAt(i);
        const grad = colors[Math.abs(hash) % colors.length];

        const card = document.createElement('div');
        card.className = 'feed-card album-card';
        card.style.cssText = 'padding: 14px; border-radius: 16px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); display: flex; flex-direction: column; gap: 10px; cursor: pointer; transition: transform 0.2s, background 0.2s, box-shadow 0.2s; position: relative;';

        card.innerHTML = `
            <div class="feed-card-cover album-cover-wrap fallback-gradient" style="width: 100%; aspect-ratio: 1/1; border-radius: 12px; overflow: hidden; background: ${grad}; display: flex; align-items: center; justify-content: center; position: relative; box-shadow: 0 8px 20px rgba(0,0,0,0.35);">
                <svg class="fallback-note-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:40%;height:40%;opacity:0.6;position:relative;z-index:1;"><path d="M9 18V5l12-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="18" cy="16" r="3"></circle></svg>
                ${cover ? `<img src="${escapeHtml(cover)}" alt="" loading="lazy" decoding="async" data-hide-on-error="1" style="width:100%;height:100%;object-fit:cover;position:absolute;top:0;left:0;z-index:2;">` : ''}
                <div class="album-play-overlay" style="position:absolute; inset:0; background:rgba(0,0,0,0.45); display:flex; align-items:center; justify-content:center; opacity:0; transition:opacity 0.2s; z-index:3;">
                    <button class="album-play-btn" style="width:44px; height:44px; border-radius:50%; background:var(--primary); color:#fff; border:none; display:flex; align-items:center; justify-content:center; cursor:pointer; box-shadow:0 4px 12px rgba(0,0,0,0.4); transition:transform 0.2s;">
                        <i data-lucide="play" style="width:20px;height:20px;fill:currentColor"></i>
                    </button>
                </div>
            </div>
            <div style="display:flex; flex-direction:column; gap:3px; overflow:hidden;">
                <div style="font-weight: 700; font-size: 14px; color: #ffffff; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(title)}">${escapeHtml(title)}</div>
                <div style="font-size: 12px; color: var(--text-sec); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(artist)}</div>
                <div style="font-size: 11px; color: var(--primary); font-weight:600; margin-top:2px;">${escapeHtml(metaStr)}</div>
            </div>
        `;

        // Click play button directly
        const playBtn = card.querySelector('.album-play-btn');
        if (playBtn) {
            playBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                playAlbum(album, card);
            });
        }

        // Card click -> Open Album Modal / Details
        card.addEventListener('click', (e) => {
            if (e.target.closest('.album-play-btn')) return;
            openAlbumModal(album);
        });

        // Hover effects
        card.addEventListener('mouseenter', () => {
            card.style.transform = 'translateY(-4px)';
            card.style.background = 'rgba(255,255,255,0.08)';
            const overlay = card.querySelector('.album-play-overlay');
            if (overlay) overlay.style.opacity = '1';
        });
        card.addEventListener('mouseleave', () => {
            card.style.transform = 'translateY(0)';
            card.style.background = 'rgba(255,255,255,0.05)';
            const overlay = card.querySelector('.album-play-overlay');
            if (overlay) overlay.style.opacity = '0';
        });

        albumGrid.appendChild(card);
    });

    container.appendChild(albumGrid);
}

let albumFetchCleanup = null;
let albumModalGeneration = 0;
export async function fetchAlbumDetails(album) {
    albumFetchCleanup?.();
    const requestId = `album-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    if (!window.pywebview?.api?.get_album_details) return {status: 'unavailable'};
    return new Promise(resolve => {
        let timer;
        const finish = data => {
            clearTimeout(timer);
            document.removeEventListener('nedotify:album_details_ready', receive);
            if (albumFetchCleanup === cancel) albumFetchCleanup = null;
            resolve(data);
        };
        const cancel = () => finish({status: 'unavailable', cancelled: true});
        const receive = event => { if (event.detail?.request_id === requestId) finish(event.detail); };
        albumFetchCleanup = cancel;
        document.addEventListener('nedotify:album_details_ready', receive);
        timer = setTimeout(() => finish({status: 'unavailable'}), 10000);
        try {
            Promise.resolve(window.pywebview.api.get_album_details(album, requestId))
                .then(result => { if (result?.status !== 'loading') finish(result || {status: 'unavailable'}); })
                .catch(() => finish({status: 'unavailable'}));
        } catch (_) { finish({status: 'unavailable'}); }
    });
}
window.fetchAlbumDetails = fetchAlbumDetails;

export async function playAlbum(album, cardElement = null) {
    if (!album) return;
    const playBtn = cardElement?.querySelector('.album-play-btn');
    if (playBtn) {
        playBtn.innerHTML = '<div class="spinner" style="width:18px;height:18px;border-width:2px;"></div>';
    }

    try {
        const result = await fetchAlbumDetails(album);
        if (result.cancelled) return;
        const tracks = result.status === 'found' ? result.tracks || [] : [];
        if (tracks.length && window.pywebview?.api?.play_track) {
            await window.pywebview.api.play_track(tracks[0], tracks, 0);
        } else {
            showToast(result.status === 'unavailable' ? 'Не удалось проверить альбом. Попробуйте ещё раз.' : 'Альбом или его треклист не найден', 'info');
        }
    } catch (e) {
        console.error("Error playing album:", e);
    } finally {
        if (playBtn) {
            playBtn.innerHTML = '<i data-lucide="play" style="width:20px;height:20px;fill:currentColor"></i>';
            renderIcons();
        }
    }
}

// The two detail overlays below hide themselves from three different paths
// (backdrop click, the X button, and "play everything"). Routing all of them
// through one place is what keeps visibility and the focus trap in step - a
// modal that is display:none but still trapped would swallow every Tab.
function hideDetailModal(modal) {
    if (!modal) return;
    modal.style.display = 'none';
    if (modal.id === 'album-detail-modal') { albumModalGeneration++; albumFetchCleanup?.(); }
    closeModalFocusTrap(modal);
}

export async function openAlbumModal(album) {
    const generation = ++albumModalGeneration;
    let modal = document.getElementById('album-detail-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'album-detail-modal';
        modal.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,0.75); backdrop-filter:blur(10px); z-index:9999; display:flex; align-items:center; justify-content:center; animation:fadeIn 0.25s ease; padding:20px;';
        modal.addEventListener('click', (e) => {
            if (e.target === modal) hideDetailModal(modal);
        });
        document.body.appendChild(modal);
    }
    modal.style.display = 'flex';
    modal.innerHTML = `
        <div style="background:var(--bg-card, #181818); border:1px solid rgba(255,255,255,0.12); border-radius:20px; width:100%; max-width:680px; max-height:85vh; display:flex; flex-direction:column; overflow:hidden; box-shadow:0 20px 50px rgba(0,0,0,0.6);">
            <div style="display:flex; justify-content:space-between; align-items:center; padding:16px 20px; border-bottom:1px solid rgba(255,255,255,0.08);">
                <span data-album-detail-kind style="font-weight:700; font-size:15px; color:var(--text-main);">Альбом</span>
                <button id="close-album-modal" style="background:none; border:none; color:var(--text-sec); cursor:pointer; padding:4px;">
                    <i data-lucide="x" style="width:20px;height:20px"></i>
                </button>
            </div>
            <div style="padding:20px; display:flex; gap:20px; align-items:center; background:linear-gradient(180deg, rgba(255,255,255,0.06) 0%, transparent 100%);">
                <img data-album-detail-cover src="${escapeHtml(album.cover_url || album.cover || album.cover_path || '')}" alt="" loading="lazy" decoding="async" data-hide-on-error="1" style="width:110px; height:110px; border-radius:12px; object-fit:cover; box-shadow:0 8px 24px rgba(0,0,0,0.4);">
                <div style="display:flex; flex-direction:column; gap:6px; flex:1; overflow:hidden;">
                    <div data-album-detail-title style="font-size:20px; font-weight:800; color:#fff; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(album.title || 'Альбом')}</div>
                    <div data-album-detail-artist style="font-size:14px; color:var(--text-sec);">${escapeHtml(album.artist || 'Исполнитель')}</div>
                    <div data-album-detail-info style="font-size:12px; color:var(--text-sec); opacity:0.8;">${album.year ? escapeHtml(String(album.year)) + ' г. • ' : ''}${album.track_count ? escapeHtml(String(album.track_count)) + ' треков' : 'Альбом'}</div>
                    <div style="margin-top:8px; display:flex; gap:10px;">
                        <button id="btn-play-full-album" style="padding:8px 18px; border-radius:24px; border:none; background:var(--primary); color:#fff; font-weight:700; font-size:12px; cursor:pointer; display:flex; align-items:center; gap:6px;">
                            <i data-lucide="play" style="width:14px;height:14px;fill:currentColor"></i> Слушать всё
                        </button>
                    </div>
                </div>
            </div>
            <div id="album-modal-tracks" style="flex:1; overflow-y:auto; padding:12px 20px; display:flex; flex-direction:column; gap:4px;">
                <div class="empty-state" style="padding:30px;"><div class="spinner"></div><span>Загрузка треков альбома...</span></div>
            </div>
        </div>
    `;
    renderIcons();

    // Initial focus: this overlay is a read-only detail view, so its X button
    // is the only sensible landing spot. Armed after innerHTML is written,
    // because that is when the close button exists.
    openModalFocusTrap(modal, { initialFocus: '#close-album-modal' });

    document.getElementById('close-album-modal')?.addEventListener('click', () => {
        hideDetailModal(modal);
    }, { once: true });

    const playAll = document.getElementById('btn-play-full-album');
    if (playAll) playAll.disabled = true;
    const result = await fetchAlbumDetails(album);
    if (generation !== albumModalGeneration || result.cancelled || modal.style.display === 'none') return;
    const tracksContainer = document.getElementById('album-modal-tracks');
    if (!tracksContainer) return;
    if (result.status !== 'found') {
        tracksContainer.innerHTML = `<div class="empty-state">${result.status === 'unavailable' ? 'Не удалось проверить альбом: каталог временно недоступен' : 'Альбом не найден в каталоге'}<button class="btn btn-secondary">Повторить</button></div>`;
        tracksContainer.querySelector('button').addEventListener('click', () => openAlbumModal(album));
        return;
    }
    const albumTracks = result.tracks || [];
    const details = {...album, ...(result.album || {})};
    const kind = String(details.album_type || details.type || 'album').toLowerCase();
    const releaseLabel = {single:'Сингл', ep:'EP', compilation:'Сборник'}[kind] || 'Альбом';
    const summary = {
        title: details.title || 'Альбом', artist: details.artist || 'Исполнитель', kind: releaseLabel,
        info: `${details.year ? String(details.year) + ' г. • ' : ''}${albumTracks.length} треков`,
    };
    for (const [field, text] of Object.entries(summary)) {
        const element = modal.querySelector(`[data-album-detail-${field}]`);
        if (element) element.textContent = text;
    }
    const cover = modal.querySelector('[data-album-detail-cover]');
    if (cover && details.cover_url) { cover.src = details.cover_url; cover.style.display = ''; }
    if (!albumTracks.length) {
        tracksContainer.innerHTML = '<div class="empty-state">Альбом подтверждён, но его треклист недоступен</div>';
        return;
    }
    if (playAll) playAll.disabled = false;
    tracksContainer.innerHTML = result.verified ? '' : '<div class="lyric-notice">Из библиотеки — данные из тегов файла</div>';
    albumTracks.forEach((t, idx) => {
        tracksContainer.appendChild(createTrackElement(t, idx, albumTracks, getCurrentTrack()));
    });
    renderIcons();

    document.getElementById('btn-play-full-album')?.addEventListener('click', () => {
        if (albumTracks.length > 0 && window.pywebview?.api?.play_track) {
            window.pywebview.api.play_track(albumTracks[0], albumTracks, 0);
            hideDetailModal(modal);
        }
    }, { once: true });
}

window.openAlbumModal = openAlbumModal;
window.playAlbum = playAlbum;

export function renderPlaylistGrid(playlists, container) {
    const playlistGrid = document.createElement('div');
    playlistGrid.className = 'playlist-cards-grid';
    playlistGrid.style.cssText = 'display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 18px; margin-bottom: 24px; animation: fadeIn 0.3s ease;';

    playlists.forEach((pl, idx) => {
        const title = pl.title || pl.name || 'Плейлист';
        const author = pl.author || pl.artist || 'NeDotify';
        const cover = pl.cover_url || pl.cover_path || pl.cover || '';
        const trackCount = pl.track_count || 10;
        const trackCountStr = typeof trackCount === 'number' ? `${trackCount} треков` : 'Плейлист';
        const grad = getCoverFallbackGradient(title);

        const card = document.createElement('div');
        card.className = 'feed-card playlist-card';
        card._playlistData = pl;
        card.dataset.playlist = JSON.stringify(pl);
        card.dataset.id = pl.id || '';
        card.dataset.sourceId = pl.source_id || pl.id || '';
        card.dataset.source = pl.source || 'youtube';
        card.style.cssText = 'padding: 14px; border-radius: 16px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); display: flex; flex-direction: column; gap: 10px; cursor: pointer; transition: transform 0.2s, background 0.2s, box-shadow 0.2s; position: relative;';

        card.innerHTML = `
            <div class="feed-card-cover playlist-cover-wrap fallback-gradient" style="width: 100%; aspect-ratio: 1/1; border-radius: 12px; overflow: hidden; background: ${grad}; display: flex; align-items: center; justify-content: center; position: relative; box-shadow: 0 8px 20px rgba(0,0,0,0.35);">
                <svg class="fallback-note-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:40%;height:40%;opacity:0.6;position:relative;z-index:1;"><path d="M9 18V5l12-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="18" cy="16" r="3"></circle></svg>
                ${cover ? `<img src="${escapeHtml(cover)}" alt="" loading="lazy" decoding="async" data-hide-on-error="1" style="width:100%;height:100%;object-fit:cover;position:absolute;top:0;left:0;z-index:2;">` : ''}
                <div class="playlist-play-overlay" style="position:absolute; inset:0; background:rgba(0,0,0,0.45); display:flex; align-items:center; justify-content:center; opacity:0; transition:opacity 0.2s; z-index:3;">
                    <button class="playlist-play-btn" style="width:44px; height:44px; border-radius:50%; background:var(--primary); color:#fff; border:none; display:flex; align-items:center; justify-content:center; cursor:pointer; box-shadow:0 4px 12px rgba(0,0,0,0.4); transition:transform 0.2s;">
                        <i data-lucide="play" style="width:20px;height:20px;fill:currentColor"></i>
                    </button>
                </div>
            </div>
            <div style="display:flex; flex-direction:column; gap:3px; overflow:hidden;">
                <div style="font-weight: 700; font-size: 14px; color: #ffffff; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(title)}">${escapeHtml(title)}</div>
                <div style="font-size: 12px; color: var(--text-sec); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(author)}</div>
                <div style="font-size: 11px; color: var(--primary); font-weight:600; margin-top:2px;">${escapeHtml(trackCountStr)}</div>
            </div>
        `;

        // Click play button directly
        const playBtn = card.querySelector('.playlist-play-btn');
        if (playBtn) {
            playBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                playPlaylist(pl, card);
            });
        }

        // Card click -> Open Playlist Modal / Details
        card.addEventListener('click', (e) => {
            if (e.target.closest('.playlist-play-btn')) return;
            openPlaylistModal(pl);
        });

        // Hover effects
        card.addEventListener('mouseenter', () => {
            card.style.transform = 'translateY(-4px)';
            card.style.background = 'rgba(255,255,255,0.08)';
            const overlay = card.querySelector('.playlist-play-overlay');
            if (overlay) overlay.style.opacity = '1';
        });
        card.addEventListener('mouseleave', () => {
            card.style.transform = 'translateY(0)';
            card.style.background = 'rgba(255,255,255,0.05)';
            const overlay = card.querySelector('.playlist-play-overlay');
            if (overlay) overlay.style.opacity = '0';
        });

        playlistGrid.appendChild(card);
    });

    container.appendChild(playlistGrid);
}

export async function playPlaylist(playlist, cardElement = null) {
    if (!playlist) return;
    const playBtn = cardElement?.querySelector('.playlist-play-btn');
    if (playBtn) {
        playBtn.innerHTML = '<div class="spinner" style="width:18px;height:18px;border-width:2px;"></div>';
    }

    try {
        let tracks = [];
        const plId = playlist.source_id || playlist.id;
        const source = playlist.source || 'youtube';

        if (window.pywebview?.api?.get_playlist_tracks) {
            const res = await window.pywebview.api.get_playlist_tracks(plId, source);
            tracks = Array.isArray(res) ? res : (res?.tracks || []);
        }

        if (tracks && tracks.length > 0) {
            if (window.pywebview?.api?.play_track) {
                window.pywebview.api.play_track(tracks[0], tracks, 0);
            } else if (window.NeDotify?.playTrack) {
                window.NeDotify.playTrack(tracks[0], tracks);
            }
        } else {
            // Fallback: search query for playlist title
            const q = (playlist.title || playlist.name || '').trim();
            if (q && window.pywebview?.api?.search) {
                window.pywebview.api.search(q, source);
            }
        }
    } catch (e) {
        console.error("Error playing playlist:", e);
    } finally {
        if (playBtn) {
            playBtn.innerHTML = '<i data-lucide="play" style="width:20px;height:20px;fill:currentColor"></i>';
            renderIcons();
        }
    }
}

export async function openPlaylistModal(playlist) {
    let modal = document.getElementById('playlist-detail-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'playlist-detail-modal';
        modal.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,0.75); backdrop-filter:blur(10px); z-index:9999; display:flex; align-items:center; justify-content:center; animation:fadeIn 0.25s ease; padding:20px;';
        modal.addEventListener('click', (e) => {
            if (e.target === modal) hideDetailModal(modal);
        });
        document.body.appendChild(modal);
    }
    modal.style.display = 'flex';
    modal.innerHTML = `
        <div style="background:var(--bg-card, #181818); border:1px solid rgba(255,255,255,0.12); border-radius:20px; width:100%; max-width:680px; max-height:85vh; display:flex; flex-direction:column; overflow:hidden; box-shadow:0 20px 50px rgba(0,0,0,0.6);">
            <div style="display:flex; justify-content:space-between; align-items:center; padding:16px 20px; border-bottom:1px solid rgba(255,255,255,0.08);">
                <span style="font-weight:700; font-size:15px; color:var(--text-main);">Плейлист</span>
                <button id="close-playlist-modal" style="background:none; border:none; color:var(--text-sec); cursor:pointer; padding:4px;">
                    <i data-lucide="x" style="width:20px;height:20px"></i>
                </button>
            </div>
            <div style="padding:20px; display:flex; gap:20px; align-items:center; background:linear-gradient(180deg, rgba(255,255,255,0.06) 0%, transparent 100%);">
                <img src="${escapeHtml(playlist.cover_url || playlist.cover || playlist.cover_path || '')}" alt="" loading="lazy" decoding="async" data-hide-on-error="1" style="width:110px; height:110px; border-radius:12px; object-fit:cover; box-shadow:0 8px 24px rgba(0,0,0,0.4);">
                <div style="display:flex; flex-direction:column; gap:6px; flex:1; overflow:hidden;">
                    <div style="font-size:20px; font-weight:800; color:#fff; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(playlist.title || playlist.name || 'Плейлист')}</div>
                    <div style="font-size:14px; color:var(--text-sec);">${escapeHtml(playlist.author || playlist.artist || 'NeDotify')}</div>
                    <div style="font-size:12px; color:var(--text-sec); opacity:0.8;">${playlist.track_count ? escapeHtml(String(playlist.track_count)) + ' треков' : 'Плейлист'}</div>
                    <div style="margin-top:8px; display:flex; gap:10px;">
                        <button id="btn-play-full-playlist" style="padding:8px 18px; border-radius:24px; border:none; background:var(--primary); color:#fff; font-weight:700; font-size:12px; cursor:pointer; display:flex; align-items:center; gap:6px;">
                            <i data-lucide="play" style="width:14px;height:14px;fill:currentColor"></i> Слушать всё
                        </button>
                    </div>
                </div>
            </div>
            <div id="playlist-modal-tracks" style="flex:1; overflow-y:auto; padding:12px 20px; display:flex; flex-direction:column; gap:4px;">
                <div class="empty-state" style="padding:30px;"><div class="spinner"></div><span>Загрузка треков плейлиста...</span></div>
            </div>
        </div>
    `;
    renderIcons();

    // Initial focus: read-only detail view, so the X button.
    openModalFocusTrap(modal, { initialFocus: '#close-playlist-modal' });

    document.getElementById('close-playlist-modal')?.addEventListener('click', () => {
        hideDetailModal(modal);
    }, { once: true });

    let playlistTracks = [];
    if (window.pywebview?.api?.get_playlist_tracks) {
        try {
            const plId = playlist.source_id || playlist.id;
            const source = playlist.source || 'youtube';
            const res = await window.pywebview.api.get_playlist_tracks(plId, source);
            playlistTracks = Array.isArray(res) ? res : (res?.tracks || []);
        } catch (e) {
            console.error("Error loading playlist tracks:", e);
        }
    }

    const tracksContainer = document.getElementById('playlist-modal-tracks');
    if (!tracksContainer) return;

    if (!playlistTracks || playlistTracks.length === 0) {
        tracksContainer.innerHTML = '<div class="empty-state" style="padding:30px 0;">Треки этого плейлиста недоступны</div>';
        return;
    }

    tracksContainer.innerHTML = '';
    playlistTracks.forEach((t, idx) => {
        tracksContainer.appendChild(createTrackElement(t, idx, playlistTracks, getCurrentTrack()));
    });
    renderIcons();

    document.getElementById('btn-play-full-playlist')?.addEventListener('click', () => {
        if (playlistTracks.length > 0) {
            if (window.pywebview?.api?.play_track) {
                window.pywebview.api.play_track(playlistTracks[0], playlistTracks, 0);
            } else if (window.NeDotify?.playTrack) {
                window.NeDotify.playTrack(playlistTracks[0], playlistTracks);
            }
            hideDetailModal(modal);
        }
    }, { once: true });
}

window.renderPlaylistGrid = renderPlaylistGrid;
window.playPlaylist = playPlaylist;
window.openPlaylistModal = openPlaylistModal;

function showLoading() {
    if (searchBatchRafId) {
        cancelAnimationFrame(searchBatchRafId);
        searchBatchRafId = null;
    }
    const container = document.getElementById('search-results');
    if (container) {
        container.innerHTML = '<div class="empty-state"><div class="spinner"></div><span>Поиск...</span></div>';
    }
}

function showLoadingArtist(query) {
    if (searchBatchRafId) {
        cancelAnimationFrame(searchBatchRafId);
        searchBatchRafId = null;
    }
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
    renderIcons(wrapper);
}

function showPlaceholder() {
    searchPending = false;
    activeSearchRequestId = null;
    searchSuggestionGeneration++;
    suggestionRequestKey = '';
    setDiscoveryMode('history');
    if (searchBatchRafId) {
        cancelAnimationFrame(searchBatchRafId);
        searchBatchRafId = null;
    }
    const container = document.getElementById('search-results');
    if (container) {
        container.innerHTML = '<div class="empty-state"><i data-lucide="search" style="width:40px;height:40px;opacity:0.3"></i><span>Введите запрос для поиска музыки</span></div>';
        renderIcons(container);
    }
}

function syncTypeButtons() {
    document.querySelectorAll('.type-filter-btn[data-type]').forEach(button => {
        const active=button.dataset.type===currentType;
        button.classList.toggle('active',active);
        button.setAttribute('aria-pressed',String(active));
    });
}

function renderOfflineSearchNote(container) {
    if (!searchIsOffline || container.querySelector('[data-offline-search]')) return;
    const note = document.createElement('p');
    note.className = 'search-query-alternatives';
    note.dataset.offlineSearch = 'true';
    note.textContent = 'Офлайн: поиск среди музыки, доступной на этом компьютере.';
    container.prepend(note);
}

function renderCorrectionContext(container) {
    if (!correctionContext || correctionContext.query !== currentSearchQuery) return;
    if (container.querySelector('[data-original-query]')) return;
    const banner = document.createElement('div');
    banner.className = 'search-query-alternatives';
    banner.dataset.originalQuery = correctionContext.original;
    const text = document.createElement('p');
    text.textContent = `Поиск «${correctionContext.query}» вместо «${correctionContext.original}».`;
    const original = document.createElement('button');
    original.className = 'home-pill';
    original.textContent = `Искать исходный запрос «${correctionContext.original}»`;
    original.onclick = () => startSuggestedSearch(correctionContext.original);
    banner.append(text, original);
    container.prepend(banner);
}

function startSuggestedSearch(query, original = null) {
    const input = document.getElementById('search-input');
    if (input) input.value = query;
    clearTimeout(searchDebounce);
    allResults = [];
    lastResultKey = null;
    currentSearchQuery = query;
    correctionContext = original ? { original, query } : null;
    saveSearchQuery(query);
    showLoading();
    runSearchQuery(query, true);
}

async function offerSearchCorrections() {
    if (currentType === 'artists' || currentType === 'genres') return;
    const query = currentSearchQuery, type = currentType;
    const key = `${query}|${type}`;
    if (suggestionRequestKey === key) return;
    suggestionRequestKey = key;
    const generation = searchSuggestionGeneration;
    try {
        const suggestions = await window.pywebview?.api?.get_search_suggestions?.(query);
        if (generation !== searchSuggestionGeneration || query !== currentSearchQuery || type !== currentType || allResults.length) return;
        const container = document.getElementById('search-results');
        if (!container || !Array.isArray(suggestions) || !suggestions.length) return;
        const alternatives = document.createElement('div');
        alternatives.className = 'search-query-alternatives';
        const description = document.createElement('p');
        description.textContent = 'Ничего не найдено. Попробуйте другую раскладку или исправление опечатки:';
        alternatives.appendChild(description);
        for (const suggestion of suggestions.slice(0,3)) {
            if (typeof suggestion?.query !== 'string' || !suggestion.query.trim() || suggestion.query === query) continue;
            const button = document.createElement('button');
            button.className = 'home-pill';
            button.textContent = `${suggestion.query} (${suggestion.reason === 'layout' ? 'раскладка' : 'опечатка'})`;
            button.onclick = () => startSuggestedSearch(suggestion.query, correctionContext?.original || query);
            alternatives.appendChild(button);
        }
        if (alternatives.children.length > 1) container.appendChild(alternatives);
    } catch {}
}

function runSearchQuery(query, keepCorrection = false) {
    clearTimeout(searchDebounce);
    searchSuggestionGeneration++;
    suggestionRequestKey = '';
    searchIsOffline = false;
    if (!keepCorrection) correctionContext = null;
    if (currentType === 'genres') {currentType='tracks';syncTypeButtons();}
    if (currentType === 'artists') {searchArtistProfile(query, null, { require_candidates: true });return;}
    const type=currentType;
    visibleSearchCount = 12;
    searchPending = true;
    const requestId = activeSearchRequestId = `search-${++searchRequestGeneration}`;
    Promise.resolve().then(()=>api('search',query,'all',type==='all'?null:type,requestId)).catch(()=>{
        if(requestId!==activeSearchRequestId || query!==currentSearchQuery || type!==currentType) return;
        searchPending = false;
        const container=document.getElementById('search-results');
        if(!container) return;
        container.innerHTML='<div class="search-discovery-empty"><strong>Не удалось выполнить поиск</strong><p>Проверьте подключение и попробуйте снова.</p><button class="home-pill">Повторить</button></div>';
        container.querySelector('button').onclick=()=>{showLoading();runSearchQuery(query);};
    });
}

function api(method, ...args) {
    if (window.pywebview && window.pywebview.api) {
        return window.pywebview.api[method](...args);
    }
}

// ==========================================================================
// FEATURE 2: Smart Search (Search History & Genre Chips)
// ==========================================================================

const SEARCH_HISTORY_KEY = 'nedotify_search_history';
const MAX_SEARCH_HISTORY = 8;
export function getSearchHistory() {
    try {
        const raw = localStorage.getItem(SEARCH_HISTORY_KEY);
        return raw ? JSON.parse(raw) : [];
    } catch (e) {
        return [];
    }
}

export function saveSearchQuery(query) {
    if (!query || !query.trim()) return;
    const clean = query.trim();
    let history = getSearchHistory().filter(q => q.toLowerCase() !== clean.toLowerCase());
    history.unshift(clean);
    if (history.length > MAX_SEARCH_HISTORY) {
        history = history.slice(0, MAX_SEARCH_HISTORY);
    }
    try {
        localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(history));
    } catch (e) {}
}

export function removeSearchQuery(queryToDelete) {
    let history = getSearchHistory().filter(q => q !== queryToDelete);
    try {
        localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(history));
    } catch (e) {}
}

/**
 * Инициализирует выпадающее меню с историей запросов
 */
export function setupSmartSearchSuggestions() {
    const searchHeader = document.querySelector('.search-header-container');
    const input = document.getElementById('search-input');
    if (!searchHeader || !input) return;

    // Создаем контейнер дропдауна, если его еще нет
    let dropdown = document.getElementById('search-suggestions-dropdown');
    if (!dropdown) {
        dropdown = document.createElement('div');
        dropdown.id = 'search-suggestions-dropdown';
        dropdown.className = 'search-suggestions-dropdown hidden';
        searchHeader.appendChild(dropdown);
    }

    const renderSuggestions = () => {
        const history = getSearchHistory();

        const historyHtml = history.length > 0 ? history.map(item => `
            <div class="search-history-item">
                <button type="button" class="search-history-query" data-query="${escapeHtml(item)}">
                    <i data-lucide="history" style="width:14px;height:14px;opacity:0.6;"></i>
                    <span>${escapeHtml(item)}</span>
                </button>
                <button class="search-history-delete-btn" data-delete-query="${escapeHtml(item)}" title="Удалить из истории" aria-label="Удалить запрос: ${escapeHtml(item)}">
                    <i data-lucide="x" style="width:12px;height:12px"></i>
                </button>
            </div>
        `).join('') : '<div class="search-history-empty"><i data-lucide="search"></i><strong>Здесь будут ваши поиски</strong><span>Найдите трек, альбом или исполнителя</span></div>';

        dropdown.innerHTML = `
            <div class="search-history-section">
                <div class="search-history-header">
                    <span>Недавние поиски</span>
                    ${history.length > 0 ? '<button class="search-history-clear-all" id="btn-clear-all-history">Очистить</button>' : ''}
                </div>
                <div class="search-history-list">${historyHtml}</div>
            </div>
        `;

        if (window.lucide && typeof window.lucide.createIcons === 'function') {
            window.lucide.createIcons({ root: dropdown });
        }
    };

    // Фокус в инпут: показать историю
    input.addEventListener('focus', () => {
        renderSuggestions();
        dropdown.classList.remove('hidden');
    });

    // Обработка кликов внутри выпадающего списка через Event Delegation
    dropdown.addEventListener('click', (e) => {
        // Удаление конкретной записи истории
        const deleteBtn = e.target.closest('[data-delete-query]');
        if (deleteBtn) {
            e.stopPropagation();
            const queryToDelete = deleteBtn.dataset.deleteQuery;
            removeSearchQuery(queryToDelete);
            renderSuggestions();
            return;
        }

        // Очистить всю историю
        if (e.target.closest('#btn-clear-all-history')) {
            e.stopPropagation();
            localStorage.removeItem(SEARCH_HISTORY_KEY);
            renderSuggestions();
            return;
        }

        // Повторить сохранённый запрос обычным поиском.
        const triggerEl = e.target.closest('.search-history-query');
        if (triggerEl) {
            const query = triggerEl.dataset.query;
            if (query) {
                input.value = query;
                setSearchLayout(true);
                saveSearchQuery(query);
                dropdown.classList.add('hidden');
                isViewingArtistProfile = false;
                allResults = [];
                currentSearchQuery = query;
                showLoading();
                runSearchQuery(query);
            }
        }
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown' && !dropdown.classList.contains('hidden')) {
            const first = dropdown.querySelector('.search-history-query');
            if (first) { e.preventDefault(); first.focus(); }
        }
    });
    dropdown.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            input.focus();
            dropdown.classList.add('hidden');
            e.preventDefault();
        } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            const rows = [...dropdown.querySelectorAll('.search-history-query')];
            const index = rows.indexOf(document.activeElement);
            const next = index + (e.key === 'ArrowDown' ? 1 : -1);
            e.preventDefault();
            if (next < 0) input.focus();
            else rows[Math.min(next, rows.length - 1)]?.focus();
        }
    });

    // Клик вне поиска закрывает подсказки
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.search-header-container')) {
            dropdown.classList.add('hidden');
        }
    });
}
