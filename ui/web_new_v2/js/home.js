import { refreshFavoritesCovers, initHomeAtmosphere, updateHomeCoverCollage } from './home-atmosphere.js';
import { updateHomeCollections, openHomeLibrary, openHomeDialog } from './home-shell.js';
import { getPlaylistCover } from './library-view.js';
import { mountRecommendationControls } from './recommendation-controls.js';
import { mountPersonalWave } from './personal-wave.js';
import { formatTime, formatListeningTime, renderIcons, getCoverUrl, escapeHtml, coverImgHtml, artistAvatarHtml, renderPlaylistCoverCollage, sizeCanvasForDpr, registerCanvasDprListener, createTrackElement, showToast } from './utils.js';

const feedTimeouts = new Map();
let trackChangeCount = 0;
let homeLoadGeneration = 0;
let sectionRequestSequence = 0;
const sectionRequests = new Map();
export function isCurrentHomeEvent(sectionId, data) {
    const expectedId = sectionRequests.get(sectionId);
    // Legacy callers that did not start a tracked request may still deliver an
    // untagged array. Once a request is active, only its tagged response can
    // clear the loading state or replace the section.
    if (!expectedId) return true;
    const receivedId = data && typeof data === 'object' ? data.request_id : null;
    return typeof receivedId === 'string' && receivedId === expectedId &&
        expectedId.slice(0, expectedId.indexOf(':')) === String(homeLoadGeneration);
}

window.addEventListener('nedotify:recommendation_feedback_changed', () => loadHome());
window.addEventListener('nedotify:recommendation_mode_changed', () => loadHome());
let coverBackfillPromise = null;
let lastCoverBackfillAt = 0;

// Helper to stagger bridge calls and prevent backend burst / thread pool congestion
const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

function applyCoverBackground(el, rawUrl) {
    if (!el || !rawUrl) return;
    try {
        const u = new URL(String(rawUrl));
        if (u.protocol !== 'https:' && u.protocol !== 'data:') return;
        // u.href is already percent-encoded by the URL parser; encodeURI on top
        // would double-encode it ("%20" -> "%2520").
        el.style.backgroundImage = `url("${u.href}")`;
    } catch (e) {}
}

function renderSkeletons(containerId, count = 4) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';
    // Fragment: one insertion instead of one per skeleton card (search.js pattern).
    const fragment = document.createDocumentFragment();
    for (let i = 0; i < count; i++) {
        const card = document.createElement('div');
        card.className = 'skeleton-card';
        card.innerHTML = `
            <div class="skeleton-cover"></div>
            <div class="skeleton-title"></div>
            <div class="skeleton-sub"></div>
        `;
        fragment.appendChild(card);
    }
    container.appendChild(fragment);
}

export function clearFeedTimeout(sectionId) {
    if (sectionId === 'home-mixes') {
        const button = document.getElementById('home-refresh-mixes');
        if (button) { button.disabled = false; button.removeAttribute('aria-busy'); }
    }
    if (feedTimeouts.has(sectionId)) {
        clearTimeout(feedTimeouts.get(sectionId));
        feedTimeouts.delete(sectionId);
    }
}

function renderRetryButton(containerId, retryFn) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '<div style="display:flex;justify-content:center;width:100%"><button class="retry-btn">Повторить</button></div>';
    container.querySelector('.retry-btn').addEventListener('click', () => {
        renderSkeletons(containerId);
        retryFn();
    });
}

export function renderHomeRetry(containerId) {
    renderRetryButton(containerId, () => loadHome());
}

function requestHomeSection(containerId, methodName, args = [], refresh = false) {
    const generation = homeLoadGeneration;
    const request = () => {
        if (generation !== homeLoadGeneration) return;
        const requestId = `${generation}:${++sectionRequestSequence}`;
        sectionRequests.set(containerId, requestId);
        clearFeedTimeout(containerId);
        renderSkeletons(containerId);
        if (containerId === 'home-mixes') {
            const button = document.getElementById('home-refresh-mixes');
            if (button) { button.disabled = true; button.setAttribute('aria-busy', 'true'); }
        }
        if (containerId === 'home-recommended') {
            const section = document.getElementById('home-recommended-section');
            if (section) section.style.display = 'block';
        }
        feedTimeouts.set(containerId, setTimeout(() => {
            if (generation !== homeLoadGeneration || sectionRequests.get(containerId) !== requestId) return;
            feedTimeouts.delete(containerId);
            clearFeedTimeout(containerId);
            renderRetryButton(containerId, request);
        }, 20000));
        try {
            const method = window.pywebview?.api?.[methodName];
            if (typeof method !== 'function') throw new Error('Feed API unavailable');
            Promise.resolve(refresh ? method(...args, requestId, true) : method(...args, requestId)).catch(() => {
                if (sectionRequests.get(containerId) !== requestId || generation !== homeLoadGeneration) return;
                clearFeedTimeout(containerId);
                renderRetryButton(containerId, request);
            });
        } catch (err) {
            clearFeedTimeout(containerId);
            renderRetryButton(containerId, request);
        }
    };
    request();
}

document.addEventListener('click', event => {
    const button = event.target.closest?.('#home-refresh-mixes');
    if (!button || button.disabled) return;
    requestHomeSection('home-mixes', 'get_home_mixes', [6], true);
});

