// NeDotify вЂ” Library Module (Favorites, Playlists, Local Files)
import { createTrackElement, renderIcons } from './utils.js?v=19';
import { getCurrentTrack } from './player.js?v=19';

let currentContextTrack = null;

let currentActiveTracks = [];

export function initLibrary() {
    // Top card click handlers
    const favCard = document.getElementById('lib-card-favorites');
    if (favCard) {
        favCard.addEventListener('click', () => selectSection('favorites'));
    }

    const offlineCard = document.getElementById('lib-card-offline');
    if (offlineCard) {
        offlineCard.addEventListener('click', () => selectSection('offline'));
    }

    // Sidebar Action Buttons
    const btnImport = document.getElementById('lib-btn-import');
    if (btnImport) {
        btnImport.addEventListener('click', () => {
            if (window.pywebview?.api?.open_local_file) {
                window.pywebview.api.open_local_file();
            }
        });
    }

    const modalIP = document.getElementById('modal-import-playlist');
    const btnConvert = document.getElementById('lib-btn-convert');
    if (btnConvert) {
        btnConvert.addEventListener('click', () => {
            if (modalIP) {
                modalIP.style.display = 'flex';
                const inputUrl = document.getElementById('modal-ip-url');
                if (inputUrl) inputUrl.focus();
            }
        });
    }

    const closeIP = () => {
        if (modalIP) modalIP.style.display = 'none';
        const statusEl = document.getElementById('modal-ip-status');
        if (statusEl) statusEl.style.display = 'none';
        const submitBtn = document.getElementById('modal-ip-submit');
        if (submitBtn) submitBtn.disabled = false;
    };

    document.getElementById('modal-ip-close')?.addEventListener('click', closeIP);
    document.getElementById('modal-ip-cancel')?.addEventListener('click', closeIP);

    document.getElementById('modal-ip-submit')?.addEventListener('click', async () => {
        const urlInput = document.getElementById('modal-ip-url');
        const nameInput = document.getElementById('modal-ip-name');
        const statusEl = document.getElementById('modal-ip-status');
        const submitBtn = document.getElementById('modal-ip-submit');

        const url = urlInput ? urlInput.value.trim() : '';
        const name = nameInput ? nameInput.value.trim() : '';

        if (!url) {
            window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Введите ссылку на плейлист', type: 'warning' } }));
            return;
        }

        if (statusEl) statusEl.style.display = 'flex';
        if (submitBtn) submitBtn.disabled = true;

        if (window.pywebview?.api?.import_external_playlist) {
            window.pywebview.api.import_external_playlist(url, name);
        }

        setTimeout(() => {
            closeIP();
            if (urlInput) urlInput.value = '';
            if (nameInput) nameInput.value = '';
        }, 1500);
    });

    // Add playlist from sidebar input
    const addPlBtn = document.getElementById('lib-btn-add-playlist');
    const plInput = document.getElementById('lib-quick-pl-input');

    const handleCreateQuick = async () => {
        const name = plInput ? plInput.value.trim() : '';
        if (!name) {
            if (window.NeDotify?.createPlaylist) window.NeDotify.createPlaylist();
            return;
        }
        if (window.pywebview?.api?.create_playlist) {
            try {
                await window.pywebview.api.create_playlist(name);
                if (plInput) plInput.value = '';
                loadPlaylists();
            } catch (e) {
                console.error("Create playlist error:", e);
            }
        }
    };

    if (addPlBtn) addPlBtn.addEventListener('click', handleCreateQuick);
    if (plInput) {
        plInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') handleCreateQuick();
        });
    }

    // Play all button in active view
    const playAllBtn = document.getElementById('lib-btn-play-all');
    if (playAllBtn) {
        playAllBtn.addEventListener('click', () => {
            if (currentActiveTracks && currentActiveTracks.length > 0) {
                if (window.NeDotify?.playTrack) {
                    window.NeDotify.playTrack(currentActiveTracks[0], currentActiveTracks);
                }
            }
        });
    }
}

