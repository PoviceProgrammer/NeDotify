// NeDotify вЂ” Search Module Redesign
import { createTrackElement, renderIcons, filterVisibleTracks, escapeHtml } from './utils.js?v=20260820_2';
import { getCurrentTrack } from './player.js?v=20260820_2';
import { 
    loadArtistProfile, 
    ArtistPhotoComponent, 
    ArtistBioComponent, 
    ArtistAlbumsComponent, 
    ArtistTracksComponent 
} from './artist_profile.js?v=20260820_2';

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
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                input.blur();
                const query = e.target.value.trim();
                if (query.length > 0) {
                    clearTimeout(searchDebounce);
                    showLoading();
                    allResults = [];
                    currentSearchQuery = query;
                    api('search', query, currentSource, currentType === 'all' ? null : currentType);
                }
            }
        });

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
                    api('search', query, currentSource, currentType === 'all' ? null : currentType);
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
                api('search', query, currentSource, currentType === 'all' ? null : currentType);
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
                        container.innerHTML = '<div class="empty-state">Введите имя артиста для поиска</div>';
                    }
                }
            } else {
                const query = input?.value.trim() || currentSearchQuery;
                if (query) {
                    showLoading();
                    allResults = [];
                    currentSearchQuery = query;
                    api('search', query, currentSource, currentType === 'all' ? null : currentType);
                } else {
                    showPlaceholder();
                }
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
        const filteredTracks = filterVisibleTracks(data.tracks);
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

    if (currentType === 'albums') {
        const albumsMap = new Map();
        tracks.forEach((t, idx) => {
            if (t.type === 'album') {
                const key = `${(t.title || '').toLowerCase()}_${(t.artist || '').toLowerCase()}`;
                if (!albumsMap.has(key)) {
                    albumsMap.set(key, t);
                }
            } else if (t.album && t.album !== 'Unknown Album' && t.album !== 'Spotify Album') {
                const key = `${(t.album || '').toLowerCase()}_${(t.artist || '').toLowerCase()}`;
                if (!albumsMap.has(key)) {
                    albumsMap.set(key, {
                        id: `album_${idx}`,
                        title: t.album,
                        artist: t.artist || 'Unknown Artist',
                        year: t.year || '',
                        cover_url: t.cover_url || t.cover_path || '',
                        source: t.source || 'youtube',
                        source_id: t.source_id || '',
                        type: 'album',
                        track_count: 1
                    });
                } else {
                    const existing = albumsMap.get(key);
                    existing.track_count = (existing.track_count || 1) + 1;
                }
            } else {
                const key = `${(t.title || '').toLowerCase()}_${(t.artist || '').toLowerCase()}`;
                if (!albumsMap.has(key)) {
                    albumsMap.set(key, {
                        id: t.id || `album_${idx}`,
                        title: t.title,
                        artist: t.artist || 'Unknown Artist',
                        year: t.year || '',
                        cover_url: t.cover_url || t.cover_path || '',
                        source: t.source || 'youtube',
                        source_id: t.source_id || '',
                        type: 'album',
                        track_count: 1
                    });
                }
            }
        });

        const albumList = Array.from(albumsMap.values());
        if (albumList.length > 0) {
            renderAlbumGrid(albumList, container);
            renderIcons();
            return;
        }
    }

    if (currentType === 'artists') {
        const uniqueArtists = new Set();
        tracks.forEach(t => { if (t.artist && t.artist !== 'Unknown Artist') uniqueArtists.add(t.artist); });
        
        const artistGrid = document.createElement('div');
        artistGrid.className = 'artist-cards-grid';
        artistGrid.style.cssText = 'display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; animation: fadeIn 0.3s ease;';

        const artistList = uniqueArtists.size > 0 ? Array.from(uniqueArtists) : [currentSearchQuery];
        artistList.slice(0, 8).forEach(artistName => {
            const artistTrack = tracks.find(t => t.artist === artistName) || {};
            const cover = artistTrack.cover_url || artistTrack.cover_path || '';

            const card = document.createElement('div');
            card.className = 'feed-card artist-card';
            card.style.cssText = 'padding: 16px; border-radius: 16px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); display: flex; flex-direction: column; align-items: center; text-align: center; gap: 10px; cursor: pointer; transition: transform 0.2s, background 0.2s;';
            card.innerHTML = `
                <div class="feed-card-cover" style="width: 90px; height: 90px; border-radius: 50%; overflow: hidden; background: linear-gradient(135deg, var(--primary), rgba(255,255,255,0.1)); display: flex; align-items: center; justify-content: center; box-shadow: 0 6px 16px rgba(0,0,0,0.3);">
                    ${cover ? `<img src="${escapeHtml(cover)}" alt="" onerror="this.onerror=null;this.style.display='none'" style="width:100%;height:100%;object-fit:cover;">` : '<i data-lucide="user" style="width:40px;height:40px;color:rgba(255,255,255,0.6)"></i>'}
                </div>
                <div style="font-weight: 700; font-size: 14px; color: #ffffff; width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(artistName)}</div>
                <div style="font-size: 11px; color: var(--text-sec);">Исполнитель • Профиль</div>
                <button class="type-filter-btn active" style="margin-top: 4px; padding: 5px 14px; font-size: 11px; border-radius: 20px;">Открыть профиль</button>
            `;
            card.onclick = () => searchArtistProfile(artistName);
            artistGrid.appendChild(card);
        });

        container.appendChild(artistGrid);
        renderIcons();
        return;
    }

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
        const metaStr = [year, trackCountStr].filter(Boolean).join(' • ');

        let hash = 0;
        for (let i = 0; i < title.length; i++) hash = ((hash << 5) - hash) + title.charCodeAt(i);
        const grad = colors[Math.abs(hash) % colors.length];

        const card = document.createElement('div');
        card.className = 'feed-card album-card';
        card.style.cssText = 'padding: 14px; border-radius: 16px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); display: flex; flex-direction: column; gap: 10px; cursor: pointer; transition: transform 0.2s, background 0.2s, box-shadow 0.2s; position: relative;';
        
        card.innerHTML = `
            <div class="feed-card-cover album-cover-wrap fallback-gradient" style="width: 100%; aspect-ratio: 1/1; border-radius: 12px; overflow: hidden; background: ${grad}; display: flex; align-items: center; justify-content: center; position: relative; box-shadow: 0 8px 20px rgba(0,0,0,0.35);">
                <svg class="fallback-note-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:40%;height:40%;opacity:0.6;position:relative;z-index:1;"><path d="M9 18V5l12-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="18" cy="16" r="3"></circle></svg>
                ${cover ? `<img src="${escapeHtml(cover)}" alt="" onerror="this.onerror=null;this.style.display='none'" style="width:100%;height:100%;object-fit:cover;position:absolute;top:0;left:0;z-index:2;">` : ''}
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

export async function playAlbum(album, cardElement = null) {
    if (!album) return;
    const playBtn = cardElement?.querySelector('.album-play-btn');
    if (playBtn) {
        playBtn.innerHTML = '<div class="spinner" style="width:18px;height:18px;border-width:2px;"></div>';
    }

    try {
        let tracks = [];
        if (window.pywebview?.api?.get_album_tracks) {
            tracks = await window.pywebview.api.get_album_tracks(album);
        }

        if (tracks && tracks.length > 0) {
            if (window.pywebview?.api?.play_track) {
                window.pywebview.api.play_track(tracks[0], tracks, 0);
            }
        } else {
            // Fallback: search query for album tracks
            const q = `${album.artist || ''} ${album.title || ''}`.trim();
            if (q && window.pywebview?.api?.search) {
                window.pywebview.api.search(q, album.source || 'youtube');
            }
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

export async function openAlbumModal(album) {
    let modal = document.getElementById('album-detail-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'album-detail-modal';
        modal.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,0.75); backdrop-filter:blur(10px); z-index:9999; display:flex; align-items:center; justify-content:center; animation:fadeIn 0.25s ease; padding:20px;';
        document.body.appendChild(modal);
    }
    modal.style.display = 'flex';
    modal.innerHTML = `
        <div style="background:var(--bg-card, #181818); border:1px solid rgba(255,255,255,0.12); border-radius:20px; width:100%; max-width:680px; max-height:85vh; display:flex; flex-direction:column; overflow:hidden; box-shadow:0 20px 50px rgba(0,0,0,0.6);">
            <div style="display:flex; justify-content:space-between; align-items:center; padding:16px 20px; border-bottom:1px solid rgba(255,255,255,0.08);">
                <span style="font-weight:700; font-size:15px; color:var(--text-main);">Альбом</span>
                <button id="close-album-modal" style="background:none; border:none; color:var(--text-sec); cursor:pointer; padding:4px;">
                    <i data-lucide="x" style="width:20px;height:20px"></i>
                </button>
            </div>
            <div style="padding:20px; display:flex; gap:20px; align-items:center; background:linear-gradient(180deg, rgba(255,255,255,0.06) 0%, transparent 100%);">
                <img src="${escapeHtml(album.cover_url || album.cover || album.cover_path || '')}" alt="" onerror="this.onerror=null;this.style.display='none'" style="width:110px; height:110px; border-radius:12px; object-fit:cover; box-shadow:0 8px 24px rgba(0,0,0,0.4);">
                <div style="display:flex; flex-direction:column; gap:6px; flex:1; overflow:hidden;">
                    <div style="font-size:20px; font-weight:800; color:#fff; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(album.title || 'Альбом')}</div>
                    <div style="font-size:14px; color:var(--text-sec);">${escapeHtml(album.artist || 'Исполнитель')}</div>
                    <div style="font-size:12px; color:var(--text-sec); opacity:0.8;">${album.year ? album.year + ' г. • ' : ''}${album.track_count ? album.track_count + ' треков' : 'Альбом'}</div>
                    <div style="margin-top:8px; display:flex; gap:10px;">
                        <button id="btn-play-full-album" style="padding:8px 18px; border-radius:24px; border:none; background:var(--primary); color:#fff; font-weight:700; font-size:12px; cursor:pointer; display:flex; align-items:center; gap:6px;">
                            <i data-lucide="play" style="width:14px;height:14px;fill:currentColor"></i> Слушать всё
                        </button>
                    </div>
                </div>
            </div>
            <div id="album-modal-tracks" class="feed-scroll" style="flex:1; overflow-y:auto; padding:12px 20px; display:flex; flex-direction:column; gap:4px;">
                <div class="empty-state" style="padding:30px;"><div class="spinner"></div><span>Загрузка треков альбома...</span></div>
            </div>
        </div>
    `;
    renderIcons();

    document.getElementById('close-album-modal')?.addEventListener('click', () => {
        modal.style.display = 'none';
    });
    modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.style.display = 'none';
    });

    let albumTracks = [];
    if (window.pywebview?.api?.get_album_tracks) {
        try {
            albumTracks = await window.pywebview.api.get_album_tracks(album);
        } catch (e) {
            console.error("Error loading album tracks:", e);
        }
    }

    const tracksContainer = document.getElementById('album-modal-tracks');
    if (!tracksContainer) return;

    if (!albumTracks || albumTracks.length === 0) {
        tracksContainer.innerHTML = '<div class="empty-state" style="padding:30px 0;">Треки этого альбома недоступны</div>';
        return;
    }

    tracksContainer.innerHTML = '';
    albumTracks.forEach((t, idx) => {
        tracksContainer.appendChild(createTrackElement(t, idx, albumTracks, getCurrentTrack()));
    });
    renderIcons();

    document.getElementById('btn-play-full-album')?.addEventListener('click', () => {
        if (albumTracks.length > 0 && window.pywebview?.api?.play_track) {
            window.pywebview.api.play_track(albumTracks[0], albumTracks, 0);
            modal.style.display = 'none';
        }
    });
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





