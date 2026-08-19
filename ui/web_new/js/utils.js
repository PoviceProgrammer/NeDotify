// NeDotify — Utilities Module

export const HIDDEN_SOURCES = new Set(['yandex', 'vk', 'vkontakte', 'zeno']);

export function isHiddenSource(source) {
    return HIDDEN_SOURCES.has(String(source || '').toLowerCase());
}

export function filterVisibleTracks(tracks) {
    return (Array.isArray(tracks) ? tracks : []).filter(track => {
        if (!track) return false;
        if (!isHiddenSource(track.source)) return true;
        return Boolean(track.is_downloaded && track.file_path);
    });
}

export function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

export function formatTime(seconds) {
    if (!seconds || seconds <= 0) return "0:00";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s < 10 ? '0' : ''}${s}`;
}

// M-9: single implementation (was duplicated in main.js where the import failed silently)
export function formatListeningTimeShort(ms) {
    if (!ms || ms <= 0) return '0 ч';
    const hours = Math.floor(ms / (1000 * 3600));
    if (hours > 0) return `${hours} ч`;
    const minutes = Math.floor(ms / (1000 * 60));
    return `${minutes} мин`;
}

export function formatListeningTime(ms) {
    if (!ms || ms <= 0) return "0 мин";
    const totalSeconds = Math.floor(ms / 1000);
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    let parts = [];
    if (days > 0) parts.push(`${days} д`);
    if (hours > 0) parts.push(`${hours} ч`);
    if (minutes > 0 || parts.length === 0) parts.push(`${minutes} мин`);
    return parts.join(' ');
}

export function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

export function extractDominantColor(imgEl) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;

    // M-11: sample a small downscaled copy instead of full-size getImageData
    canvas.width = 50;
    canvas.height = 50;

    try {
        ctx.drawImage(imgEl, 0, 0, canvas.width, canvas.height);
        const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
        let r = 0, g = 0, b = 0, count = 0;
        for (let i = 0; i < data.length; i += 4 * 10) { // step by 10 pixels to speed up
            if (data[i+3] > 128) { // ignore transparent pixels
                r += data[i];
                g += data[i+1];
                b += data[i+2];
                count++;
            }
        }
        if (count === 0) return null;
        r = Math.floor(r / count);
        g = Math.floor(g / count);
        b = Math.floor(b / count);
        return {r, g, b};
    } catch (e) {
        console.warn('Canvas color extraction failed (CORS?):', e);
        return null;
    }
}

export function handleImageError(img, coverUrl, sourceId, source) {
    if (img.dataset.failed) {
        img.style.display = 'none';
        return;
    }
    img.dataset.failed = 'true';
    if (coverUrl && coverUrl.startsWith('http')) {
        img.src = coverUrl;
    } else if (sourceId && source === 'youtube') {
        img.src = `https://img.youtube.com/vi/${sourceId}/hqdefault.jpg`;
    } else {
        img.style.display = 'none';
    }
}

// Builds a safe <img> tag: escaped src + data-attributes instead of inline onerror.
// The delegated error listener below handles image fallback (coverUrl/sourceId/source).
export function coverImgHtml({ src, coverUrl, sourceId, source, alt = '', extraAttrs = '' }) {
    let dataAttrs = '';
    if (coverUrl) dataAttrs += ` data-cover-url="${escapeHtml(coverUrl)}"`;
    if (sourceId) dataAttrs += ` data-source-id="${escapeHtml(sourceId)}"`;
    if (source) dataAttrs += ` data-source="${escapeHtml(source)}"`;
    return `<img src="${escapeHtml(src || '')}" alt="${escapeHtml(alt)}"${dataAttrs} loading="lazy"${extraAttrs ? ' ' + extraAttrs : ''}>`;
}

// 'error' does not bubble, but is caught on document in the capture phase.
document.addEventListener('error', (e) => {
    const target = e.target;
    if (!target || target.tagName !== 'IMG' || !target.dataset.coverUrl) return;
    handleImageError(target, target.dataset.coverUrl, target.dataset.sourceId || '', target.dataset.source || '');
}, true);