export async function loadLibrary() {
    loadLibrarySummary();
    loadPlaylists();
}

export async function loadLibrarySummary() {
    // Update Favorite count
    try {
        let localFavs = [];
        try {
            const raw = localStorage.getItem('nedotify_favorites');
            if (raw) localFavs = JSON.parse(raw);
        } catch (e) {}

        let backendFavs = [];
        if (window.pywebview?.api?.get_favorites) {
            backendFavs = await window.pywebview.api.get_favorites() || [];
        }

        const favCombined = [...localFavs];
        backendFavs.forEach(bt => {
            const bId = bt.id || bt.source_id;
            if (!favCombined.some(lt => (lt.id || lt.source_id) === bId)) {
                favCombined.push(bt);
            }
        });

        const favSub = document.getElementById('lib-fav-count');
        if (favSub) {
            favSub.textContent = favCombined.length > 0 ? `${favCombined.length} треков` : 'Нет треков';
        }
    } catch (e) {}

    // Update Offline count
    try {
        if (window.pywebview?.api?.get_downloaded_tracks) {
            const downloaded = await window.pywebview.api.get_downloaded_tracks() || [];
            const offSub = document.getElementById('lib-offline-count');
            if (offSub) {
                offSub.textContent = downloaded.length > 0 ? `${downloaded.length} треков` : 'Нет треков';
            }
        }
    } catch (e) {}
}

export async function selectSection(type, data = null) {
    const emptyEl = document.getElementById('lib-empty-selection');
    const activeView = document.getElementById('lib-active-view');
    const titleEl = document.getElementById('lib-active-title');
    const subEl = document.getElementById('lib-active-sub');
    const tracksContainer = document.getElementById('lib-active-tracks');

    if (!activeView || !tracksContainer) return;

    if (emptyEl) emptyEl.style.display = 'none';
    activeView.style.display = 'flex';
    tracksContainer.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';

    // Reset active highlights
    document.querySelectorAll('.lib-top-card').forEach(c => c.classList.remove('active'));
    document.querySelectorAll('.lib-playlist-item').forEach(i => i.classList.remove('active'));

    if (type === 'favorites') {
        const favCard = document.getElementById('lib-card-favorites');
        if (favCard) favCard.classList.add('active');
        if (titleEl) titleEl.textContent = 'Любимые треки';

        let localFavs = [];
        try {
            const raw = localStorage.getItem('nedotify_favorites');
            if (raw) localFavs = JSON.parse(raw);
        } catch (e) {}

        let backendFavs = [];
        if (window.pywebview?.api?.get_favorites) {
            backendFavs = await window.pywebview.api.get_favorites() || [];
        }

        const combined = [...localFavs];
        backendFavs.forEach(bt => {
            const bId = bt.id || bt.source_id;
            if (!combined.some(lt => (lt.id || lt.source_id) === bId)) {
                combined.push(bt);
            }
        });

        currentActiveTracks = combined;
        if (subEl) subEl.textContent = `${combined.length} треков`;

        if (combined.length === 0) {
            tracksContainer.innerHTML = '<div class="empty-state">Нет любимых треков</div>';
            return;
        }

        tracksContainer.innerHTML = '';
        combined.forEach((track, i) => {
            tracksContainer.appendChild(createTrackElement(track, i, combined, getCurrentTrack()));
        });
        renderIcons();

    } else if (type === 'offline') {
        const offCard = document.getElementById('lib-card-offline');
        if (offCard) offCard.classList.add('active');
        if (titleEl) titleEl.textContent = 'Оффлайн треки';

        let downloaded = [];
        if (window.pywebview?.api?.get_downloaded_tracks) {
            downloaded = await window.pywebview.api.get_downloaded_tracks() || [];
        }

        // Deduplicate tracks by title and artist
        const seen = new Set();
        const uniqueDownloaded = [];
        downloaded.forEach(t => {
            const key = `${(t.title || '').toLowerCase().trim()}___${(t.artist || '').toLowerCase().trim()}`;
            if (!seen.has(key)) {
                seen.add(key);
                uniqueDownloaded.push(t);
            }
        });
        downloaded = uniqueDownloaded;

        currentActiveTracks = downloaded;
        if (subEl) subEl.textContent = `${downloaded.length} треков`;

        if (downloaded.length === 0) {
            tracksContainer.innerHTML = '<div class="empty-state">Нет скачанных треков</div>';
            return;
        }

        tracksContainer.innerHTML = '';
        downloaded.forEach((track, i) => {
            tracksContainer.appendChild(createTrackElement(track, i, downloaded, getCurrentTrack()));
        });
        renderIcons();

    } else if (type === 'playlist' && data) {
        if (titleEl) titleEl.textContent = data.name || 'Плейлист';

        let tracks = [];
        if (window.pywebview?.api?.get_playlist_tracks) {
            tracks = await window.pywebview.api.get_playlist_tracks(data.id) || [];
        }

        // Deduplicate tracks by title and artist
        const seen = new Set();
        const uniqueTracks = [];
        tracks.forEach(t => {
            const key = `${(t.title || '').toLowerCase().trim()}___${(t.artist || '').toLowerCase().trim()}`;
            if (!seen.has(key)) {
                seen.add(key);
                uniqueTracks.push(t);
            }
        });
        tracks = uniqueTracks;

        currentActiveTracks = tracks;
        if (subEl) subEl.textContent = `${tracks.length} треков`;

        if (tracks.length === 0) {
            tracksContainer.innerHTML = '<div class="empty-state">В этом плейлисте пока нет треков</div>';
            return;
        }

        tracksContainer.innerHTML = '';
        tracks.forEach((track, i) => {
            tracksContainer.appendChild(createTrackElement(track, i, tracks, getCurrentTrack()));
        });
        renderIcons();
    }
}

