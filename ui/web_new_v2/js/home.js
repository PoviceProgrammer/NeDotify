import { formatTime, formatListeningTime, renderIcons, getCoverUrl, escapeHtml, coverImgHtml, artistAvatarHtml, renderPlaylistCoverCollage } from './utils.js';

const feedTimeouts = new Map();
let trackChangeCount = 0;
let homeLoadGeneration = 0;

// Helper to stagger bridge calls and prevent backend burst / thread pool congestion
const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

function renderSkeletons(containerId, count = 4) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';
    for (let i = 0; i < count; i++) {
        const card = document.createElement('div');
        card.className = 'skeleton-card';
        card.innerHTML = `
            <div class="skeleton-cover"></div>
            <div class="skeleton-title"></div>
            <div class="skeleton-sub"></div>
        `;
        container.appendChild(card);
    }
}

export function clearFeedTimeout(sectionId) {
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

export async function loadHome(isTrackChange = false) {
    await window.awaitBridge();
    if (!window.pywebview?.api) return;

    const currentGen = ++homeLoadGeneration;

    try {
        // Step 1: Core home stats & history
        const data = await window.pywebview.api.get_home_data() || {};
        if (currentGen !== homeLoadGeneration) return;

        // Render Quick Access Grid (2x3 modern Spotify-style grid)
        renderQuickAccess(data, data.playlists || []);

        // History
        if (data.history && data.history.length > 0) {
            renderHistory(data.history);
        }

        // Analytics (Local Last.fm)
        if (data.analytics) {
            renderTopTracks(data.analytics.top_tracks || []);
            renderTopArtists(data.analytics.top_artists || []);
        }

        // Step 2: Playlists (fast local query)
        if (window.pywebview.api.get_playlists) {
            try {
                const playlists = await window.pywebview.api.get_playlists();
                if (currentGen !== homeLoadGeneration) return;
                if (playlists && playlists.length > 0) {
                    renderHomePlaylists(playlists);
                    renderQuickAccess(data, playlists);
                }
            } catch (err) {
                console.warn('Failed to load playlists on home:', err);
            }
        }

        // Decide whether to refresh recommendations/mixes/etc.
        let shouldLoadFeeds = !isTrackChange;
        if (isTrackChange) {
            trackChangeCount++;
            if (trackChangeCount >= 10) {
                trackChangeCount = 0;
                shouldLoadFeeds = true;
            }
        }

        // Step 3: Staggered external feeds to avoid slamming backend bridge
        if (shouldLoadFeeds) {
            renderSkeletons('home-popular');
            renderSkeletons('home-recommended');
            renderSkeletons('home-releases');
            renderSkeletons('home-mixes');

            if (window.pywebview.api.get_popular_tracks) {
                window.pywebview.api.get_popular_tracks();
            }

            await delay(75);
            if (currentGen !== homeLoadGeneration) return;

            if (window.pywebview.api.get_feed) {
                window.pywebview.api.get_feed(10);
            }

            await delay(75);
            if (currentGen !== homeLoadGeneration) return;

            if (window.pywebview.api.get_home_releases) {
                window.pywebview.api.get_home_releases(10);
            }

            await delay(75);
            if (currentGen !== homeLoadGeneration) return;

            if (window.pywebview.api.get_home_mixes) {
                window.pywebview.api.get_home_mixes(10);
            }

            await delay(75);
            if (currentGen !== homeLoadGeneration) return;

            if (window.pywebview.api.get_authentic_home_feed) {
                window.pywebview.api.get_authentic_home_feed(5);
            }
        }

        await delay(100);
        if (currentGen !== homeLoadGeneration) return;

        // Step 4: Artists feed
        if (window.pywebview.api.get_home_artists) {
            renderSkeletons('home-artists');
            window.pywebview.api.get_home_artists(15);
            feedTimeouts.set('home-artists', setTimeout(() => {
                renderRetryButton('home-artists', () => {
                    feedTimeouts.set('home-artists', setTimeout(() => renderRetryButton('home-artists', () => window.pywebview.api.get_home_artists(15)), 15000));
                    window.pywebview.api.get_home_artists(15);
                });
            }, 15000));
        }

        await delay(100);
        if (currentGen !== homeLoadGeneration) return;

        // Step 5: Wrapped Stats
        loadWrappedStats(currentWrappedPeriod);
    } catch (e) {
        console.error('Error loading home:', e);
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

    const items = [];
    const favCount = data?.favorites_count || 0;

    // 1. Pinned Favorites Slot
    items.push({
        id: 'favorites',
        type: 'favorites',
        title: 'Любимые треки',
        subtitle: formatTracksCount(favCount),
        action: async () => {
            if (window.pywebview?.api?.get_favorites) {
                try {
                    const favs = await window.pywebview.api.get_favorites();
                    const tracks = Array.isArray(favs) ? favs : (favs?.tracks || []);
                    if (tracks && tracks.length > 0 && window.pywebview.api.play_track) {
                        window.pywebview.api.play_track(tracks[0], tracks, 0);
                    } else if (window.showPage) {
                        window.showPage('library');
                    } else if (window.NeDotify?.showPage) {
                        window.NeDotify.showPage('library');
                    }
                } catch (e) {
                    if (window.showPage) window.showPage('library');
                    else if (window.NeDotify?.showPage) window.NeDotify.showPage('library');
                }
            } else if (window.showPage) {
                window.showPage('library');
            } else if (window.NeDotify?.showPage) {
                window.NeDotify.showPage('library');
            }
        }
    });

    // 2. Playlists (up to 2 recent/user playlists)
    const effectivePlaylists = (playlists && playlists.length > 0)
        ? playlists
        : (data?.playlists && data.playlists.length > 0 ? data.playlists : []);

    effectivePlaylists.slice(0, 2).forEach(pl => {
        if (!pl) return;
        const pid = pl.id !== undefined ? pl.id : pl.ID;
        items.push({
            id: `playlist-${pid}`,
            type: 'playlist',
            playlist: pl,
            title: pl.name || 'Плейлист',
            subtitle: formatTracksCount(pl.track_count || 0),
            action: async () => {
                if (window.pywebview?.api?.get_playlist_tracks) {
                    try {
                        const res = await window.pywebview.api.get_playlist_tracks(pid);
                        const tracks = Array.isArray(res) ? res : (res && Array.isArray(res.tracks) ? res.tracks : []);
                        if (tracks && tracks.length > 0 && window.pywebview.api.play_track) {
                            window.pywebview.api.play_track(tracks[0], tracks, 0);
                        } else if (window.showPage) {
                            window.showPage('library');
                        } else if (window.NeDotify?.showPage) {
                            window.NeDotify.showPage('library');
                        }
                    } catch (e) {
                        console.warn('Quick access playlist error:', e);
                    }
                }
            }
        });
    });

    // 3. History Tracks or Top Tracks to fill remaining slots
    const historyList = (data?.history && data.history.length > 0)
        ? data.history
        : (data?.analytics?.top_tracks || []);

    const seenTrackKeys = new Set();
    historyList.forEach((track, idx) => {
        if (items.length >= 6) return;
        if (!track || !track.title) return;
        const trackKey = `${track.source || 'src'}_${track.source_id || track.id || track.title}`;
        if (!seenTrackKeys.has(trackKey)) {
            seenTrackKeys.add(trackKey);
            items.push({
                id: `track-${trackKey}`,
                type: 'track',
                track: track,
                title: track.title || 'Unknown',
                subtitle: track.artist || 'Трек',
                cover_url: getCoverUrl(track),
                action: () => {
                    if (window.pywebview?.api?.play_track) {
                        const trackObj = { ...track };
                        if (trackObj.track_id) trackObj.id = trackObj.track_id;
                        const trackList = historyList.filter(x => x && (x.title || x.source_id));
                        window.pywebview.api.play_track(trackObj, trackList.length > 0 ? trackList : [trackObj], idx);
                    }
                }
            });
        }
    });

    // 4. Cold-Start / Fallback Fillers if fewer than 6 items exist
    const fallbacks = [
        {
            id: 'fallback-flow',
            type: 'fallback',
            icon: 'radio',
            title: 'Бесконечная волна',
            subtitle: 'Умный радиопоток',
            gradient: 'linear-gradient(135deg, #8b5cf6, #ec4899)',
            action: () => {
                const flowBtn = document.getElementById('pb-btn-flow');
                if (flowBtn) flowBtn.click();
            }
        },
        {
            id: 'fallback-library',
            type: 'fallback',
            icon: 'library',
            title: 'Моя медиатека',
            subtitle: 'Все треки и коллекции',
            gradient: 'linear-gradient(135deg, #3b82f6, #8b5cf6)',
            action: () => {
                if (window.showPage) window.showPage('library');
                else if (window.NeDotify?.showPage) window.NeDotify.showPage('library');
            }
        },
        {
            id: 'fallback-popular',
            type: 'fallback',
            icon: 'flame',
            title: 'Популярное',
            subtitle: 'Тренды и чарты',
            gradient: 'linear-gradient(135deg, #f59e0b, #ef4444)',
            action: () => {
                const popSec = document.getElementById('home-popular');
                if (popSec) popSec.scrollIntoView({ behavior: 'smooth' });
                else if (window.showPage) window.showPage('search');
            }
        },
        {
            id: 'fallback-search',
            type: 'fallback',
            icon: 'compass',
            title: 'Обзор и поиск',
            subtitle: 'Миллионы треков',
            gradient: 'linear-gradient(135deg, #10b981, #06b6d4)',
            action: () => {
                if (window.showPage) window.showPage('search');
                else if (window.NeDotify?.showPage) window.NeDotify.showPage('search');
            }
        },
        {
            id: 'fallback-releases',
            type: 'fallback',
            icon: 'sparkles',
            title: 'Новые релизы',
            subtitle: 'Свежая музыка недели',
            gradient: 'linear-gradient(135deg, #ec4899, #f43f5e)',
            action: () => {
                const relSec = document.getElementById('home-releases');
                if (relSec) relSec.scrollIntoView({ behavior: 'smooth' });
            }
        }
    ];

    let fbIdx = 0;
    while (items.length < 6 && fbIdx < fallbacks.length) {
        items.push(fallbacks[fbIdx++]);
    }

    container.innerHTML = '';

    items.slice(0, 6).forEach(item => {
        const card = document.createElement('div');
        card.className = 'quick-access-card';
        card.setAttribute('data-qa-id', item.id);

        let coverHtml = '';
        if (item.type === 'favorites') {
            coverHtml = `
                <div class="qa-cover" style="background: linear-gradient(135deg, #f43f5e, #ec4899);">
                    <i data-lucide="heart" class="qa-fav-icon" style="width:26px;height:26px;fill:currentColor"></i>
                </div>
            `;
        } else if (item.type === 'playlist') {
            const pid = item.playlist?.id !== undefined ? item.playlist.id : item.playlist?.ID;
            card.setAttribute('data-pl-id', String(pid));
            coverHtml = `
                <div class="qa-cover">
                    <i data-lucide="list-music" class="pl-cover-skeleton" style="width:24px;height:24px;color:var(--color-text-muted, rgba(255,255,255,0.5))"></i>
                </div>
            `;
        } else if (item.type === 'track') {
            coverHtml = `
                <div class="qa-cover">
                    ${coverImgHtml({ src: item.cover_url || '', coverUrl: item.cover_url || '', sourceId: item.track?.source_id || '', source: item.track?.source || 'youtube' })}
                </div>
            `;
        } else if (item.type === 'fallback') {
            coverHtml = `
                <div class="qa-cover" style="background: ${item.gradient};">
                    <i data-lucide="${item.icon}" style="width:24px;height:24px;color:#ffffff"></i>
                </div>
            `;
        }

        card.innerHTML = `
            ${coverHtml}
            <div class="qa-info">
                <div class="qa-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</div>
                <div class="qa-sub" title="${escapeHtml(item.subtitle)}">${escapeHtml(item.subtitle)}</div>
            </div>
            <button class="qa-play-btn" title="Воспроизвести" aria-label="Play">
                <i data-lucide="play" style="width:16px;height:16px;fill:currentColor"></i>
            </button>
        `;

        if (item.type === 'playlist' && item.playlist) {
            attachPlaylistCollage(item.playlist, card.querySelector('.qa-cover'));
        }

        card.addEventListener('click', (e) => {
            if (e.target.closest('.qa-play-btn')) return;
            item.action();
        });

        const playBtn = card.querySelector('.qa-play-btn');
        if (playBtn) {
            playBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                item.action();
            });
        }

        container.appendChild(card);
    });

    renderIcons(container);
}