export function getCoverUrl(track) {
    if (!track) return '';
    if (track.cover_path) {
        const path = track.cover_path.replace(/\\/g, '/');
        const idx = path.indexOf('web_new/covers/');
        if (idx !== -1) {
            return './covers/' + path.substring(idx + 15);
        }
        const idxWeb = path.indexOf('ui/web/covers/');
        if (idxWeb !== -1) {
            return './covers/' + path.substring(idxWeb + 14);
        }
        return 'file:///' + path;
    }
    let url = track.cover_url || track.og_image || track.artwork_url || '';
    if (url && url.includes('%%')) {
        url = url.replace('%%', '400x400');
    }
    if (url && url.includes('yandex.net') && !url.includes('400x400') && !url.includes('200x200')) {
        url = url.replace(/\/([0-9]+x[0-9]+)?$/, '/400x400');
    }
    if (url && !url.startsWith('http') && !url.startsWith('file:///') && !url.startsWith('./') && !url.startsWith('data:')) {
        url = 'https://' + url;
    }
    return url;
}

export function createTrackElement(track, index, tracksArray, currentTrack) {
    const item = document.createElement('div');
    const isCurrentlyPlaying = currentTrack && ((currentTrack.id && track.id && currentTrack.id === track.id) || currentTrack.source_id === track.source_id);
    item.className = `track-item${isCurrentlyPlaying ? ' playing' : ''}`;
    item.style.animationDelay = `${Math.min(index * 0.03, 0.5)}s`;
    item.dataset.trackSourceId = String(track.source_id || track.id || '');

    const coverSrc = getCoverUrl(track);
    const isFav = track.is_favorite;
    const title = track.title || 'Unknown';
    let hash = 0;
    for (let i = 0; i < title.length; i++) {
        hash = ((hash << 5) - hash) + title.charCodeAt(i);
        hash |= 0;
    }
    const gradientColors = [
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
    const grad = gradientColors[Math.abs(hash) % gradientColors.length];

    item.innerHTML = `
        <div class="track-cover-wrap fallback-gradient" style="background: ${grad}">
            <svg class="fallback-note-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:40%;height:40%;opacity:0.6;position:relative;z-index:1;"><path d="M9 18V5l12-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="18" cy="16" r="3"></circle></svg>
            ${coverSrc ? `<img src="${escapeHtml(coverSrc)}" alt="" onerror="this.onerror=null;this.style.display='none';" loading="lazy">` : ''}
            <div class="track-cover-overlay">
                <i data-lucide="play" style="width:16px;height:16px;color:white"></i>
            </div>
            ${track.source && !isHiddenSource(track.source) ? `<div class="source-badge source-${escapeHtml(track.source)}" title="${escapeHtml(track.source)}">${getSourceIcon(track.source)}</div>` : ''}
        </div>
        <div class="track-info">
            <div class="track-title">${escapeHtml(track.title || 'Unknown')}</div>
            <div class="track-artist clickable-artist">${escapeHtml(track.artist || 'Unknown')}</div>
        </div>
        <div class="track-actions">
            <button class="icon-btn download-btn ${track.is_downloaded || track.source === 'local' ? 'downloaded' : ''}" title="${track.is_downloaded || track.source === 'local' ? 'Скачан' : 'Скачать'}">
                <i data-lucide="${track.is_downloaded || track.source === 'local' ? 'check' : 'download'}" style="width:14px;height:14px"></i>
            </button>
            <button class="icon-btn like-btn ${isFav ? 'liked' : ''}" title="Нравится">
                <i data-lucide="heart" style="width:14px;height:14px;${isFav ? 'fill:currentColor' : ''}"></i>
            </button>
            <button class="icon-btn add-btn" title="Добавить в плейлист">
                <i data-lucide="plus" style="width:14px;height:14px"></i>
            </button>
        </div>
        <div class="track-duration-container">
            <span class="track-duration">${formatTime(track.duration)}</span>
            <button class="icon-btn track-more-btn" title="Опции">
                <i data-lucide="more-horizontal" style="width:16px;height:16px"></i>
            </button>
        </div>
    `;

    // Play handler: Entire track row clickable except action buttons, more button and artist link
    item.addEventListener('click', (e) => {
        if (e.target.closest('.like-btn') || e.target.closest('.add-btn') || e.target.closest('.download-btn') || e.target.closest('.track-more-btn') || e.target.closest('.clickable-artist')) {
            return;
        }
        if (window.pywebview && window.pywebview.api) {
            window.pywebview.api.play_track(track, tracksArray, index);
        }
    });

    // Download handler: show spinning animation, trigger download, update state on completion
    const downloadBtn = item.querySelector('.download-btn');
    if (downloadBtn) {
        downloadBtn.addEventListener('click', async (e) => {
            e.stopPropagation();
            e.preventDefault();
            if (downloadBtn.classList.contains('downloaded') || downloadBtn.classList.contains('downloading')) {
                return;
            }
            downloadBtn.classList.add('downloading');
            downloadBtn.innerHTML = '<i data-lucide="loader-2" class="spin-icon" style="width:14px;height:14px"></i>';
            renderIcons(item);
            showToast(`Скачивание '${track.title || 'трека'}'...`, 'info');

            if (window.NeDotify?.downloadTrack) {
                window.NeDotify.downloadTrack(track);
            } else if (window.pywebview?.api?.download_track) {
                try {
                    await window.pywebview.api.download_track(track);
                } catch(err) {
                    downloadBtn.classList.remove('downloading');
                    downloadBtn.innerHTML = '<i data-lucide="download" style="width:14px;height:14px"></i>';
                    renderIcons(item);
                    showToast('Ошибка скачивания', 'error');
                }
            }
        });
    }

    // Artist click navigation handler: ONLY fires on artist text
    const artistEl = item.querySelector('.track-artist');
    if (artistEl && track.artist && track.artist !== 'Unknown') {
        artistEl.addEventListener('click', (e) => {
            e.stopPropagation();
            e.preventDefault();
            if (window.searchArtistProfile) {
                window.searchArtistProfile(track.artist);
            }
        });
    }

    // Like handler: Instant UI toggle + localStorage persistence + pywebview API
    const likeBtn = item.querySelector('.like-btn');
    if (likeBtn) {
        likeBtn.addEventListener('click', async (e) => {
            e.stopPropagation();
            e.preventDefault();
            track.is_favorite = !track.is_favorite;
            likeBtn.classList.toggle('liked', track.is_favorite);
            const icon = likeBtn.querySelector('i');
            if (icon) {
                icon.style.fill = track.is_favorite ? 'currentColor' : 'none';
            }

            // Sync with localStorage (M-2: store IDs only, not full track objects)
            try {
                let favs = JSON.parse(localStorage.getItem('nedotify_favorites') || '[]');
                const tId = String(track.id || track.source_id || '');
                const matches = (f) => {
                    if (typeof f === 'string') return f === tId;
                    return String((f && f.id) || (f && f.source_id) || '') === tId;
                };
                if (track.is_favorite) {
                    if (tId && !favs.some(matches)) {
                        favs.push(tId);
                    }
                } else {
                    favs = favs.filter(f => !matches(f));
                }
                localStorage.setItem('nedotify_favorites', JSON.stringify(favs));
            } catch (err) {}

            if (window.pywebview?.api?.toggle_favorite) {
                try {
                    await window.pywebview.api.toggle_favorite(track);
                } catch (err) {}
            }
        });
    }

    // Add to playlist handler
    const addBtn = item.querySelector('.add-btn');
    if (addBtn) {
        addBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            e.preventDefault();
            if (window.NeDotify && window.NeDotify.openPlaylistMenu) {
                window.NeDotify.openPlaylistMenu(track, e.clientX, e.clientY);
            }
        });
    }

    // Three horizontal dots button click handler (Screenshot 1 menu)
    const moreBtn = item.querySelector('.track-more-btn');
    if (moreBtn) {
        moreBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            e.preventDefault();
            showTrackContextMenu(track, e, tracksArray, index);
        });
    }

    // Right-click context menu handler on track item
    item.addEventListener('contextmenu', (e) => {
        e.stopPropagation();
        e.preventDefault();
        showTrackContextMenu(track, e, tracksArray, index);
    });

    return item;
}