export async function loadFavorites() {
    loadLibrarySummary();
    const activeView = document.getElementById('lib-active-view');
    if (activeView && activeView.style.display !== 'none') {
        const titleEl = document.getElementById('lib-active-title');
        if (titleEl && titleEl.textContent === 'Любимые треки') {
            return selectSection('favorites');
        }
    }
}

export async function loadDownloaded() {
    loadLibrarySummary();
    const activeView = document.getElementById('lib-active-view');
    if (activeView && activeView.style.display !== 'none') {
        const titleEl = document.getElementById('lib-active-title');
        if (titleEl && titleEl.textContent === 'Оффлайн треки') {
            return selectSection('offline');
        }
    }
}

export async function loadPlaylists() {
    const sidebarList = document.getElementById('lib-sidebar-playlists');
    if (!sidebarList || !window.pywebview?.api) return;

    try {
        const playlists = await window.pywebview.api.get_playlists();
        if (!playlists || playlists.length === 0) {
            sidebarList.innerHTML = '<div class="empty-state text-sm" style="padding:12px;font-size:12px">Нет плейлистов</div>';
            return;
        }

        sidebarList.innerHTML = '';
        playlists.forEach(pl => {
            const id = pl.id !== undefined ? pl.id : pl.ID;
            const item = document.createElement('div');
            item.className = 'lib-playlist-item';
            item.setAttribute('data-pl-id', id);

            const isDownloadedPl = pl.name === 'Скачанное';
            const iconName = isDownloadedPl ? 'download' : 'music';
            const iconColor = isDownloadedPl ? 'var(--primary)' : 'var(--text-sec)';

            item.innerHTML = `
                <i data-lucide="${iconName}" style="width:14px;height:14px;color:${iconColor};flex-shrink:0;"></i>
                <span class="truncate" style="${isDownloadedPl ? 'font-weight:600;' : ''}">${pl.name}</span>
            `;
            item.addEventListener('click', () => {
                document.querySelectorAll('.lib-playlist-item').forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                selectSection('playlist', { id, name: pl.name });
            });
            sidebarList.appendChild(item);
        });
        renderIcons();
    } catch (e) {
        console.error("Load playlists error:", e);
    }
}