function backfillHomeCovers(currentGen) {
    // Artwork may involve dozens of network lookups. Keep it outside the feed
    // critical path and do not repeat a failed scan on every track change.
    if (!window.pywebview?.api?.fetch_missing_covers || coverBackfillPromise ||
        Date.now() - lastCoverBackfillAt < 5 * 60 * 1000) return;
    lastCoverBackfillAt = Date.now();
    coverBackfillPromise = Promise.resolve().then(() => window.pywebview.api.fetch_missing_covers(40))
        .then(async res => {
            if (!res?.updated || currentGen !== homeLoadGeneration) return;
            const fresh = await window.pywebview.api.get_home_data() || {};
            if (currentGen !== homeLoadGeneration) return;
            renderHistory(fresh.history || []);
            if (fresh.analytics) {
                renderTopTracks(fresh.analytics.top_tracks || []);
                renderTopArtists(fresh.analytics.top_artists || []);
            }
        }).catch(err => console.warn('Cover backfill failed:', err))
        .finally(() => { coverBackfillPromise = null; });
}

export async function loadHome(isTrackChange = false) {
    await window.awaitBridge();
    if (!window.pywebview?.api) return;
    mountPersonalWave();
    mountRecommendationControls(document.getElementById('home-recommendation-controls'));

    const currentGen = ++homeLoadGeneration;

    try {
        // Step 1: Core home stats & history
        const data = await window.pywebview.api.get_home_data() || {};
        if (currentGen !== homeLoadGeneration) return;

        document.getElementById('home-error')?.classList.add('hidden');
        updateHomeCollections(data);
        // Four collections, backed by real local data.
        renderQuickAccess(data, data.playlists || []);

        // History
        renderHistory(data.history || []);

        // Analytics (Local Last.fm)
        data.analytics ||= {};
        if (data.analytics) {
            renderTopTracks(data.analytics.top_tracks || []);
            renderTopArtists(data.analytics.top_artists || []);
        }

        // Backfill artwork for rows stored before covers were persisted on
        // playback. Without this those tiles stay empty placeholders forever,
        // because the grid can only render what the row already holds.
        backfillHomeCovers(currentGen);

        // Step 2: Playlists (fast local query)
        if (window.pywebview.api.get_playlists) {
            try {
                const playlists = await window.pywebview.api.get_playlists();
                if (currentGen !== homeLoadGeneration) return;
                if (Array.isArray(playlists)) {
                    data.playlists = playlists;
                    renderHomePlaylists(playlists);
                    renderQuickAccess(data, playlists);
                }
            } catch (err) {
                console.warn('Failed to load playlists on home:', err);
            }
        }

        if (window.pywebview.api.get_downloaded_tracks) {
            try {
                const localTracks = await window.pywebview.api.get_downloaded_tracks();
                if (currentGen !== homeLoadGeneration) return;
                data.localTracks = Array.isArray(localTracks) ? localTracks : [];
                renderQuickAccess(data, data.playlists || []);
            } catch (error) { console.warn('Home local collection unavailable:', error); }
        }

        if(!isTrackChange)requestHomeSection('home-mixes','get_home_mixes',[6]);
        refreshFavoritesCovers();
        initHomeAtmosphere();
    } catch (e) {
        console.error('Error loading home:', e);
        document.getElementById('home-error')?.classList.remove('hidden');
        document.getElementById('home-quick-access')?.setAttribute('aria-busy','false');
    }
}
// ─── Quick Access Grid (2x3 Modern Matrix) ───────────────────────────────────
function formatTracksCount(n) {
    const count = Number(n) || 0;
    const mod10 = count % 10;
    const mod100 = count % 100;
    if (mod100 >= 11 && mod100 <= 19) return `${count} треков`;
    if (mod10 === 1) return `${count} трек`;
    if (mod10 >= 2 && mod10 <= 4) return `${count} трека`;
    return `${count} треков`;
}