// M-2: warn when localStorage usage exceeds ~4MB (silent quota errors are the symptom)
export function checkLocalStorageQuota(warnThresholdBytes = 4 * 1024 * 1024) {
    try {
        let total = 0;
        for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i);
            if (k === null) continue;
            const v = localStorage.getItem(k);
            total += k.length + (v ? v.length : 0);
        }
        if (total > warnThresholdBytes) {
            console.warn(`[storage] localStorage usage ${(total / 1024 / 1024).toFixed(1)}MB exceeds ${(warnThresholdBytes / 1024 / 1024)}MB — clean up custom backgrounds or large cached data`);
        }
        return total;
    } catch (e) {
        return 0;
    }
}

// M-2: downscale a base64 image to max 256px JPEG before persisting (backgrounds)
export function compressBackgroundImage(dataUrl, callback) {
    if (!dataUrl || !dataUrl.startsWith('data:image')) {
        callback(dataUrl);
        return;
    }
    try {
        const img = new Image();
        img.onload = () => {
            try {
                const MAX = 256;
                const scale = Math.min(1, MAX / Math.max(img.width, img.height));
                const w = Math.max(1, Math.round(img.width * scale));
                const h = Math.max(1, Math.round(img.height * scale));
                const canvas = document.createElement('canvas');
                canvas.width = w;
                canvas.height = h;
                const ctx = canvas.getContext('2d');
                if (!ctx) { callback(dataUrl); return; }
                ctx.drawImage(img, 0, 0, w, h);
                callback(canvas.toDataURL('image/jpeg', 0.8));
            } catch (err) {
                callback(dataUrl);
            }
        };
        img.onerror = () => callback(dataUrl);
        img.src = dataUrl;
    } catch (err) {
        callback(dataUrl);
    }
}

