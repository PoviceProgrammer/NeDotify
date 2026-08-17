// NeDotify вЂ” Library Module (Favorites, Playlists, Local Files)
import { createTrackElement, renderIcons, escapeHtml } from './utils.js?v=20260814_9';
import { getCurrentTrack } from './player.js?v=20260814_9';

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

    // Download all favorites button & Batch Progress
    const btnDownloadAll = document.getElementById('lib-btn-download-all');
    const batchProgressBox = document.getElementById('lib-batch-progress-box');
    const batchProgressBar = document.getElementById('lib-batch-progress-bar');
    const batchProgressCount = document.getElementById('lib-batch-progress-count');
    const btnBatchCancel = document.getElementById('lib-btn-batch-cancel');

    if (btnDownloadAll) {
        btnDownloadAll.addEventListener('click', async () => {
            if (window.pywebview?.api?.download_all_favorites) {
                btnDownloadAll.disabled = true;
                btnDownloadAll.style.opacity = '0.6';
                window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: '⏳ Проверка свободного места и запуск скачивания...', type: 'info' } }));
                try {
                    const res = await window.pywebview.api.download_all_favorites();
                    if (res && res.success) {
                        if (res.count > 0 && batchProgressBox) {
                            batchProgressBox.style.display = 'inline-flex';
                            if (batchProgressBar) batchProgressBar.style.width = '0%';
                            if (batchProgressCount) batchProgressCount.textContent = `0 / ${res.count}`;
                        }
                        window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: res.message || 'Скачивание начато', type: 'success' } }));
                    } else {
                        window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: res?.message || 'Ошибка запуска скачивания', type: 'warning' } }));
                    }
                } catch(e) {
                    window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Ошибка вызова скачивания', type: 'error' } }));
                } finally {
                    btnDownloadAll.disabled = false;
                    btnDownloadAll.style.opacity = '1';
                }
            }
        });
    }

    if (btnBatchCancel) {
        btnBatchCancel.addEventListener('click', async () => {
            if (window.pywebview?.api?.cancel_batch_download) {
                await window.pywebview.api.cancel_batch_download();
                if (batchProgressBox) batchProgressBox.style.display = 'none';
                window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Пакетное скачивание отменено', type: 'warning' } }));
            }
        });
    }

    // Document event listeners for batch downloading dispatched via events.js
    document.addEventListener('nedotify:batch_download_started', (e) => {
        const data = e.detail || {};
        if (batchProgressBox) batchProgressBox.style.display = 'inline-flex';
        if (batchProgressBar) batchProgressBar.style.width = '0%';
        if (batchProgressCount) batchProgressCount.textContent = `0 / ${data.total || 0}`;
    });

    document.addEventListener('nedotify:batch_download_progress', (e) => {
        const data = e.detail || {};
        if (batchProgressBox) batchProgressBox.style.display = 'inline-flex';
        if (batchProgressBar) batchProgressBar.style.width = `${data.percent || 0}%`;
        if (batchProgressCount) batchProgressCount.textContent = `${data.current || 0} / ${data.total || 0}`;
    });

    document.addEventListener('nedotify:batch_download_finished', (e) => {
        const data = e.detail || {};
        if (batchProgressCount) batchProgressCount.textContent = `${data.completed || 0} / ${data.total || 0}`;
        if (batchProgressBar) batchProgressBar.style.width = '100%';
        setTimeout(() => {
            if (batchProgressBox) batchProgressBox.style.display = 'none';
            window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: `✅ Загрузка завершена (${data.completed || 0} треков)`, type: 'success' } }));
            loadLibrary();
        }, 1200);
    });

    document.addEventListener('nedotify:batch_download_cancelled', () => {
        if (batchProgressBox) batchProgressBox.style.display = 'none';
    });

    // Sidebar Action Buttons
    const btnImport = document.getElementById('lib-btn-import');
    if (btnImport) {
        btnImport.addEventListener('click', async () => {
            if (window.pywebview?.api?.open_local_file) {
                try {
                    const res = await window.pywebview.api.open_local_file();
                    if (res && (res.success || res.count > 0)) {
                        const count = typeof res === 'object' && res.count !== undefined ? res.count : 1;
                        window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: `Импортировано треков: ${count}`, type: 'success' } }));
                        loadLibrary();
                        refreshActiveLibraryView();
                        if (window.pywebview.api.get_storage_info) {
                            window.pywebview.api.get_storage_info();
                        }
                    }
                } catch (e) {
                    console.error('Import error:', e);
                }
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
            try {
                const res = await window.pywebview.api.import_external_playlist(url, name);
                if (res && res.success) {
                    window.dispatchEvent(new CustomEvent('nedotify:toast', { 
                        detail: { msg: `Импортирован плейлист "${res.playlist_name || res.name || 'Импортированный'}" (${res.imported_count || res.count || 0} треков)`, type: 'success' } 
                    }));
                    closeIP();
                    if (urlInput) urlInput.value = '';
                    if (nameInput) nameInput.value = '';
                    loadPlaylists();
                    refreshActiveLibraryView();
                    if (window.pywebview.api.get_storage_info) {
                        window.pywebview.api.get_storage_info();
                    }
                } else {
                    const errMsg = res?.error || 'Не удалось импортировать плейлист';
                    window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: errMsg, type: 'error' } }));
                    if (statusEl) statusEl.style.display = 'none';
                    if (submitBtn) submitBtn.disabled = false;
                }
            } catch(err) {
                window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Ошибка при импорте плейлиста', type: 'error' } }));
                if (statusEl) statusEl.style.display = 'none';
                if (submitBtn) submitBtn.disabled = false;
            }
        } else {
            closeIP();
        }
    });

    // Add playlist from sidebar input
    const addPlBtn = document.getElementById('lib-btn-add-playlist');
    const plInput = document.getElementById('lib-input-add-playlist') || document.getElementById('lib-quick-pl-input');
    const handleCreateQuick = async () => {
        const name = plInput ? plInput.value.trim() : '';
        if (!name) return;
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

    // Play all / toggle play-pause button in active view
    const playAllBtn = document.getElementById('lib-btn-play-all');
    if (playAllBtn) {
        playAllBtn.addEventListener('click', () => {
            if (!currentActiveTracks || currentActiveTracks.length === 0) return;
            const current = getCurrentTrack();
            const isPlayingFromCurrentList = current && currentActiveTracks.some(t => String(t.id) === String(current.id));

            if (isPlayingFromCurrentList && window.pywebview?.api?.play_pause) {
                window.pywebview.api.play_pause();
            } else if (window.pywebview?.api?.play_track) {
                window.pywebview.api.play_track(currentActiveTracks[0], currentActiveTracks, 0);
            } else if (window.NeDotify?.playTrack) {
                window.NeDotify.playTrack(currentActiveTracks[0], currentActiveTracks);
            }
        });
    }

    // Playlist Details view buttons
    const btnBackLib = document.getElementById('btn-back-library');
    if (btnBackLib) {
        btnBackLib.addEventListener('click', () => {
            if (window.NeDotify?.showPage) {
                window.NeDotify.showPage('library');
            } else {
                const libTab = document.querySelector('[data-page="library"]');
                if (libTab) libTab.click();
            }
        });
    }

    const plPlayBtn = document.getElementById('pl-btn-play');
    if (plPlayBtn) {
        plPlayBtn.addEventListener('click', () => {
            if (!currentActiveTracks || currentActiveTracks.length === 0) return;
            const current = getCurrentTrack();
            const isPlayingFromCurrentList = current && currentActiveTracks.some(t => String(t.id) === String(current.id));

            if (isPlayingFromCurrentList && window.pywebview?.api?.play_pause) {
                window.pywebview.api.play_pause();
            } else if (window.pywebview?.api?.play_track) {
                window.pywebview.api.play_track(currentActiveTracks[0], currentActiveTracks, 0);
            } else if (window.NeDotify?.playTrack) {
                window.NeDotify.playTrack(currentActiveTracks[0], currentActiveTracks);
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
        let localIds = new Set();
        try {
            const raw = localStorage.getItem('nedotify_favorites');
            if (raw) {
                const entries = JSON.parse(raw);
                entries.forEach(e => {
                    const id = typeof e === 'string' ? e : String((e && e.id) || (e && e.source_id) || '');
                    if (id) localIds.add(id);
                });
            }
        } catch (e) {}

        let backendFavs = [];
        if (window.pywebview?.api?.get_favorites) {
            backendFavs = await window.pywebview.api.get_favorites() || [];
        }
        if (backendFavs === null || backendFavs === undefined) backendFavs = [];

        const backendIds = new Set(backendFavs.map(bt => String(bt.id || bt.source_id || '')));
        // M-2/M-3: count = unique backend + local-only IDs (legacy sync may lag)
        const favCount = backendFavs.length + [...localIds].filter(id => id && !backendIds.has(id)).length;

        const favSub = document.getElementById('lib-fav-count');
        if (favSub) {
            favSub.textContent = favCount > 0 ? `${favCount} треков` : 'Нет треков';
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

let currentActiveSection = 'favorites';
let currentSelectedPlaylistData = null;

// O-11: generation counter — stale async renders must not overwrite newer views
let libraryGeneration = 0;

export function refreshActiveLibraryView() {
    loadLibrarySummary();
    if (currentActiveSection === 'favorites') {
        selectSection('favorites');
    } else if (currentActiveSection === 'offline') {
        selectSection('offline');
    } else if (currentActiveSection === 'playlist' && currentSelectedPlaylistData) {
        selectSection('playlist', currentSelectedPlaylistData);
    }
}
window.refreshActiveLibraryView = refreshActiveLibraryView;

// O-9: render library lists in batches (artist_profile.js pattern) instead of all at once
const LIB_BATCH_SIZE = 50;
let libraryScrollCleanup = null;

function makeLibraryBatchRenderer(container, tracks) {
    let rendered = 0;
    const renderNext = () => {
        const start = rendered;
        const end = Math.min(tracks.length, start + LIB_BATCH_SIZE);
        for (let i = start; i < end; i++) {
            container.appendChild(createTrackElement(tracks[i], i, tracks, getCurrentTrack()));
        }
        rendered = end;
        renderIcons();
        return end;
    };
    return { renderNext, getRendered: () => rendered, getTotal: () => tracks.length };
}

// O-9: load further batches when the scrollable ancestor nears its bottom
function attachLibraryScrollLoader(container, renderNext, getRendered, getTotal) {
    let node = container.parentElement;
    while (node && node !== document.body) {
        const st = getComputedStyle(node);
        if (/(auto|scroll)/.test(st.overflowY)) break;
        node = node.parentElement;
    }
    const scrollParent = node || document.scrollingElement;
    if (!scrollParent) return () => {};

    // Drain batches until content overflows the scrollport (or everything is rendered)
    let guard = 0;
    while (getRendered() < getTotal() && scrollParent.clientHeight >= scrollParent.scrollHeight && guard < 20) {
        renderNext();
        guard++;
    }

    const onScroll = () => {
        const sc = scrollParent.scrollTop + scrollParent.clientHeight;
        if (sc >= scrollParent.scrollHeight - 200 && getRendered() < getTotal()) {
            renderNext();
        }
    };
    scrollParent.addEventListener('scroll', onScroll, { passive: true });
    return () => scrollParent.removeEventListener('scroll', onScroll);
}

function renderLibraryList(tracksContainer, tracks) {
    if (libraryScrollCleanup) { libraryScrollCleanup(); libraryScrollCleanup = null; }
    tracksContainer.innerHTML = '';
    const renderer = makeLibraryBatchRenderer(tracksContainer, tracks);
    renderer.renderNext();
    libraryScrollCleanup = attachLibraryScrollLoader(tracksContainer, renderer.renderNext, renderer.getRendered, renderer.getTotal);
}

export async function selectSection(type, data = null) {
    currentActiveSection = type;
    if (data) currentSelectedPlaylistData = data;

    // O-11: bump generation — any in-flight render from an older selection is discarded
    const viewGen = ++libraryGeneration;

    const emptyEl = document.getElementById('lib-empty-selection');
    const activeView = document.getElementById('lib-active-view');
    const titleEl = document.getElementById('lib-active-title');
    const subEl = document.getElementById('lib-active-sub');
    const tracksContainer = document.getElementById('lib-active-tracks');

    if (!activeView || !tracksContainer) return;

    if (emptyEl) emptyEl.style.display = 'none';
    activeView.style.display = 'block';
    tracksContainer.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';

    const btnDownloadAll = document.getElementById('lib-btn-download-all');
    if (btnDownloadAll) {
        btnDownloadAll.style.display = type === 'favorites' ? 'inline-flex' : 'none';
    }

    // Reset active highlights
    document.querySelectorAll('.lib-top-card').forEach(c => c.classList.remove('active'));
    document.querySelectorAll('.lib-playlist-item').forEach(i => i.classList.remove('active'));

    if (type === 'favorites') {
        const favCard = document.getElementById('lib-card-favorites');
        if (favCard) favCard.classList.add('active');
        if (titleEl) titleEl.textContent = 'Любимые треки';

        // M-2: localStorage holds IDs only (full objects live in the backend DB)
        const localIds = new Set();
        try {
            const raw = localStorage.getItem('nedotify_favorites');
            if (raw) {
                JSON.parse(raw).forEach(e => {
                    const id = typeof e === 'string' ? e : String((e && e.id) || (e && e.source_id) || '');
                    if (id) localIds.add(id);
                });
            }
        } catch (e) {}

        let backendFavs = [];
        try {
            if (window.pywebview?.api?.get_favorites) {
                backendFavs = await window.pywebview.api.get_favorites() || [];
            }
        } catch (e) {
            console.error('get_favorites failed:', e);
            backendFavs = [];
        }

        // M-10: never leave the spinner hanging — show a message on failure
        if (backendFavs === null || backendFavs === undefined) backendFavs = [];
        if (viewGen !== libraryGeneration) return;

        // M-3: O(n) dedup via Set
        const seen = new Set();
        const combined = backendFavs.filter(bt => {
            const bId = String(bt.id || bt.source_id || '');
            if (!bId || seen.has(bId)) return false;
            seen.add(bId);
            return true;
        });
        // local-only IDs (not yet synced) still count
        const totalFavs = combined.length + [...localIds].filter(id => id && !seen.has(id)).length;

        currentActiveTracks = combined;
        if (subEl) subEl.textContent = `${totalFavs} треков`;

        if (combined.length === 0) {
            tracksContainer.innerHTML = '<div class="empty-state">Нет любимых треков</div>';
            return;
        }

        renderLibraryList(tracksContainer, combined);

    } else if (type === 'offline') {
        const offCard = document.getElementById('lib-card-offline');
        if (offCard) offCard.classList.add('active');
        if (titleEl) titleEl.textContent = 'Оффлайн треки';

        let downloaded = [];
        try {
            if (window.pywebview?.api?.get_downloaded_tracks) {
                downloaded = await window.pywebview.api.get_downloaded_tracks() || [];
            }
        } catch (e) {
            console.error('get_downloaded_tracks failed:', e);
            downloaded = [];
        }
        if (viewGen !== libraryGeneration) return;

        // Deduplicate tracks by id / source_id
        const seen = new Set();
        const uniqueDownloaded = [];
        downloaded.forEach(t => {
            const key = String(t.id || t.source_id || `${(t.title || '').toLowerCase().trim()}___${(t.artist || '').toLowerCase().trim()}`);
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

        renderLibraryList(tracksContainer, downloaded);

    } else if (type === 'playlist' && data) {
        if (titleEl) titleEl.textContent = data.name || 'Плейлист';

        let tracks = [];
        try {
            if (window.pywebview?.api?.get_playlist_tracks) {
                tracks = await window.pywebview.api.get_playlist_tracks(data.id) || [];
            }
        } catch (e) {
            console.error('get_playlist_tracks failed:', e);
            tracks = [];
        }
        if (viewGen !== libraryGeneration) return;

        // Deduplicate tracks by id / source_id
        const seen = new Set();
        const uniqueTracks = [];
        tracks.forEach(t => {
            const key = String(t.id || t.source_id || `${(t.title || '').toLowerCase().trim()}___${(t.artist || '').toLowerCase().trim()}`);
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

        renderLibraryList(tracksContainer, tracks);
    }
}

export async function loadDownloaded() {
    refreshActiveLibraryView();
}

// ─── Playlist Order (persisted in localStorage) ───
function getPlaylistOrder() {
    try { return JSON.parse(localStorage.getItem('nedotify_playlist_order') || 'null'); } catch { return null; }
}
function savePlaylistOrder(ids) {
    localStorage.setItem('nedotify_playlist_order', JSON.stringify(ids));
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

        // Apply saved order (only for non-locked playlists)
        const locked = playlists.filter(p => p.name === 'Скачанное');
        const movable = playlists.filter(p => p.name !== 'Скачанное');
        const savedOrder = getPlaylistOrder();
        let ordered = movable;
        if (savedOrder) {
            const byId = Object.fromEntries(movable.map(p => [String(p.id ?? p.ID), p]));
            const sorted = savedOrder.map(id => byId[String(id)]).filter(Boolean);
            const unseen = movable.filter(p => !savedOrder.includes(String(p.id ?? p.ID)) && !savedOrder.includes(p.id ?? p.ID));
            ordered = [...sorted, ...unseen];
        }
        const sortedPlaylists = [...locked, ...ordered];

        sidebarList.innerHTML = '';

        sortedPlaylists.forEach(pl => {
            const id = pl.id !== undefined ? pl.id : pl.ID;
            const item = document.createElement('div');
            item.className = 'lib-playlist-item';
            item.setAttribute('data-pl-id', id);

            const isLocked = pl.name === 'Скачанное';
            const iconName = isLocked ? 'download' : 'music';
            const iconColor = isLocked ? 'var(--primary)' : 'var(--text-sec)';

            item.innerHTML = `
                ${!isLocked ? `<span class="pl-drag-handle" title="Зажми для перемещения"><i data-lucide="grip-vertical" style="width:13px;height:13px;color:var(--primary);flex-shrink:0;cursor:grab;"></i></span>` : '<span style="width:13px;flex-shrink:0;"></span>'}
                <i data-lucide="${iconName}" style="width:14px;height:14px;color:${iconColor};flex-shrink:0;"></i>
                <span class="truncate" style="${isLocked ? 'font-weight:600;' : ''}">${escapeHtml(pl.name)}</span>
                ${!isLocked ? `<button class="btn-del-pl" title="Удалить плейлист" style="margin-left:auto; background:none; border:none; color:var(--text-dim); cursor:pointer; padding:2px; opacity:0; transition:opacity 0.18s;"><i data-lucide="trash-2" style="width:12px;height:12px;"></i></button>` : ''}
            `;

            item.addEventListener('click', (e) => {
                if (e.target.closest('.btn-del-pl') || e.target.closest('.pl-drag-handle')) return;
                document.querySelectorAll('.lib-playlist-item').forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                selectSection('playlist', { id, name: pl.name });
            });

            const delBtn = item.querySelector('.btn-del-pl');

            if (delBtn) {
                item.addEventListener('mouseenter', () => {
                    delBtn.style.opacity = '1';
                });
                item.addEventListener('mouseleave', () => {
                    delBtn.style.opacity = '0';
                });
                delBtn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const confirmed = await showDeletePlaylistModal(pl.name);
                    if (confirmed) {
                        if (window.pywebview?.api?.delete_playlist) {
                            // Animate out
                            item.style.transition = 'transform 0.25s ease, opacity 0.25s ease, max-height 0.3s ease';
                            item.style.opacity = '0';
                            item.style.transform = 'translateX(-20px)';
                            item.style.maxHeight = item.offsetHeight + 'px';
                            setTimeout(() => {
                                item.style.maxHeight = '0';
                                item.style.marginBottom = '0';
                                item.style.overflow = 'hidden';
                            }, 50);
                            setTimeout(async () => {
                                await window.pywebview.api.delete_playlist(id);
                                window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: `Плейлист "${pl.name}" удалён`, type: 'info' } }));
                                if (currentSelectedPlaylistData?.id === id) {
                                    selectSection('favorites');
                                }
                                loadPlaylists();
                            }, 320);
                        }
                    }
                });
            }

            if (!isLocked) {
                setupPlaylistDrag(item, sidebarList);
            }

            sidebarList.appendChild(item);
        });

        renderIcons();

        // Animate items in
        const items = sidebarList.querySelectorAll('.lib-playlist-item');
        items.forEach((el, i) => {
            el.style.opacity = '0';
            el.style.transform = 'translateX(-12px)';
            el.style.transition = 'none';
            requestAnimationFrame(() => {
                setTimeout(() => {
                    el.style.transition = 'opacity 0.22s ease, transform 0.22s ease';
                    el.style.opacity = '1';
                    el.style.transform = 'translateX(0)';
                }, i * 40);
            });
        });

    } catch (e) {
        console.error("Load playlists error:", e);
    }
}

// ─── Custom Delete Playlist Modal ───
function showDeletePlaylistModal(playlistName) {
    return new Promise((resolve) => {
        const modal = document.getElementById('modal-delete-playlist');
        const nameEl = document.getElementById('modal-dpl-name');
        const btnConfirm = document.getElementById('modal-dpl-confirm');
        const btnCancel = document.getElementById('modal-dpl-cancel');
        if (!modal) { resolve(window.confirm(`Удалить плейлист "${playlistName}"?`)); return; }

        nameEl.textContent = `«${playlistName}» будет удалён без возможности восстановления.`;

        // Animate in
        const card = modal.querySelector('.glass-modal-card');
        modal.style.display = 'flex';
        if (card) {
            card.style.transform = 'scale(0.9)';
            card.style.opacity = '0';
            card.style.transition = 'none';
            requestAnimationFrame(() => {
                card.style.transition = 'transform 0.22s cubic-bezier(0.16,1,0.3,1), opacity 0.22s ease';
                card.style.transform = 'scale(1)';
                card.style.opacity = '1';
            });
        }

        // Re-render icons inside modal
        if (window.lucide) setTimeout(() => window.lucide.createIcons(), 10);

        const close = (result) => {
            if (card) {
                card.style.transition = 'transform 0.18s ease, opacity 0.18s ease';
                card.style.transform = 'scale(0.92)';
                card.style.opacity = '0';
            }
            setTimeout(() => {
                modal.style.display = 'none';
                if (card) { card.style.transform = ''; card.style.opacity = ''; }
            }, 180);
            btnConfirm.removeEventListener('click', onConfirm);
            btnCancel.removeEventListener('click', onCancel);
            modal.removeEventListener('click', onOverlay);
            resolve(result);
        };

        const onConfirm = () => close(true);
        const onCancel = () => close(false);
        const onOverlay = (e) => { if (e.target === modal) close(false); };

        btnConfirm.addEventListener('click', onConfirm);
        btnCancel.addEventListener('click', onCancel);
        modal.addEventListener('click', onOverlay);
    });
}

// ─── Drag-and-Drop Logic ───
function setupPlaylistDrag(item, list) {
    const handle = item.querySelector('.pl-drag-handle');
    if (!handle) return;

    let dragGhost = null;
    let startY = 0;
    let origIndex = 0;
    let isDragging = false;
    let placeholder = null;

    const onPointerDown = (e) => {
        if (e.button !== 0) return;
        e.preventDefault();

        startY = e.clientY;
        origIndex = [...list.children].indexOf(item);
        isDragging = false;

        const onPointerMove = (e2) => {
            const dy = Math.abs(e2.clientY - startY);
            if (!isDragging && dy > 6) {
                isDragging = true;
                startDrag(item, list, e2.clientY);
            }
            if (isDragging) {
                moveDrag(e2.clientY, list, item);
            }
        };

        const onPointerUp = () => {
            document.removeEventListener('pointermove', onPointerMove);
            document.removeEventListener('pointerup', onPointerUp);
            if (isDragging) endDrag(item, list);
        };

        document.addEventListener('pointermove', onPointerMove);
        document.addEventListener('pointerup', onPointerUp);
    };

    handle.addEventListener('pointerdown', onPointerDown);
}

let _dragGhost = null;
let _placeholder = null;
let _dragOffsetY = 0;

function startDrag(item, list, clientY) {
    const rect = item.getBoundingClientRect();
    _dragOffsetY = clientY - rect.top;

    // Placeholder
    _placeholder = document.createElement('div');
    _placeholder.className = 'pl-drag-placeholder';
    _placeholder.style.height = rect.height + 'px';
    _placeholder.style.transition = 'none';
    list.insertBefore(_placeholder, item);

    // Ghost
    _dragGhost = item.cloneNode(true);
    _dragGhost.className = 'lib-playlist-item pl-drag-ghost';
    _dragGhost.style.cssText = `
        position:fixed; left:${rect.left}px; top:${rect.top}px;
        width:${rect.width}px; z-index:9999; pointer-events:none;
        box-shadow:0 8px 32px rgba(0,0,0,0.55); opacity:0.95;
        transform:scale(1.03); border-radius:10px;
        background:var(--bg-card); transition:box-shadow 0.15s;
    `;
    document.body.appendChild(_dragGhost);

    item.classList.add('pl-dragging');
    document.body.style.userSelect = 'none';
}

function moveDrag(clientY, list, item) {
    if (!_dragGhost || !_placeholder) return;

    _dragGhost.style.top = (clientY - _dragOffsetY) + 'px';

    const items = [...list.querySelectorAll('.lib-playlist-item:not(.pl-dragging)')];
    let insertBefore = null;

    for (const el of items) {
        const elRect = el.getBoundingClientRect();
        if (clientY < elRect.top + elRect.height / 2) {
            insertBefore = el;
            break;
        }
    }

    if (insertBefore) {
        if (_placeholder.nextSibling !== insertBefore) {
            list.insertBefore(_placeholder, insertBefore);
        }
    } else {
        if (list.lastChild !== _placeholder) {
            list.appendChild(_placeholder);
        }
    }
}

function endDrag(item, list) {
    if (!_dragGhost || !_placeholder) return;

    // Animate ghost into placeholder position
    const targetRect = _placeholder.getBoundingClientRect();
    _dragGhost.style.transition = 'top 0.18s cubic-bezier(0.16,1,0.3,1), left 0.18s cubic-bezier(0.16,1,0.3,1), transform 0.18s, opacity 0.18s';
    _dragGhost.style.top = targetRect.top + 'px';
    _dragGhost.style.left = targetRect.left + 'px';
    _dragGhost.style.transform = 'scale(1)';
    _dragGhost.style.opacity = '0';

    setTimeout(() => {
        list.insertBefore(item, _placeholder);
        _placeholder.remove();
        _dragGhost.remove();
        item.classList.remove('pl-dragging');
        document.body.style.userSelect = '';
        _dragGhost = null;
        _placeholder = null;

        // Persist new order (only draggable items, skip locked)
        const allItems = [...list.querySelectorAll('.lib-playlist-item')];
        const ids = allItems
            .filter(el => el.querySelector('.pl-drag-handle'))
            .map(el => el.getAttribute('data-pl-id'));
        savePlaylistOrder(ids);

        // Flash item
        item.style.transition = 'background 0.3s';
        item.style.background = 'rgba(var(--primary-rgb, 59,130,246), 0.15)';
        setTimeout(() => { item.style.background = ''; }, 400);
    }, 200);
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
                btn.innerHTML = `<i data-lucide="list-music" style="width:14px;height:14px;color:var(--text-sec)"></i> ${escapeHtml(pl.name)}`;
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