export function renderQuickAccess(data = {}, playlists = []) {
    const container = document.getElementById('home-quick-access');
    if (!container) return;
    const play = async tracks => {
        if (!tracks.length) return;
        try { await window.pywebview.api.play_track({...tracks[0], id:tracks[0].track_id || tracks[0].id}, tracks, 0); }
        catch { window.dispatchEvent(new CustomEvent('nedotify:toast', {detail:{msg:'Не удалось включить трек. Повторите попытку.',type:'error'}})); }
    };
    const favorites = {id:'favorites', type:'favorites', title:'Любимые треки', subtitle:formatTracksCount(data.favorites_count), icon:'heart', open:()=>openHomeLibrary('favorites'), play:async()=>{try {const tracks=await window.pywebview.api.get_favorites(); if (tracks?.length) play(tracks); else openHomeLibrary('favorites');} catch {openHomeLibrary('favorites');}}};
    const local = {id:'local', type:'local', title:'Локальные', subtitle:data.localTracks ? formatTracksCount(data.localTracks.length) : 'На этом компьютере', icon:'list-music', open:()=>openHomeLibrary('offline'), play:async()=>{try {const tracks=await window.pywebview.api.get_downloaded_tracks(); if (tracks?.length) play(tracks); else openHomeLibrary('offline');} catch {openHomeLibrary('offline');}}};
    const availablePlaylists = playlists.length ? playlists : data.playlists || [];
    const selected = availablePlaylists.find(p => Number(p.track_count) > 0) || availablePlaylists[0];
    const pl = selected ? {...selected, id:selected.id ?? selected.ID} : null;
    const playlist = pl ? {id:`playlist-${pl.id}`,type:'playlist',playlist:pl,title:pl.name || 'Плейлист',subtitle:formatTracksCount(pl.track_count),icon:'list-music',open:()=>openHomeLibrary('playlist',pl),play:async()=>{try {const result=await window.pywebview.api.get_playlist_tracks(pl.id); const tracks=Array.isArray(result)?result:result?.tracks || []; if(tracks.length) await play(tracks); else openHomeLibrary('playlist',pl);}catch {openHomeLibrary('playlist',pl);}}} : {id:'create-playlist',type:'local',title:'Ваш первый плейлист',subtitle:'Соберите любимую музыку',icon:'plus',open:()=>window.NeDotify?.createPlaylist(),play:()=>window.NeDotify?.createPlaylist()};
    const track = data.history?.[0];
    const recent = track ? {id:'recent',type:'track',track,title:track.title,subtitle:track.artist || 'Недавно прослушано',open:()=>play(data.history),play:()=>play(data.history)} : {id:'library',type:'local',title:'Ваша библиотека',subtitle:'Выберите музыку',icon:'library',open:()=>openHomeLibrary('all'),play:()=>openHomeLibrary('all')};
    container.replaceChildren();
    container.setAttribute('aria-busy','false');
    [favorites,local,playlist,recent].forEach(item => {
        const card=document.createElement('div'); card.className=`quick-access-card qa-${item.type}`; card.dataset.qaId=item.id;
        const cover=item.track ? coverImgHtml({src:getCoverUrl(item.track),coverUrl:item.track.cover_url || '',sourceId:item.track.source_id || '',source:item.track.source || '',alt:''}) : `<i data-lucide="${item.icon || 'list-music'}"></i>`;
        card.innerHTML=`<button class="qa-open" aria-label="Открыть: ${escapeHtml(item.title)}"><span class="qa-cover">${cover}</span><span class="qa-info"><span class="qa-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</span><span class="qa-sub">${escapeHtml(item.subtitle)}</span></span></button><button class="qa-play-btn" aria-label="${item.id==='create-playlist'?'Создать плейлист':'Воспроизвести: '+escapeHtml(item.title)}"><i data-lucide="${item.id==='create-playlist'?'plus':'play'}"></i></button>`;
        card.querySelector('.qa-open').onclick=item.open;
        card.querySelector('.qa-play-btn').onclick=async e=>{const button=e.currentTarget;button.disabled=true;try{await item.play();}finally{if(button.isConnected)button.disabled=false;}};
        if(item.playlist){card.dataset.plId=item.playlist.id;attachPlaylistCollage(item.playlist,card.querySelector('.qa-cover'));}
        container.appendChild(card);
    });
    enhanceHomeCards(container);
    renderIcons(container);
    refreshFavoritesCovers();
}

function renderHistory(tracks) {
    updateHomeCoverCollage(tracks);
    const container = document.getElementById('home-history');
    if (!container) return;
    container.innerHTML = '';
    if (!tracks.length) { container.innerHTML = '<div class="home-empty"><i data-lucide="headphones"></i><h3>Слушайте то, что нравится</h3><p>Ваши недавние треки появятся здесь после первого прослушивания.</p></div>'; renderIcons(container); return; }
    const fragment = document.createDocumentFragment();
    tracks.slice(0, 10).forEach((track, idx) => {
        fragment.appendChild(createFeedCard(track, tracks, idx));
    });
    container.appendChild(fragment);
    enhanceHomeCards(container);
    renderIcons(container);
}

export function renderPopular(tracks) {
    clearFeedTimeout('home-popular');
    renderFeedSection('home-popular', tracks);
}

export function renderRecommendations(tracks) {
    clearFeedTimeout('home-recommended');
    const sec = document.getElementById('home-recommended-section');
    if (sec) sec.style.display = (tracks && tracks.length > 0) ? 'block' : 'none';
    renderFeedSection('home-recommended', tracks);
}

export function renderReleases(tracks) {
    clearFeedTimeout('home-releases');
    renderFeedSection('home-releases', tracks);
}

export function renderMixes(tracks) {
    clearFeedTimeout('home-mixes');
    renderFeedSection('home-mixes', tracks);
}