function renderHistory(tracks) {
    const container = document.getElementById('home-history');
    if (!container) return;
    container.innerHTML = '';
    tracks.slice(0, 10).forEach((track, idx) => {
        container.appendChild(createFeedCard(track, tracks, idx));
    });
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
        items.forEach(item => {
            if (!item) return;
            if (item.type === 'track') {
                const trackData = {
                    title: item.title,
                    artist: item.artist,
                    cover_url: item.cover_url,
                    source: item.source,
                    source_id: item.source_id,
                    source_url: item.source_url,
                    duration: item.duration || 0
                };
                
                const card = document.createElement('div');
                card.className = 'feed-card';
                card.innerHTML = `
                    <div class="feed-card-cover">
                        ${coverImgHtml({ src: item.cover_url || '', coverUrl: item.cover_url || '', sourceId: item.source_id || '', source: 'youtube' })}
                        <div class="feed-card-overlay">
                            <button class="feed-card-play"><i data-lucide="play" style="width:14px;height:14px;fill:currentColor"></i></button>
                        </div>
                    </div>
                    <div class="feed-card-title">${escapeHtml(item.title || 'Unknown')}</div>
                    <div class="feed-card-sub">${escapeHtml(item.artist || '')}</div>
                `;
                
                card.onclick = () => {
                    const allTracks = items
                        .filter(i => i && i.type === 'track')
                        .map(i => ({
                            title: i.title,
                            artist: i.artist,
                            cover_url: i.cover_url,
                            source: i.source,
                            source_id: i.source_id,
                            source_url: i.source_url,
                            duration: i.duration || 0
                        }));
                    if (window.pywebview && window.pywebview.api && window.pywebview.api.play_track) {
                        window.pywebview.api.play_track(trackData, allTracks);
                    }
                };
                scrollEl.appendChild(card);
            } else if (item.type === 'playlist' || item.type === 'album') {
                const card = document.createElement('div');
                card.className = 'feed-card';
                card.innerHTML = `
                    <div class="feed-card-cover" style="background-image: url('${escapeHtml(item.cover_url)}')">
                        <div class="feed-card-overlay">
                            <button class="feed-card-play"><i data-lucide="play" style="width:14px;height:14px"></i></button>
                        </div>
                    </div>
                    <div class="feed-card-title">${escapeHtml(item.title)}</div>
                    <div class="feed-card-sub">${escapeHtml(item.artist || (item.type === 'album' ? 'Альбом' : 'Микс'))}</div>
                `;
                card.onclick = async () => {
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
                };
                scrollEl.appendChild(card);
            } else if (item.type === 'custom_playlist') {
                const card = document.createElement('div');
                card.className = 'feed-card';
                card.innerHTML = `
                    <div class="feed-card-cover" style="background-image: url('${escapeHtml(item.cover_url)}')">
                        <div class="feed-card-overlay">
                            <button class="feed-card-play"><i data-lucide="play" style="width:14px;height:14px"></i></button>
                        </div>
                    </div>
                    <div class="feed-card-title">${escapeHtml(item.title)}</div>
                    <div class="feed-card-sub">${escapeHtml(item.artist || 'Специально для вас')}</div>
                `;
                card.onclick = () => {
                    if (window.pywebview && window.pywebview.api && window.pywebview.api.play_track) {
                        window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: `Включаю: ${item.title}...`, type: 'info' } }));
                        if (item.tracks && item.tracks.length > 0) {
                            window.pywebview.api.play_track(item.tracks[0], item.tracks);
                        }
                    }
                };
                scrollEl.appendChild(card);
            }
        });
        
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
            `#home-playlists .feed-card[data-pl-id="${String(pid)}"] .feed-card-cover, #home-quick-access .quick-access-card[data-pl-id="${String(pid)}"] .qa-cover`);
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

    playlists.forEach(pl => {
        const card = document.createElement('div');
        card.className = 'feed-card';
        card.setAttribute('data-pl-id', String(pl.id !== undefined ? pl.id : pl.ID));
        card.innerHTML = `
            <div class="feed-card-cover" style="display:flex;align-items:center;justify-content:center">
                <i data-lucide="list-music" class="pl-cover-skeleton" style="width:32px;height:32px;color:var(--text-sec)"></i>
                <div class="feed-card-overlay">
                    <button class="feed-card-play"><i data-lucide="play" style="width:14px;height:14px"></i></button>
                </div>
            </div>
            <div class="feed-card-title">${escapeHtml(pl.name)}</div>
            <div class="feed-card-sub">${pl.track_count || 0} треков</div>
        `;
        // Collage of the first 4 track covers (skeleton stays until resolved;
        // with 0 covers the skeleton remains as-is).
        attachPlaylistCollage(pl, card.querySelector('.feed-card-cover'));
        card.addEventListener('click', async () => {
            if (window.pywebview?.api?.get_playlist_tracks) {
                const res = await window.pywebview.api.get_playlist_tracks(pl.id);
                const tracks = Array.isArray(res) ? res : (res && Array.isArray(res.tracks) ? res.tracks : []);
                if (tracks && tracks.length > 0) {
                    window.pywebview.api.play_track(tracks[0], tracks);
                }
            }
        });
        container.appendChild(card);
    });
    renderIcons(container);
}