export function renderIcons(targetEl) {
    if (window.lucide) {
        if (targetEl && (targetEl.nodeType === 1 || targetEl.nodeType === 9)) {
            try {
                window.lucide.createIcons({
                    nameAttr: 'data-lucide',
                    attrs: {},
                    root: targetEl
                });
            } catch(e) {
                window.lucide.createIcons();
            }
        } else {
            window.lucide.createIcons();
        }
    }
}

function getSourceIcon(source) {
    if (isHiddenSource(source)) return '';
    switch (source) {
        case 'youtube': return '<i data-lucide="youtube" style="width:12px;height:12px"></i>';
        case 'soundcloud': return '<i data-lucide="cloud" style="width:12px;height:12px"></i>';
        case 'local': return '<i data-lucide="folder" style="width:12px;height:12px"></i>';
        default: return '';
    }
}

document.addEventListener('nedotify:track_downloaded', (e) => {
    const data = e.detail;
    if (!data) return;
    const targetId = String(data.track_id || data.source_id || '');
    document.querySelectorAll('.track-item').forEach(el => {
        if (el.dataset.trackSourceId && targetId && el.dataset.trackSourceId.includes(targetId)) {
            const btn = el.querySelector('.download-btn');
            if (btn) {
                btn.classList.remove('downloading');
                btn.classList.add('downloaded');
                btn.title = 'Скачан';
                btn.innerHTML = '<i data-lucide="check" style="width:14px;height:14px"></i>';
            }
        }
    });
    renderIcons();
});

let activeRichMenu = null;