export function renderAuthenticHome(sections) {
    const container = document.getElementById('home-authentic-feed');
    if (!container) return;
    
    container.innerHTML = '';
    
    const sectionList = Array.isArray(sections) 
        ? sections 
        : (sections && Array.isArray(sections.sections) ? sections.sections : []);
        
    if (!sectionList || sectionList.length === 0) return;
    
    sectionList.forEach((section, index) => {
        if (!section) return;
        const sectionId = `auth-section-${index}`;
        
        // Create section wrapper
        const sectionEl = document.createElement('div');
        sectionEl.className = 'feed-section';
        
        // Title
        const titleEl = document.createElement('div');
        titleEl.className = 'feed-title';
        titleEl.textContent = section.title || 'Рекомендуем';
        sectionEl.appendChild(titleEl);
        
        // Scroll container
        const scrollEl = document.createElement('div');
        scrollEl.className = 'feed-scroll';
        scrollEl.id = sectionId;
        
        const items = Array.isArray(section.items) ? section.items : [];
        const trackItems = items.filter(item => item?.type === 'track');
        const allTracks = trackItems.map(item => ({
            title: item.title, artist: item.artist, cover_url: item.cover_url,
            source: item.source, source_id: item.source_id, source_url: item.source_url,
            duration: item.duration || 0
        }));
        let nextTrackIndex = 0;
        // Fragment: this section's cards land in one insertion (search.js pattern).
        const cardsFragment = document.createDocumentFragment();
        items.forEach(item => {
            if (!item) return;
            if (item.type === 'track') {
                const trackData = {
                    ...item,
                    title: item.title,
                    artist: item.artist,
                    cover_url: item.cover_url,
                    source: item.source,
                    source_id: item.source_id,
                    source_url: item.source_url,
                    duration: item.duration || 0
                };
                const trackIndex = nextTrackIndex++;
                cardsFragment.appendChild(createFeedCard(trackData, allTracks, trackIndex, {source: item.source || 'youtube'}));
            } else if (item.type === 'playlist' || item.type === 'album') {
                const card = createFeedTile({
                    title: item.title,
                    subtitle: item.artist || (item.type === 'album' ? 'Альбом' : 'Микс'),
                    coverUrl: item.cover_url,
                    onActivate: async () => {
                    if (window.pywebview && window.pywebview.api && window.pywebview.api.get_playlist_tracks) {
                        window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: `Загрузка: ${item.title}...`, type: 'info' } }));
                        try {
                            const res = await window.pywebview.api.get_playlist_tracks(item.id, item.source || 'youtube', 50);
                            if (res && res.success && res.tracks && res.tracks.length > 0) {
                                if (window.pywebview.api.play_track) {
                                    window.pywebview.api.play_track(res.tracks[0], res.tracks, 0);
                                }
                            } else {
                                const errMsg = (res && res.error) || 'Не удалось загрузить треки';
                                window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: errMsg, type: 'error' } }));
                            }
                        } catch (err) {
                            window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: String(err), type: 'error' } }));
                        }
                    }
                    },
                });
                cardsFragment.appendChild(card);
            } else if (item.type === 'custom_playlist') {
                const card = document.createElement('div');
                card.className = 'feed-card';
                card.innerHTML = `
                    <div class="feed-card-cover">
                        <div class="feed-card-overlay">
                            <button class="feed-card-play" title="Слушать" aria-label="Слушать"><i data-lucide="play" style="width:14px;height:14px"></i></button>
                        </div>
                    </div>
                    <div class="feed-card-title">${escapeHtml(item.title)}</div>
                    <div class="feed-card-sub">${escapeHtml(item.artist || 'Специально для вас')}</div>
                `;
                applyCoverBackground(card.querySelector('.feed-card-cover'), item.cover_url);
                card.onclick = () => {
                    if (window.pywebview && window.pywebview.api && window.pywebview.api.play_track) {
                        window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: `Включаю: ${item.title}...`, type: 'info' } }));
                        if (item.tracks && item.tracks.length > 0) {
                            window.pywebview.api.play_track(item.tracks[0], item.tracks);
                        }
                    }
                };
                cardsFragment.appendChild(card);
            }
        });

        scrollEl.appendChild(cardsFragment);
        sectionEl.appendChild(scrollEl);
        container.appendChild(sectionEl);
        renderIcons(sectionEl);
    });
}

export const renderAuthenticHomeFeed = renderAuthenticHome;

// ─── Playlist collage covers ───────────────────────────────────────────────
// Session cache: playlistId -> cover urls (first 4 tracks). Invalidated on
// 'nedotify:playlists_changed' (see listener below).
const _plCollageCache = new Map();

export function clearPlaylistCollageCache() {
    _plCollageCache.clear();
}

document.addEventListener('nedotify:playlists_changed', () => _plCollageCache.clear());

// Cold-start safety: the very first renderHomePlaylists can race backend
// warm-up (PROXY_PORT / bridge), leaving skeletons without collages. Once
// init() fully finished, re-render the playlists section deterministically.
window.addEventListener('nedotify:app_ready', async () => {
    try {
        await window.awaitBridge();
        if (!document.getElementById('home-playlists')) return;
        const playlists = await window.pywebview.api.get_playlists();
        if (playlists && playlists.length > 0) renderHomePlaylists(playlists);
    } catch (e) { /* non-fatal: skeletons remain */ }
});

export async function attachPlaylistCollage(pl, coverEl) {
    if (!coverEl || !window.pywebview?.api?.get_playlist_tracks) return;
    const savedCover=getPlaylistCover(pl.id ?? pl.ID);
    if(savedCover){
        coverEl.querySelectorAll('img,.pl-collage,.pl-cover-skeleton,svg.lucide-list-music').forEach(element=>element.remove());
        coverEl.insertAdjacentHTML('afterbegin',coverImgHtml({src:savedCover,alt:''}));
        return;
    }
    // Bridge first: PROXY_PORT must be known before cover URLs are mapped,
    // otherwise local covers resolve to unusable URLs on cold start.
    await window.awaitBridge();
    const pid = pl.id !== undefined ? pl.id : pl.ID;
    let covers = _plCollageCache.get(pid);
    if (!covers) {
        covers = [];
        try {
            const res = await window.pywebview.api.get_playlist_tracks(pid);
            const tracks = Array.isArray(res) ? res : (res && Array.isArray(res.tracks) ? res.tracks : []);
            covers = tracks
                .map(t => ({ src: getCoverUrl(t), coverUrl: t.cover_url || '', sourceId: t.source_id || '', source: t.source || '' }))
                .filter(c => c.src || c.coverUrl)
                .slice(0, 4);
        } catch (e) {
            covers = [];
        }
        // Cache successes only: a cold-start failure (bridge not ready yet)
        // must not pin an empty result for the whole session - the next
        // render retries and self-heals.
        if (covers.length > 0) _plCollageCache.set(pid, covers);
    }
    // One retry for transient cold-start failures: the first render can run
    // before the backend is fully warmed and return no tracks.
    if (covers.length === 0 && (pl.track_count || 0) > 0 && !coverEl.dataset.collageRetried) {
        coverEl.dataset.collageRetried = '1';
        setTimeout(() => { attachPlaylistCollage(pl, coverEl); }, 3000);
        return;
    }
    const html = renderPlaylistCoverCollage(covers);
    if (!html) return;
    // The home feed can be re-rendered while this lookup was in flight, so
    // the captured coverEl may already be detached. Re-resolve the CURRENT
    // card by its playlist id - otherwise the collage is lost to a re-render.
    if (!coverEl.isConnected) {
        const fresh = document.querySelector(
            `#home-playlists .feed-card[data-pl-id="${CSS.escape(String(pid))}"] .feed-card-cover, #home-quick-access .quick-access-card[data-pl-id="${CSS.escape(String(pid))}"] .qa-cover`);
        if (!fresh) return;
        coverEl = fresh;
    }
    if (coverEl.querySelector('.pl-collage')) return; // already attached
    // lucide replaces <i> with an svg and drops the original class, so match
    // both the marker class and the rendered icon.
    const skeleton = coverEl.querySelector('.pl-cover-skeleton, svg.lucide-list-music');
    if (skeleton) skeleton.remove();
    coverEl.insertAdjacentHTML('afterbegin', html);
}