// ─── Real artist avatars (photo upgrade over the letter discs) ─────────────
// The DB stores artist names only, so cards first paint the deterministic
// letter disc; this block then swaps in the real channel photo resolved by
// the backend (one YT Music search per unknown artist, cached a week in
// localStorage so subsequent launches paint photos instantly).
const AVATAR_LS_KEY = 'nedotify_artist_avatars_v1';
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
        if (!coverEl || coverEl.querySelector('img')) return;
        const img = document.createElement('img');
        img.alt = name;
        img.loading = 'lazy';
        img.style.cssText = 'width:100%;height:100%;object-fit:cover;';
        // On failure the letter disc stays: just remove the broken img.
        img.addEventListener('error', () => img.remove());
        img.src = url;
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
            window.pywebview.api.get_artists_avatars(missing);
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

    artists.forEach(artist => {
        const card = document.createElement('div');
        card.className = 'feed-card artist-card';
        card.style.minWidth = '120px';
        card.style.maxWidth = '120px';
        const cover = getCoverUrl(artist);
        const artistName = artist.artist || artist.name || 'Unknown';
        // No artist-photo source exists locally (DB stores names only): show
        // the gradient+letter avatar instead of a broken empty image.
        const coverHtml = cover
            ? `<div class="feed-card-cover">${coverImgHtml({ src: cover, coverUrl: artist.cover_url || '', alt: artistName })}</div>`
            : `<div class="feed-card-cover">${artistAvatarHtml(artistName)}</div>`;
        card.innerHTML = `
            ${coverHtml}
            <div class="feed-card-title" style="text-align:center">${escapeHtml(artistName)}</div>
        `;
        card.addEventListener('click', () => {
            const input = document.getElementById('search-input');
            if (input) {
                input.value = artistName;
                if (window.showPage) window.showPage('search');
                input.dispatchEvent(new Event('input', { bubbles: true }));
            }
        });
        container.appendChild(card);
    });
    renderIcons(container);
    requestArtistAvatars(artists.map(a => a.artist || a.name));
}