export function showTrackContextMenu(track, e, tracksArray, index) {
    if (e) {
        e.preventDefault();
        e.stopPropagation();
    }

    if (activeRichMenu) {
        activeRichMenu.remove();
        activeRichMenu = null;
    }

    const menu = document.createElement('div');
    menu.className = 'rich-track-menu visible';

    const coverUrl = getCoverUrl(track);
    const isFav = !!track.is_favorite;

    menu.innerHTML = `
        <div class="rich-menu-header">
            ${coverUrl ? `<div class="rich-menu-header-bg" style="background-image: url('${escapeHtml(coverUrl)}')"></div>` : ''}
            <img class="rich-menu-cover" src="${escapeHtml(coverUrl || './assets/default_cover.png')}" onerror="this.style.opacity='0.4'">
            <div class="rich-menu-title-col">
                <div class="rich-menu-title-row">
                    <span class="rich-menu-title">${escapeHtml(track.title || 'Неизвестный трек')}</span>
                    <i data-lucide="info" class="rich-menu-info-icon" style="width:15px;height:15px"></i>
                </div>
                <div class="rich-menu-artist">${escapeHtml(track.artist || 'Неизвестный исполнитель')}</div>
            </div>
        </div>

        <button class="rich-menu-item" data-action="play_next">
            <i data-lucide="play-circle" style="width:16px;height:16px"></i>
            <span>Следующим</span>
        </button>
        <button class="rich-menu-item" data-action="add_queue">
            <i data-lucide="list-plus" style="width:16px;height:16px"></i>
            <span>Добавить в очередь</span>
        </button>
        <button class="rich-menu-item" data-action="wave">
            <i data-lucide="radio" style="width:16px;height:16px"></i>
            <span>Волна по треку</span>
        </button>

        <div class="rich-menu-divider"></div>

        <button class="rich-menu-item ${isFav ? 'red-action' : ''}" data-action="favorite">
            <i data-lucide="heart" style="width:16px;height:16px;${isFav ? 'fill:currentColor' : ''}"></i>
            <span>${isFav ? 'Удалить из избранного' : 'Добавить в избранное'}</span>
        </button>
        <button class="rich-menu-item orange-action" data-action="dislike">
            <i data-lucide="thumbs-down" style="width:16px;height:16px"></i>
            <span>Убрать из «Не интересно»</span>
        </button>

        <div class="rich-menu-divider"></div>

        <button class="rich-menu-item" data-action="share">
            <i data-lucide="share-2" style="width:16px;height:16px"></i>
            <span>Поделиться</span>
        </button>

        <div class="rich-menu-divider"></div>

        <button class="rich-menu-item" data-action="download">
            <i data-lucide="download" style="width:16px;height:16px"></i>
            <span>Скачать</span>
        </button>
        <button class="rich-menu-item" data-action="cache">
            <i data-lucide="hard-drive" style="width:16px;height:16px"></i>
            <span>Кешировать</span>
        </button>

        <div class="rich-menu-divider"></div>

        <button class="rich-menu-item" data-action="pin">
            <i data-lucide="pin" style="width:16px;height:16px"></i>
            <span>Закрепить в профиле</span>
        </button>

        <button class="rich-menu-item" data-action="edit_tags">
            <i data-lucide="edit-3" style="width:16px;height:16px"></i>
            <span>Редактировать теги</span>
        </button>

        <div class="rich-menu-divider"></div>

        <button class="rich-menu-item red-action" data-action="remove_queue">
            <i data-lucide="minus-circle" style="width:16px;height:16px"></i>
            <span>Удалить из очереди</span>
        </button>
    `;

    document.body.appendChild(menu);
    activeRichMenu = menu;
    renderIcons();

    // Calculate position relative to mouse or button
    const menuWidth = 270;
    const menuHeight = menu.offsetHeight || 420;
    let clickX = e ? e.clientX : window.innerWidth / 2;
    let clickY = e ? e.clientY : window.innerHeight / 2;

    if (clickX + menuWidth > window.innerWidth - 10) {
        clickX = window.innerWidth - menuWidth - 14;
    }
    if (clickY + menuHeight > window.innerHeight - 10) {
        clickY = window.innerHeight - menuHeight - 14;
    }
    if (clickY < 10) clickY = 10;
    if (clickX < 10) clickX = 10;

    menu.style.left = `${clickX}px`;
    menu.style.top = `${clickY}px`;

    // Click Actions
    menu.addEventListener('click', (evt) => {
        const itemBtn = evt.target.closest('.rich-menu-item');
        const infoIcon = evt.target.closest('.rich-menu-info-icon');

        if (infoIcon) {
            evt.stopPropagation();
            showToast(`Трек: ${track.title || ''} • ${track.artist || ''}`, 'info');
            closeMenu();
            return;
        }

        if (!itemBtn) return;
        evt.stopPropagation();
        const action = itemBtn.dataset.action;

        switch(action) {
            case 'play_next':
                if (window.NeDotify?.playNext) {
                    window.NeDotify.playNext(track);
                }
                showToast(`'${track.title || 'Трек'}' будет сыгран следующим`, 'success');
                break;
            case 'add_queue':
                if (window.NeDotify?.addToQueue) {
                    window.NeDotify.addToQueue(track);
                }
                showToast(`'${track.title || 'Трек'}' добавлен в очередь`, 'success');
                break;
            case 'wave':
                if (window.NeDotify?.startTrackWave) {
                    window.NeDotify.startTrackWave(track);
                } else {
                    showToast(`📻 Запуск радио по треку '${track.title || ''}'...`, 'info');
                }
                break;
            case 'favorite':
                track.is_favorite = !track.is_favorite;
                if (window.pywebview?.api?.toggle_favorite) {
                    window.pywebview.api.toggle_favorite(track);
                }
                showToast(track.is_favorite ? 'Добавлено в избранное!' : 'Удалено из избранного', 'info');
                break;
            case 'dislike':
                showToast(`Функция пока недоступна (Не интересно)`, 'info');
                break;
            case 'share':
                const shareStr = `${track.title || ''} - ${track.artist || ''}`;
                if (navigator.clipboard) {
                    navigator.clipboard.writeText(shareStr);
                }
                showToast('Ссылка скопирована в буфер!', 'success');
                break;
            case 'download':
                if (window.NeDotify?.downloadTrack) {
                    window.NeDotify.downloadTrack(track);
                } else if (window.pywebview?.api?.download_track) {
                    window.pywebview.api.download_track(track);
                }
                showToast(`Загрузка '${track.title || ''}' начата`, 'info');
                break;
            case 'cache':
                showToast(`Функция пока недоступна (Кэшировать)`, 'info');
                break;
            case 'pin':
                if (window.pywebview?.api?.save_setting) {
                    window.pywebview.api.save_setting('pinned_track', track, 'profile');
                }
                showToast(`'${track.title || ''}' закреплен в профиле!`, 'success');
                break;
            case 'edit_tags':
                openEditTagsModal(track);
                break;
            case 'remove_queue':
                (async () => {
                    let removeIndex = index;
                    if (removeIndex === undefined || removeIndex === null || removeIndex < 0) {
                        if (tracksArray && Array.isArray(tracksArray)) {
                            removeIndex = tracksArray.indexOf(track);
                        }
                    }
                    if (removeIndex === undefined || removeIndex === null || removeIndex < 0) {
                        try {
                            if (window.pywebview?.api?.get_queue) {
                                const q = await window.pywebview.api.get_queue();
                                if (q && q.tracks) {
                                    removeIndex = q.tracks.findIndex(t => 
                                        (t.id && track.id && String(t.id) === String(track.id)) ||
                                        (t.source_id && track.source_id && String(t.source_id) === String(track.source_id)) ||
                                        (t.title === track.title && t.artist === track.artist)
                                    );
                                }
                            }
                        } catch (qe) {}
                    }
                    if (window.pywebview?.api?.remove_from_queue && removeIndex !== undefined && removeIndex !== null && removeIndex >= 0) {
                        try {
                            const res = await window.pywebview.api.remove_from_queue(removeIndex);
                            if (res && res.success === false) {
                                showToast(res.error || 'Cannot remove current track', 'error');
                            } else {
                                showToast(`Трек '${track.title || ''}' удален из очереди`, 'info');
                            }
                        } catch (err) {
                            showToast('Ошибка удаления из очереди', 'error');
                        }
                    } else if (window.pywebview?.api?.remove_from_queue) {
                        const res = await window.pywebview.api.remove_from_queue(removeIndex ?? -1);
                        if (res && res.success === false) {
                            showToast(res.error || 'Cannot remove current track', 'error');
                        }
                    } else {
                        showToast(`Трек '${track.title || ''}' удален из очереди`, 'info');
                    }
                })();
                break;
        }

        closeMenu();
    });

    function closeMenu() {
        if (activeRichMenu) {
            activeRichMenu.remove();
            activeRichMenu = null;
        }
        document.removeEventListener('click', onDocumentClick);
        document.removeEventListener('keydown', onKeyDown);
    }

    function onDocumentClick(evt) {
        if (activeRichMenu && !activeRichMenu.contains(evt.target)) {
            closeMenu();
        }
    }

    function onKeyDown(evt) {
        if (evt.key === 'Escape') {
            closeMenu();
        }
    }

    setTimeout(() => {
        document.addEventListener('click', onDocumentClick);
        document.addEventListener('keydown', onKeyDown);
    }, 50);
}