export function renderHomePlaylists(playlists) {
    const container = document.getElementById('home-playlists');
    if (!container) return;
    container.innerHTML = '';

    // Fragment: all playlist cards land in one insertion (search.js pattern).
    // attachPlaylistCollage() can only resume in a microtask, i.e. after this
    // synchronous loop appended the fragment, so its isConnected re-resolve
    // still finds the live card.
    const playlistsFragment = document.createDocumentFragment();

    if (!playlists?.length) {
        container.innerHTML='<div class="home-empty"><i data-lucide="list-music"></i><h3>Место для вашей коллекции</h3><p>Соберите плейлист для любимого настроения.</p><button class="home-pill">Создать плейлист</button></div>';
        container.querySelector('button').onclick=()=>window.NeDotify?.createPlaylist(); renderIcons(container); return;
    }
    playlists.forEach(pl => {
        const card = createFeedTile({
            title: pl.name,
            subtitle: `${pl.track_count || 0} треков`,
            coverMarkup: '<i data-lucide="list-music" class="pl-cover-skeleton" style="width:32px;height:32px;color:var(--text-sec)"></i>',
            coverStyle: 'display:flex;align-items:center;justify-content:center',
            onActivate: async () => {
                if (!window.pywebview?.api?.get_playlist_tracks) return;
                try {
                    const res = await window.pywebview.api.get_playlist_tracks(pl.id);
                    const tracks = Array.isArray(res) ? res : (res && Array.isArray(res.tracks) ? res.tracks : []);
                    if (tracks.length) window.pywebview.api.play_track(tracks[0], tracks);
                } catch (err) {
                    window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Не удалось открыть плейлист', type: 'error' } }));
                }
            },
        });
        card.setAttribute('data-pl-id', String(pl.id !== undefined ? pl.id : pl.ID));
        // Collage of the first 4 track covers (skeleton stays until resolved;
        // with 0 covers the skeleton remains as-is).
        attachPlaylistCollage(pl, card.querySelector('.feed-card-cover'));
        playlistsFragment.appendChild(card);
    });
    container.appendChild(playlistsFragment);
    enhanceHomeCards(container);
    renderIcons(container);
}

// ─── Real artist avatars (photo upgrade over the letter discs) ─────────────
// The DB stores artist names only, so cards first paint the deterministic
// letter disc; this block then swaps in the real channel photo resolved by
// the backend (one YT Music search per unknown artist, cached a week in
// localStorage so subsequent launches paint photos instantly).
const AVATAR_LS_KEY = 'nedotify_artist_avatars_v2';
const AVATAR_TTL_MS = 7 * 24 * 3600 * 1000;
const _avatarInflight = new Set();

function loadAvatarStore() {
    try { return JSON.parse(localStorage.getItem(AVATAR_LS_KEY) || '{}'); } catch (e) { return {}; }
}
function saveAvatarStore(store) {
    try { localStorage.setItem(AVATAR_LS_KEY, JSON.stringify(store)); } catch (e) {}
}

function applyArtistAvatar(name, url) {
    if (!name || !url) return;
    document.querySelectorAll('.artist-card').forEach(card => {
        const titleEl = card.querySelector('.feed-card-title');
        if (!titleEl || titleEl.textContent.trim() !== name) return;
        const coverEl = card.querySelector('.feed-card-cover');
        if (!coverEl) return;
        const previous = coverEl.querySelector('img');
        const resolved = getCoverUrl({cover_url:url});
        if (previous?.getAttribute('src') === resolved) return;
        const img = document.createElement('img');
        img.alt = name;
        img.loading = 'lazy';
        img.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;object-fit:cover;';
        // On failure the letter disc stays: just remove the broken img.
        img.addEventListener('error', () => {
            img.remove();
            const store = loadAvatarStore(); delete store[name]; saveAvatarStore(store);
        });
        img.addEventListener('load', () => {
            previous?.remove();
            coverEl.querySelector('.artist-avatar-fallback')?.remove();
        }, {once:true});
        img.src = resolved;
        coverEl.appendChild(img);
    });
}

function requestArtistAvatars(names) {
    const unique = [...new Set((names || []).map(n => (n || '').trim()).filter(Boolean))];
    if (unique.length === 0) return;
    const store = loadAvatarStore();
    const now = Date.now();
    const missing = [];
    unique.forEach(name => {
        const entry = store[name];
        if (entry && entry.url && now - (entry.ts || 0) < AVATAR_TTL_MS) {
            applyArtistAvatar(name, entry.url);
        } else if (!_avatarInflight.has(name)) {
            missing.push(name);
        }
    });
    if (missing.length === 0) return;
    missing.forEach(n => _avatarInflight.add(n));
    const bridgeWait = window.awaitBridge ? window.awaitBridge() : Promise.resolve();
    bridgeWait.then(() => {
        if (window.pywebview?.api?.get_artists_avatars) {
            Promise.resolve(window.pywebview.api.get_artists_avatars(missing)).catch(()=>missing.forEach(n=>_avatarInflight.delete(n)));
        }
        // Allow a retry on the next render if the backend never answered.
        setTimeout(() => missing.forEach(n => _avatarInflight.delete(n)), 15000);
    });
}