// в”Ђв”Ђв”Ђ Playlist Context Menu в”Ђв”Ђв”Ђ

export function openPlaylistMenu(track, x, y) {
    currentContextTrack = track;
    const menu = document.getElementById('playlist-context-menu');
    const items = document.getElementById('playlist-menu-items');
    if (!menu || !items) return;

    menu.style.left = `${x}px`;
    menu.style.top = `${y}px`;
    menu.classList.add('visible');

    items.innerHTML = '<div class="context-menu-item" style="justify-content:center"><div class="spinner"></div></div>';

    loadPlaylistMenuItems(items, menu);
}

async function loadPlaylistMenuItems(items, menu) {
    try {
        const playlists = await window.pywebview.api.get_playlists();
        items.innerHTML = '';

        if (playlists && playlists.length > 0) {
            playlists.forEach(pl => {
                const btn = document.createElement('button');
                btn.className = 'context-menu-item';
                btn.innerHTML = `<i data-lucide="list-music" style="width:14px;height:14px;color:var(--text-sec)"></i> ${pl.name}`;
                btn.addEventListener('click', async () => {
                    const plId = pl.id !== undefined ? pl.id : pl.ID;
                    await window.pywebview.api.add_to_playlist(plId, currentContextTrack);
                    menu.classList.remove('visible');
                    loadPlaylists();
                });
                items.appendChild(btn);
            });
            renderIcons();
        }

        // Create new playlist button
        const divider = document.createElement('div');
        divider.className = 'context-menu-divider';
        items.appendChild(divider);

        const createBtn = document.createElement('button');
        createBtn.className = 'context-menu-item';
        createBtn.innerHTML = '<i data-lucide="plus" style="width:14px;height:14px;color:var(--primary)"></i> Новый плейлист';
        createBtn.addEventListener('click', async () => {
            menu.classList.remove('visible');
            await createPlaylist();
        });
        items.appendChild(createBtn);
        renderIcons();
    } catch (e) {
        items.innerHTML = '<div class="context-menu-item" style="color:var(--error)">Ошибка</div>';
    }
}

export async function createPlaylist() {
    const modal = document.getElementById('modal-create-playlist');
    const input = document.getElementById('modal-cp-input');
    const closeBtn = document.getElementById('modal-cp-close');
    const cancelBtn = document.getElementById('modal-cp-cancel');
    const submitBtn = document.getElementById('modal-cp-submit');

    if (!modal || !input) return;

    input.value = '';
    modal.style.display = 'flex';
    setTimeout(() => input.focus(), 50);

    const closeModal = () => {
        modal.style.display = 'none';
        closeBtn?.removeEventListener('click', closeModal);
        cancelBtn?.removeEventListener('click', closeModal);
        submitBtn?.removeEventListener('click', handleSubmit);
        input?.removeEventListener('keydown', handleKeyDown);
    };

    const handleSubmit = async () => {
        const name = input.value.trim();
        if (name) {
            try {
                const plId = await window.pywebview.api.create_playlist(name);
                if (plId && currentContextTrack) {
                    await window.pywebview.api.add_to_playlist(plId, currentContextTrack);
                }
            } catch (e) {
                console.error("Failed to add track to new playlist:", e);
            }
            loadPlaylists();
        }
        closeModal();
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            handleSubmit();
        } else if (e.key === 'Escape') {
            closeModal();
        }
    };

    closeBtn?.addEventListener('click', closeModal);
    cancelBtn?.addEventListener('click', closeModal);
    submitBtn?.addEventListener('click', handleSubmit);
    input?.addEventListener('keydown', handleKeyDown);
}

document.addEventListener('nedotify:track_downloaded', () => {
    loadDownloaded();
});