function renderFeedSection(containerId, tracks) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';

    if (!tracks || tracks.length === 0) {
        container.innerHTML = '<div class="empty-state text-sm" style="padding:20px">Нет данных</div>';
        return;
    }

    tracks.forEach((track, idx) => {
        container.appendChild(createFeedCard(track, tracks, idx));
    });
    renderIcons(container);
}

function createFeedCard(track, trackList = null, trackIndex = 0) {
    const card = document.createElement('div');
    card.className = 'feed-card';

    if (track.type === 'custom_playlist') {
        // Generate consistent vibrant colors based on title
        let hash = 0;
        const safeTitle = track.title || '';
        for (let i = 0; i < safeTitle.length; i++) hash = safeTitle.charCodeAt(i) + ((hash << 5) - hash);
        const hue1 = Math.abs(hash % 360);
        const hue2 = (hue1 + 40 + Math.abs((hash >> 2) % 60)) % 360;
        
        card.innerHTML = `
            <div class="feed-card-cover" style="background: linear-gradient(135deg, hsl(${hue1}, 85%, 55%), hsl(${hue2}, 85%, 45%)); overflow: hidden; position: relative;">
                <!-- Decorative wave pattern -->
                <div style="position: absolute; bottom: -20%; right: -20%; width: 140%; height: 100%; background: linear-gradient(to top right, rgba(0,0,0,0.4), transparent); border-top-left-radius: 50%; transform: rotate(-15deg);"></div>
                
                <!-- If there's a cover_url, show it subtly or as a small badge. Otherwise just colors. -->
                ${track.cover_url && !track.cover_url.includes('hqdefault') ? `<div style="position:absolute; bottom: -10px; right: -10px; width: 60%; height: 60%; border-radius: 12px; background-image: url('${escapeHtml(track.cover_url)}'); background-size: cover; box-shadow: 0 8px 16px rgba(0,0,0,0.4); transform: rotate(-10deg); opacity: 0.8;"></div>` : ''}
                
                <!-- YT Music style persistent play icon ring -->
                <div style="position: absolute; top: 12px; left: 12px; width: 32px; height: 32px; border-radius: 50%; background: #000; border: 2px solid hsl(${hue1}, 80%, 70%); display:flex; align-items:center; justify-content:center; box-shadow: 0 4px 8px rgba(0,0,0,0.3);">
                    <i data-lucide="play" style="width:12px;height:12px;fill:hsl(${hue1}, 80%, 70%); color:hsl(${hue1}, 80%, 70%); margin-left: 2px;"></i>
                </div>
                
                <div class="feed-card-overlay">
                    <button class="feed-card-play" style="background: rgba(0,0,0,0.6);"><i data-lucide="play" style="width:16px;height:16px;fill:#fff;color:#fff"></i></button>
                </div>
            </div>
            <div class="feed-card-title">${escapeHtml(track.title)}</div>
            <div class="feed-card-sub">${escapeHtml(track.artist || 'Микс')}</div>
        `;
        card.addEventListener('click', () => {
            if (window.pywebview?.api?.play_track && track.tracks && track.tracks.length > 0) {
                window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: `Включаю: ${track.title}...`, type: 'info' } }));
                window.pywebview.api.play_track(track.tracks[0], track.tracks, 0);
            }
        });
        return card;
    }

    const cover = getCoverUrl(track);
    card.innerHTML = `
        <div class="feed-card-cover">
            ${coverImgHtml({ src: cover, coverUrl: track.cover_url || '', sourceId: track.source_id || '', source: track.source || '' })}
            <div class="feed-card-overlay">
                <button class="feed-card-play"><i data-lucide="play" style="width:14px;height:14px;fill:currentColor"></i></button>
            </div>
        </div>
        <div class="feed-card-title">${escapeHtml(track.title || 'Unknown')}</div>
        <div class="feed-card-sub clickable-artist">${escapeHtml(track.artist || '')}</div>
    `;
    
    const subEl = card.querySelector('.feed-card-sub');
    if (subEl && track.artist && track.artist !== 'Unknown' && track.artist !== 'Микс') {
        subEl.addEventListener('click', (e) => {
            e.stopPropagation();
            e.preventDefault();
            if (window.searchArtistProfile) {
                window.searchArtistProfile(track.artist);
            } else if (window.NeDotify?.searchArtistProfile) {
                window.NeDotify.searchArtistProfile(track.artist);
            }
        });
    }

    card.addEventListener('click', (e) => {
        if (e.target.closest('.clickable-artist') || e.target.closest('.feed-card-sub')) return;
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

window.addEventListener('app:mood_playlists_ready', (e) => {
    const data = e.detail;
    renderFeedSection('home-mood', data);
});

window.addEventListener('app:artists_ready', (e) => {
    clearFeedTimeout('home-artists');
    renderArtists(e.detail);
});

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

    tracks.forEach((track, i) => {
        const cover = getCoverUrl(track);
        const card = document.createElement('div');
        card.className = 'feed-card';
        const playCount = track.play_count || track.plays || track.total_plays || 0;
        card.innerHTML = `
            <div class="feed-card-cover">
                ${coverImgHtml({ src: cover, coverUrl: track.cover_url || '', sourceId: track.source_id || '', source: track.source || '' })}
                <div class="feed-card-overlay">
                    <button class="feed-card-play"><i data-lucide="play" style="width:14px;height:14px;fill:currentColor"></i></button>
                </div>
            </div>
            <div class="feed-card-title">${escapeHtml(track.title || 'Unknown Title')}</div>
            <div class="feed-card-sub">${escapeHtml(track.artist || 'Unknown')} (${playCount})</div>
        `;
        card.onclick = () => {
            if (window.pywebview?.api) window.pywebview.api.play_track(track, tracks, i);
        };
        container.appendChild(card);
    });
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

    artists.forEach(artist => {
        const card = document.createElement('div');
        card.className = 'feed-card artist-card';
        const artistName = artist.artist || artist.name || 'Unknown';
        const playsCount = artist.total_plays || artist.play_count || artist.plays || 0;
        card.innerHTML = `
            <div class="feed-card-cover">${artistAvatarHtml(artistName)}</div>
            <div class="feed-card-title" style="text-align: center;">${escapeHtml(artistName)}</div>
            <div class="feed-card-sub" style="text-align: center;">${playsCount} раз</div>
        `;
        card.onclick = () => {
            window.appConfig = window.appConfig || {};
            window.appConfig.searchQuery = artistName;
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            const searchNav = document.querySelector('[data-page="search"]');
            if (searchNav) searchNav.classList.add('active');
            if (window.NeDotify && window.NeDotify.showPage) {
                window.NeDotify.showPage('search');
            } else {
                const searchTab = document.getElementById('tab-search');
                if (searchTab) searchTab.click();
            }
        };
        container.appendChild(card);
    });
    renderIcons(container);
    requestArtistAvatars(artists.map(a => a.artist || a.name));
}

let currentWrappedPeriod = 'week';

export async function loadWrappedStats(period = 'week') {
    currentWrappedPeriod = period;
    await window.awaitBridge();
    if (!window.pywebview?.api || !window.pywebview.api.get_wrapped_stats) return;

    try {
        const stats = await window.pywebview.api.get_wrapped_stats(period);
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
        list.appendChild(row);
    });
}

function renderActivityChart(activity) {
    const canvas = document.getElementById('wrapped-activity-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width = canvas.parentElement.clientWidth || 300;
    const h = canvas.height = 140;

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