window.addEventListener('app:artists_avatars_ready', (e) => {
    const avatars = (e.detail && e.detail.avatars) || {};
    const store = loadAvatarStore();
    const now = Date.now();
    Object.entries(avatars).forEach(([name, url]) => {
        _avatarInflight.delete(name);
        if (!url) return;
        store[name] = { url, ts: now };
        applyArtistAvatar(name, url);
    });
    saveAvatarStore(store);
});

export function renderArtists(artists) {
    const container = document.getElementById('home-artists');
    if (!container) return;
    const sec = container.closest('.feed-section');
    if (sec) {
        sec.classList.remove('hidden');
        sec.style.display = '';
    }
    container.innerHTML = '';

    if (!artists || artists.length === 0) {
        container.innerHTML = '<div class="empty-state text-sm" style="padding:20px">Нет данных</div>';
        return;
    }

    // Fragment: artist cards land in one insertion (search.js pattern).
    const artistsFragment = document.createDocumentFragment();

    artists.forEach(artist => {
        const cover = getCoverUrl(artist);
        const artistName = artist.artist || artist.name || 'Unknown';
        const coverMarkup = cover
            ? coverImgHtml({ src: cover, coverUrl: artist.cover_url || '', alt: artistName })
            : artistAvatarHtml(artistName);
        const card = createFeedTile({
            title: artistName, subtitle: null, coverMarkup, className: 'feed-card artist-card',
            titleStyle: 'text-align:center', showPlayButton: false,
            onActivate: () => openArtistProfile(artistName),
        });
        card.style.minWidth = '120px';
        card.style.maxWidth = '120px';
        artistsFragment.appendChild(card);
    });
    container.appendChild(artistsFragment);
    enhanceHomeCards(container);
    renderIcons(container);
    requestArtistAvatars(artists.map(a => a.artist || a.name));
}

function renderFeedSection(containerId, tracks) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';

    if (!tracks || tracks.length === 0) {
        const message = containerId === 'home-mixes'
            ? 'Новых рекомендаций пока нет. Послушайте музыку или обновите подборки позже.'
            : 'Нет данных';
        container.innerHTML = `<div class="empty-state text-sm" style="padding:20px">${message}</div>`;
        return;
    }

    // Fragment: the section's cards land in one insertion (search.js pattern).
    const feedFragment = document.createDocumentFragment();
    tracks.forEach((track, idx) => {
        feedFragment.appendChild(createFeedCard(track, tracks, idx));
    });
    container.appendChild(feedFragment);
    enhanceHomeCards(container);
    renderIcons(container);
}

function openArtistProfile(artistName, track = null) {
    if (!artistName || artistName === 'Unknown' || artistName === 'Микс') return;
    if (window.searchArtistProfile) { window.searchArtistProfile(artistName, track); return; }
    if (window.NeDotify?.searchArtistProfile) { window.NeDotify.searchArtistProfile(artistName, track); return; }
    const input = document.getElementById('search-input');
    if (!input) return;
    input.value = artistName;
    if (window.showPage) window.showPage('search');
    input.dispatchEvent(new Event('input', {bubbles: true}));
}

function createFeedTile({title, subtitle = '', coverMarkup = '', coverUrl = '', className = 'feed-card',
    coverStyle = '', subtitleClass = '', titleStyle = '', subtitleStyle = '', showPlayButton = true,
    onActivate = null, artistName = '', track = null}) {
    const card = document.createElement('div');
    card.className = className;
    card.innerHTML = `
        <div class="feed-card-cover" style="${coverStyle}">${coverMarkup}${showPlayButton ? `<div class="feed-card-overlay"><button class="feed-card-play" type="button" aria-label="Воспроизвести: ${escapeHtml(title || 'Музыка')}"><i data-lucide="play" style="width:14px;height:14px;fill:currentColor"></i></button></div>` : ''}</div>
        <div class="feed-card-title" style="${titleStyle}">${escapeHtml(title || 'Unknown')}</div>
        ${subtitle !== null ? `<div class="feed-card-sub ${subtitleClass}" style="${subtitleStyle}">${escapeHtml(subtitle)}</div>` : ''}
    `;
    if (coverUrl) applyCoverBackground(card.querySelector('.feed-card-cover'), coverUrl);
    const sub = card.querySelector('.feed-card-sub');
    if (artistName && sub) {
        sub.classList.add('clickable-artist');
        sub.addEventListener('click', event => { event.stopPropagation(); openArtistProfile(artistName, track); });
    }
    if (onActivate) card.addEventListener('click', onActivate);
    return card;
}