export function openEditTagsModal(track) {
    if (!track) return;
    const modal = document.getElementById('modal-edit-tags');
    if (!modal) return;

    const idInput = document.getElementById('modal-et-track-id');
    const titleInput = document.getElementById('modal-et-title');
    const artistInput = document.getElementById('modal-et-artist');
    const albumInput = document.getElementById('modal-et-album');
    const genreInput = document.getElementById('modal-et-genre');
    const yearInput = document.getElementById('modal-et-year');
    const coverPathInput = document.getElementById('modal-et-cover-path');
    const coverImg = document.getElementById('modal-et-cover-img');

    if (idInput) idInput.value = track.id || '';
    if (titleInput) titleInput.value = track.title || '';
    if (artistInput) artistInput.value = track.artist || '';
    if (albumInput) albumInput.value = track.album || '';
    if (genreInput) genreInput.value = track.genre || '';
    if (yearInput) yearInput.value = track.year || '';
    if (coverPathInput) coverPathInput.value = '';

    const coverUrl = getCoverUrl(track);
    if (coverImg) coverImg.src = coverUrl || './assets/default_cover.png';

    modal.style.display = 'flex';
    modal.classList.remove('hidden');
    renderIcons();

    const closeBtn = document.getElementById('modal-et-close');
    const cancelBtn = document.getElementById('modal-et-cancel');
    const submitBtn = document.getElementById('modal-et-submit');
    const coverBtn = document.getElementById('modal-et-btn-cover');

    function closeModal() {
        modal.style.display = 'none';
        modal.classList.add('hidden');
    }

    if (closeBtn) closeBtn.onclick = closeModal;
    if (cancelBtn) cancelBtn.onclick = closeModal;

    if (coverBtn) {
        coverBtn.onclick = async () => {
            if (window.pywebview?.api?.choose_cover_image) {
                try {
                    const res = await window.pywebview.api.choose_cover_image();
                    if (res && res.success && res.path) {
                        if (coverPathInput) coverPathInput.value = res.path;
                        const cleanPath = res.path.replace(/\\/g, '/');
                        if (coverImg) coverImg.src = `file:///${encodeURI(cleanPath.replace(/^\//, ''))}`;
                    }
                } catch(e) {
                    console.error('Error selecting cover image:', e);
                }
            }
        };
    }

    if (submitBtn) {
        submitBtn.onclick = async () => {
            const trackId = parseInt(idInput?.value || track.id);
            if (!trackId) {
                showToast('Ошибка: ID трека не найден', 'error');
                return;
            }

            const tagsData = {
                title: titleInput ? titleInput.value.trim() : '',
                artist: artistInput ? artistInput.value.trim() : '',
                album: albumInput ? albumInput.value.trim() : '',
                genre: genreInput ? genreInput.value.trim() : '',
                year: yearInput && yearInput.value ? parseInt(yearInput.value) || null : null,
                cover_path: coverPathInput ? coverPathInput.value : ''
            };

            submitBtn.disabled = true;
            submitBtn.textContent = 'Сохранение...';

            try {
                if (window.pywebview?.api?.update_track_tags) {
                    const res = await window.pywebview.api.update_track_tags(trackId, tagsData);
                    if (res && res.success) {
                        showToast('Теги и метаданные сохранены!', 'success');
                        closeModal();
                    } else {
                        showToast(res?.error || 'Ошибка сохранения тегов', 'error');
                    }
                }
            } catch(err) {
                showToast(`Ошибка: ${err.message || err}`, 'error');
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Сохранить теги';
            }
        };
    }
}

export function getSkeletonGrid(count = 10) {
    let html = '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 20px;">';
    for (let i = 0; i < count; i++) {
        html += `
            <div style="padding: 15px; border-radius: 8px; background: rgba(255,255,255,0.02);">
                <div class="skeleton skeleton-cover" style="width: 100%; aspect-ratio: 1/1; height: auto; border-radius: 8px; margin-bottom: 12px;"></div>
                <div class="skeleton skeleton-text" style="width: 80%;"></div>
                <div class="skeleton skeleton-text" style="width: 50%;"></div>
            </div>
        `;
    }
    html += '</div>';
    return html;
}