function createFeedCard(track, trackList = null, trackIndex = 0, options = {}) {
    let card = document.createElement('div');
    card.className = 'feed-card';

    if (track.type === 'custom_playlist') {
        const covers=(track.tracks||[]).slice(0,4).map(t=>({src:getCoverUrl(t),coverUrl:t.cover_url,sourceId:t.source_id,source:t.source}));
        card.innerHTML=`<div class="feed-card-cover">${renderPlaylistCoverCollage(covers)}<div class="feed-card-overlay"><button class="feed-card-play" aria-label="Слушать микс"><i data-lucide="play"></i></button></div></div><div class="feed-card-title">${escapeHtml(track.title)}</div><div class="feed-card-sub">${escapeHtml(track.artist||'На ваш вкус')}</div>`;
        const play=()=>window.pywebview.api.play_track(track.tracks[0],track.tracks,0);
        card.querySelector('.feed-card-play').onclick=e=>{e.stopPropagation();play().catch(()=>showToast('Не удалось включить микс','error'));};
        card.addEventListener('click',()=>openHomeDialog(track.title,content=>{
            const save=document.createElement('button');save.className='home-pill';save.textContent='Сохранить плейлист';
            save.onclick=async()=>{save.disabled=true;try{const tracks=track.tracks.map(t=>({...t,id:/^\d+$/.test(String(t.id||''))?t.id:undefined}));const id=await window.pywebview.api.create_local_playlist(track.title,tracks);if(!id||id?.success===false)throw Error();save.textContent='Сохранено';showToast('Плейлист сохранён','success');}catch{save.disabled=false;showToast('Не удалось сохранить плейлист','error');}};
            content.append(save);
            (track.tracks||[]).forEach((t,index)=>content.append(createTrackElement(t,index,track.tracks,null)));
        }));
        return card;
    }

    const cover = getCoverUrl(track);
    const subtitle = options.subtitle ?? track.artist ?? '';
    const artistLink = options.artistLink !== false && track.artist && track.artist !== 'Unknown' && track.artist !== 'Микс';
    card = createFeedTile({
        title: track.title || 'Unknown', subtitle,
        coverMarkup: coverImgHtml({ src: cover, coverUrl: track.cover_url || '', sourceId: track.source_id || '', source: options.source || track.source || '' }),
        artistName: artistLink ? track.artist : '',
        track: track,
    });
    if (track.recommendation_reason) {
        const reason = document.createElement('span');
        reason.className = 'recommendation-reason';
        reason.textContent = track.recommendation_reason;
        reason.title = track.recommendation_reason;
        card.append(reason);
    }
    card.addEventListener('click', (e) => {
        if (e.target.closest('.feed-card-sub')) return;
        if (window.pywebview?.api) {
            const trackObj = { ...track };
            if (trackObj.track_id) trackObj.id = trackObj.track_id;
            if (trackList && trackList.length > 0) {
                window.pywebview.api.play_track(trackObj, trackList, trackIndex);
            } else {
                window.pywebview.api.play_track(trackObj);
            }
        }
    });
    return card;
}

function setElText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

// BUG-U3-003: слушатель 'app:mood_playlists_ready' удалён — событие не
// эмитится бэкендом, фича «Под настроение» снята (секция section-home-mood
// удалена из index.html, case удалён из events.js).


window.addEventListener('app:refresh_home', () => {
    loadHome(false);
});

export function renderTopTracks(tracks) {
    const container = document.getElementById('home-top-tracks');
    if (!container) return;
    container.innerHTML = '';
    
    if (!tracks || tracks.length === 0) {
        container.innerHTML = '<div class="empty-state text-sm" style="padding:18px 24px; color:rgba(255,255,255,0.85); font-weight:600; background:rgba(255,255,255,0.04); border-radius:12px; border:1px dashed rgba(255,255,255,0.15); width:100%;">🎵 Слушайте любимую музыку, чтобы сформировать личный Топ!</div>';
        return;
    }

    // Fragment: top-track cards land in one insertion (search.js pattern).
    const topTracksFragment = document.createDocumentFragment();
    tracks.forEach((track, i) => {
        const playCount = track.play_count || track.plays || track.total_plays || 0;
        const displayTrack = {...track, title: track.title || 'Unknown Title'};
        topTracksFragment.appendChild(createFeedCard(displayTrack, tracks, i, {
            subtitle: `${track.artist || 'Unknown'} (${playCount})`
        }));
    });
    container.appendChild(topTracksFragment);
    enhanceHomeCards(container);
    renderIcons(container);
}

export function renderTopArtists(artists) {
    const container = document.getElementById('home-top-artists');
    if (!container) return;
    container.innerHTML = '';
    
    if (!artists || artists.length === 0) {
        container.innerHTML = '<div class="empty-state text-sm" style="padding:16px;color:var(--text-sec)">Пока нет данных</div>';
        return;
    }

    // Fragment: top-artist cards land in one insertion (search.js pattern).
    const topArtistsFragment = document.createDocumentFragment();
    artists.forEach(artist => {
        const artistName = artist.artist || artist.name || 'Unknown';
        const playsCount = artist.total_plays || artist.play_count || artist.plays || 0;
        const card = createFeedTile({
            title: artistName, subtitle: `${playsCount} раз`, coverMarkup: artistAvatarHtml(artistName),
            className: 'feed-card artist-card', titleStyle: 'text-align:center', subtitleStyle: 'text-align:center',
            artistName, onActivate: () => openArtistProfile(artistName),
        });
        topArtistsFragment.appendChild(card);
    });
    container.appendChild(topArtistsFragment);
    enhanceHomeCards(container);
    renderIcons(container);
    requestArtistAvatars(artists.map(a => a.artist || a.name));
}

let currentWrappedPeriod = 'week';
let wrappedLoadGeneration = 0;

export async function loadWrappedStats(period = 'week') {
    currentWrappedPeriod = period;
    const gen = ++wrappedLoadGeneration;
    await window.awaitBridge();
    if (!window.pywebview?.api || !window.pywebview.api.get_wrapped_stats) return;

    try {
        const stats = await window.pywebview.api.get_wrapped_stats(period);
        if (gen !== wrappedLoadGeneration) return;
        renderWrappedUI(stats);
    } catch (e) {
        console.error("Error loading wrapped stats:", e);
    }
}

function renderWrappedUI(stats) {
    if (!stats) return;
    const badge = document.getElementById('wrapped-total-time-badge');
    if (badge) badge.textContent = `${stats.total_minutes || 0} мин (${stats.total_plays || 0} треков)`;

    // Render Canvas Activity Chart
    renderActivityChart(stats.daily_activity || []);

    // Render Top 5
    const list = document.getElementById('wrapped-top-list');
    if (!list) return;

    if (!stats.top_tracks || stats.top_tracks.length === 0) {
        list.innerHTML = '<div class="empty-state text-sm" style="padding:12px; opacity:0.6;">Нет слушательских данных за этот период</div>';
        return;
    }

    list.innerHTML = '';
    const topListFragment = document.createDocumentFragment();
    stats.top_tracks.forEach((track, i) => {
        const row = document.createElement('div');
        row.style.cssText = 'display:flex; justify-content:space-between; align-items:center; padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.05);';
        row.innerHTML = `
            <div style="display:flex; align-items:center; gap:8px; overflow:hidden;">
                <span style="font-weight:700; color:var(--primary); width:14px; text-align:center;">${i+1}</span>
                <div style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                    <span style="color:#fff; font-weight:600;">${escapeHtml(track.title || 'Unknown')}</span>
                    <span style="color:var(--text-sec); font-size:11px; margin-left:4px;">• ${escapeHtml(track.artist || 'Unknown')}</span>
                </div>
            </div>
            <span style="color:var(--primary); font-size:11px; font-weight:600; white-space:nowrap;">${track.plays} прослушиваний</span>
        `;
        topListFragment.appendChild(row);
    });
    list.appendChild(topListFragment);
}

// Retained so a devicePixelRatio change can re-rasterise the chart without
// another bridge round-trip for the same period's data.
let lastActivityData = null;

function renderActivityChart(activity) {
    const canvas = document.getElementById('wrapped-activity-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    // CSS-pixel geometry; the backing store is scaled by devicePixelRatio and
    // the context carries the matching scale, so all the maths below - and
    // therefore the rendered chart - is unchanged. At dpr === 1 the backing
    // store is exactly w x h, identical to before.
    // CSS owns the responsive box; only the backing store is resized here.
    // A fixed inline width would retain the previous window's dimensions.
    const sized = sizeCanvasForDpr(
        canvas, ctx,
        canvas.parentElement.clientWidth || 300,
        140
    );
    const w = sized.cssW;
    const h = sized.cssH;
    lastActivityData = activity;

    ctx.clearRect(0, 0, w, h);

    if (!activity || activity.length === 0) return;

    const maxVal = Math.max(...activity.map(a => a.minutes), 10);
    const barWidth = Math.max(12, Math.floor((w - 40) / activity.length));
    const spacing = 6;

    activity.forEach((item, i) => {
        const barH = Math.max(4, Math.floor((item.minutes / maxVal) * (h - 35)));
        const x = 20 + i * (barWidth + spacing);
        const y = h - 25 - barH;

        // Gradient bar
        const grad = ctx.createLinearGradient(0, y, 0, h - 25);
        grad.addColorStop(0, '#1DB954');
        grad.addColorStop(1, 'rgba(29, 185, 84, 0.15)');

        ctx.fillStyle = grad;
        ctx.beginPath();
        if (ctx.roundRect) {
            ctx.roundRect(x, y, barWidth, barH, 4);
        } else {
            ctx.rect(x, y, barWidth, barH);
        }
        ctx.fill();

        // Day Label
        ctx.fillStyle = 'rgba(255,255,255,0.6)';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(item.day, x + barWidth / 2, h - 8);
    });
}

// A window drag between monitors changes devicePixelRatio without a resize
// event; re-rasterise the activity chart at the new scale.
registerCanvasDprListener(() => {
    if (lastActivityData) renderActivityChart(lastActivityData);
});
let activityResizeFrame=0;
const redrawActivity=()=>{
    cancelAnimationFrame(activityResizeFrame);
    activityResizeFrame=requestAnimationFrame(()=>{if(lastActivityData)renderActivityChart(lastActivityData);});
};
window.addEventListener('resize',redrawActivity);
window.addEventListener('nedotify:page_changed',event=>{if(event.detail==='home')redrawActivity();});

// Bind period buttons
document.addEventListener('DOMContentLoaded', () => {
    const periodContainer = document.getElementById('wrapped-period-btns');
    if (periodContainer) {
        periodContainer.querySelectorAll('.wrapped-period-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                periodContainer.querySelectorAll('.wrapped-period-btn').forEach(b => {
                    b.classList.remove('active');
                    b.style.background = 'transparent';
                    b.style.color = 'var(--text-sec)';
                });
                btn.classList.add('active');
                btn.style.background = 'var(--primary)';
                btn.style.color = '#fff';
                const period = btn.dataset.period || 'week';
                loadWrappedStats(period);
            });
        });
    }
});




function enhanceHomeCards(container) {
    container.querySelectorAll('.feed-card').forEach(card => {
        const title=card.querySelector('.feed-card-title')?.textContent || 'Музыка';
        card.querySelectorAll('.feed-card-play').forEach(button=>{button.type='button';button.setAttribute('aria-label',`Воспроизвести: ${title}`);});
        const play=card.querySelector('.feed-card-play');
        if(!play){card.tabIndex=0;card.setAttribute('role','button');card.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();card.click();}};}
        const artist=card.querySelector('.clickable-artist');
        if(artist){artist.tabIndex=0;artist.setAttribute('role','button');artist.setAttribute('aria-label',`Исполнитель: ${artist.textContent}`);artist.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();artist.click();}};}
    });
}
