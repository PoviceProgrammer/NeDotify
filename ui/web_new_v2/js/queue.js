import { formatTime, renderIcons, getCoverUrl, escapeHtml, showToast } from './utils.js';
import { getCurrentTrack, playTrack, incrementQueueVersion } from './player.js';
import { getTrackWaveState, stopTrackWave, retryTrackWave } from './track-wave.js';

let isQueueVisible = false;
let draggedItemIndex = null;
let currentQueue = [];
let queueLoadGen = 0;
let queueRevision = null;
let queueTab = 'upcoming';
let lastSnapshot = {tracks: [], currentIndex: -1, history: []};

export function queueRows(tracks, currentIndex, history = [], tab = 'upcoming') {
    if (tab === 'history') return history.slice().reverse().map(track => ({track, index: track.queue_index, section: 'Прослушано'}));
    return [
        ...(tracks[currentIndex] ? [{track: tracks[currentIndex], index: currentIndex, section: 'Сейчас играет'}] : []),
        ...tracks.slice(Math.max(0, currentIndex + 1)).map((track, i) => ({track, index: Math.max(0, currentIndex + 1) + i, section: 'Далее'})),
    ];
}

export function getQueueTracks() { return currentQueue; }
function syncQueueToWindow() { window.currentQueue = currentQueue; }

export function initQueue() {
    const btnPP = document.getElementById('pp-btn-queue');
    const btnPB = document.getElementById('pb-btn-queue');
    const closeBtn = document.getElementById('queue-drawer-close');
    const drawer = document.getElementById('queue-drawer');
    const setOpen = open => {
        drawer?.setAttribute('aria-hidden', String(!open));
        if (drawer) drawer.inert = !open;
        [btnPP, btnPB].forEach(button => {
            button?.classList.toggle('active', open);
            button?.setAttribute('aria-expanded', String(open));
        });
    };
    setOpen(false);
    document.querySelectorAll('[data-queue-tab]').forEach(button => button.addEventListener('click', () => {
        const content = document.getElementById('queue-drawer-content');
        const change = () => {
            queueTab = button.dataset.queueTab;
            renderQueue(lastSnapshot.tracks, lastSnapshot.currentIndex, lastSnapshot.history);
            if (content) content.scrollTop = 0;
        };
        if (window.NeDotifyMotion) window.NeDotifyMotion.swap(content, change); else change();
    }));

    // Clean up any legacy backdrop if present
    const oldBackdrop = document.getElementById('queue-backdrop');
    if (oldBackdrop) oldBackdrop.remove();

    const closeQueue = () => {
        isQueueVisible = false;
        if (drawer) drawer.classList.remove('open');
        setOpen(false);
    };

    const openQueue = () => {
        isQueueVisible = true;
        if (drawer) drawer.classList.add('open');
        setOpen(true);
        loadQueue();
    };

    const toggleQueue = () => {
        if (isQueueVisible) {
            closeQueue();
        } else {
            openQueue();
        }
    };

    if (btnPP) btnPP.addEventListener('click', (e) => { e.stopPropagation(); toggleQueue(); });
    if (btnPB) btnPB.addEventListener('click', (e) => { e.stopPropagation(); toggleQueue(); });
    if (closeBtn) closeBtn.addEventListener('click', (e) => { e.stopPropagation(); closeQueue(); });

    ensureClearButton(drawer);
    ensureWaveStatus(drawer);
    window.addEventListener('nedotify:track_wave_state_changed', event => renderWaveStatus(event.detail));

    // Close on click outside WITHOUT blocking underlying clicks
    document.addEventListener('pointerdown', (e) => {
        if (!isQueueVisible) return;
        if (drawer && !drawer.contains(e.target) && !e.target.closest('#pb-btn-queue, #pp-btn-queue')) {
            closeQueue();
        }
    });

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && isQueueVisible) closeQueue();
    });

    // Listen to queue updates from python (dispatched via events.js as nedotify:queue_updated)
    document.addEventListener('nedotify:queue_updated', (e) => {
        incrementQueueVersion();
        const q = e.detail || {};
        queueLoadGen++;
        queueRevision = q.queue_revision ?? null;
        currentQueue = q.tracks || [];
        syncQueueToWindow();
        if (isQueueVisible) {
            renderQueue(q.tracks, q.current_index, q.history);
        }
    });

    document.addEventListener('nedotify:track_changed', () => {
        if (isQueueVisible) loadQueue();
    });
}

async function loadQueue() {
    const gen = ++queueLoadGen;
    await window.awaitBridge();
    if (!window.pywebview?.api?.get_queue) return;
    let q;
    try { q = await window.pywebview.api.get_queue(); }
    catch { showToast('Не удалось загрузить очередь', 'error'); return; }
    if (gen !== queueLoadGen || !q) return;
    currentQueue = q.tracks || [];
    queueRevision = q.queue_revision ?? null;
    syncQueueToWindow();
    renderQueue(currentQueue, q.current_index, q.history);
}

// "Clear" button in the drawer header: prefers the clear_queue bridge,
// falls back to removing tracks from the end (keeps the playing track).
function ensureClearButton(drawer) {
    const header = document.getElementById('queue-drawer-header');
    if (!header || document.getElementById('queue-clear-btn')) return;
    const btn = document.createElement('button');
    btn.id = 'queue-clear-btn';
    btn.className = 'icon-btn';
    btn.title = 'Очистить очередь';
    btn.style.cssText = 'display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-sec);';
    btn.innerHTML = '<i data-lucide="trash-2" style="width:14px;height:14px"></i><span>Очистить</span>';
    const closeEl = document.getElementById('queue-drawer-close');
    if (closeEl) header.insertBefore(btn, closeEl);
    else header.appendChild(btn);
    renderIcons(header);
    btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        stopTrackWave();
        btn.disabled = true;
        try {
            if (window.pywebview?.api?.clear_queue) {
                const res = await window.pywebview.api.clear_queue();
                if (res && res.success === false) {
                    showToast(res.error || 'Не удалось очистить очередь', 'error');
                }
            } else if (window.pywebview?.api?.remove_from_queue) {
                await window.awaitBridge?.();
                const q = window.pywebview?.api?.get_queue ? await window.pywebview.api.get_queue() : null;
                const tracks = (q && q.tracks) || currentQueue || [];
                const curIdx = (q && q.current_index !== undefined) ? q.current_index : -1;
                for (let i = tracks.length - 1; i >= 0; i--) {
                    if (i === curIdx) continue;
                    try { await window.pywebview.api.remove_from_queue(i); } catch(err) {}
                }
            }
            await loadQueue();
        } finally {
            btn.disabled = false;
        }
    });
}

function ensureWaveStatus(drawer) {
    if (!drawer || document.getElementById('queue-wave-status')) return;
    const panel = document.createElement('div');
    panel.id = 'queue-wave-status';
    panel.className = 'queue-wave-status';
    panel.hidden = true;
    panel.innerHTML = '<div class="queue-wave-copy"><strong>Непрерывная волна</strong><span role="status" aria-live="polite"></span></div>' +
        '<button type="button" class="queue-wave-retry">Повторить</button><button type="button" class="queue-wave-stop" aria-label="Остановить подбор волны" title="Остановить подбор, сохранив очередь">Стоп</button>';
    panel.querySelector('.queue-wave-stop').addEventListener('click', stopTrackWave);
    panel.querySelector('.queue-wave-retry').addEventListener('click', () => { void retryTrackWave(); });
    drawer.insertBefore(panel, drawer.querySelector('.queue-view-tabs') || drawer.querySelector('#queue-drawer-content'));
    renderWaveStatus(getTrackWaveState());
}

function renderWaveStatus(state = getTrackWaveState()) {
    const panel = document.getElementById('queue-wave-status');
    if (!panel) return;
    panel.hidden = !state.active;
    panel.dataset.status = state.status;
    const message = state.status === 'loading' ? 'Подбираем продолжение…' : state.status === 'waiting' ? 'Продолжение не загружено' : 'Продолжение добавится автоматически';
    const label = panel.querySelector('[role="status"]');
    label.textContent = message;
    label.title = state.title ? `Волна по треку «${state.title}»` : message;
    panel.querySelector('.queue-wave-retry').hidden = state.status !== 'waiting';
}

function renderQueue(tracks, currentIndex, history = []) {
    const content = document.getElementById('queue-drawer-content');
    if (!content) return;
    tracks = Array.isArray(tracks) ? tracks : [];
    history = Array.isArray(history) ? history : [];
    lastSnapshot = {tracks, currentIndex, history};
    document.querySelectorAll('[data-queue-tab]').forEach(button => {
        const selected = button.dataset.queueTab === queueTab;
        button.setAttribute('aria-pressed', String(selected));
        const count = button.querySelector('span');
        if (count) count.textContent = button.dataset.queueTab === 'history' ? history.length : Math.max(0, tracks.length - Math.max(0, currentIndex + 1));
    });
    const renderedRevision = queueRevision;
    if (!tracks.length || (queueTab === 'history' && !history.length)) {
        content.innerHTML = `<div class="empty-state">${queueTab === 'history' ? 'Здесь появятся прослушанные треки' : 'Добавьте треки в очередь'}</div>`;
        return;
    }

    content.innerHTML = '';

    // Build every row into a fragment and insert once (search.js pattern):
    // N appendChild calls would invalidate layout N times. No layout read
    // happens below, and the getBoundingClientRect() calls live in the
    // dragover/drop handlers, which can only fire after this loop returns.
    const fragment = document.createDocumentFragment();

    const rows = queueRows(tracks, currentIndex, history, queueTab);
    let previousSection = null;
    rows.forEach(({track,index,section}, position) => {
        if (section !== previousSection) {
            const heading = document.createElement('h3');
            heading.className = 'queue-section-title';
            heading.textContent = section;
            fragment.appendChild(heading);
            previousSection = section;
        }
        const item = document.createElement('div');
        item._trackData = track;
        item.className = 'track-item' + (queueTab !== 'history' && index === currentIndex ? ' playing' : '');
        item.classList.toggle('queue-history-row', queueTab === 'history');
        item.draggable = false;
        item.dataset.index = index;
        item.style.cursor = 'pointer';
        
        // We'll style it similarly to library tracks but with a drag handle
        const coverUrl = getCoverUrl(track);
        item.innerHTML = `
            <span class="track-number">${position + 1}</span>
            <div style="display:flex; align-items:center; color:var(--text-dim); cursor:grab; padding:0 6px; flex-shrink:0;" class="drag-handle" title="Зажмите чтобы перетащить">
                <i data-lucide="grip-vertical" style="width:14px;height:14px"></i>
            </div>
            ${coverUrl ? `<img class="track-item-cover" src="${escapeHtml(coverUrl)}" alt="" width="42" height="42" style="width:42px;height:42px;min-width:42px;max-width:42px;border-radius:8px;object-fit:cover;flex-shrink:0;display:block;" loading="lazy" decoding="async" data-hide-on-error="1" loading="lazy">` : `<div class="track-item-cover fallback-note-cover" style="width:42px;height:42px;min-width:42px;max-width:42px;display:flex;align-items:center;justify-content:center;background:#18181f;border-radius:8px;flex-shrink:0;"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#555" stroke-width="2"><path d="M9 18V5l12-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="18" cy="16" r="3"></circle></svg></div>`}
            <div class="track-item-info">
                <div class="track-item-title" style="${queueTab !== 'history' && index === currentIndex ? 'color:var(--primary)' : ''}">${escapeHtml(track.title || 'Unknown')}</div>
                <div class="track-item-artist">${escapeHtml(track.artist || 'Unknown Artist')}</div>
                ${track.recommendation_reason ? `<div class="recommendation-reason" title="${escapeHtml(track.recommendation_reason)}">${escapeHtml(track.recommendation_reason)}</div>` : ''}
            </div>
            <div class="track-item-duration">${formatTime(track.duration || 0)}</div>
            <button class="icon-btn queue-remove-btn" title="Удалить из очереди" style="flex-shrink:0;width:26px;height:26px;opacity:0.55;">
                <i data-lucide="x" style="width:14px;height:14px"></i>
            </button>
        `;

        const handle = item.querySelector('.drag-handle');
        if (handle) {
            handle.addEventListener('mousedown', () => { item.draggable = true; });
            handle.addEventListener('mouseup', () => { item.draggable = false; });
            handle.addEventListener('mouseleave', () => { if (draggedItemIndex === null) item.draggable = false; });
        }

        // Click to play track instantly
        item.addEventListener('click', async (e) => {
            if (e.target.closest('.drag-handle')) return;
            if (e.target.closest('.queue-remove-btn')) return;
            e.stopPropagation();

            if (window.pywebview?.api?.play_track) {
                try {
                    // BUG-U3-001: мёртвая ветка play_queue_track удалена — такого метода
                    // нет ни в PUBLIC_METHODS моста, ни в AppApi; play_track(track)
                    // сам находит трек по entry_id в живой очереди.
                    const result = await window.pywebview.api.play_track(track);
                    if (result === false || result?.success === false) throw new Error('Play rejected');
                } catch { showToast('Не удалось включить трек из очереди', 'error'); }
            } else if (window.NeDotify?.playTrack) {
                window.NeDotify.playTrack(track);
            }
        });

        // Remove-track cross button → backend remove_from_queue
        const removeBtn = item.querySelector('.queue-remove-btn');
        if (removeBtn) {
            removeBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                e.preventDefault();
                if (index === currentIndex) {
                    showToast('Нельзя удалить текущий трек', 'warning');
                    return;
                }
                if (removeBtn.disabled) return;
                removeBtn.disabled = true;
                try {
                    if (window.pywebview?.api?.remove_from_queue) {
                        try {
                            const res = await window.pywebview.api.remove_from_queue(index, track.entry_id ?? null, renderedRevision);
                            if (res === false || res?.success === false) {
                                showToast(res.error || 'Не удалось удалить трек', 'error');
                                return;
                            }
                        } catch(err) {
                            showToast('Ошибка удаления из очереди', 'error');
                            return;
                        }
                    } else {
                        currentQueue.splice(index, 1);
                        syncQueueToWindow();
                    }
                    await loadQueue();
                } finally {
                    removeBtn.disabled = false;
                }
            });
            removeBtn.addEventListener('mousedown', (e) => e.stopPropagation());
        }

        // Drag & Drop Events
        item.addEventListener('dragstart', (e) => {
            draggedItemIndex = index;
            item.style.opacity = '0.5';
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', String(index));
        });

        item.addEventListener('dragend', () => {
            draggedItemIndex = null;
            item.draggable = false;
            item.style.opacity = '1';
            document.querySelectorAll('.track-item').forEach(el => {
                el.classList.remove('drag-over-top');
                el.classList.remove('drag-over-bottom');
            });
        });

        item.addEventListener('dragover', (e) => {
            e.preventDefault(); // Necessary to allow dropping
            if (draggedItemIndex === null || draggedItemIndex === index) return;
            
            const rect = item.getBoundingClientRect();
            const relY = e.clientY - rect.top;
            
            item.classList.remove('drag-over-top', 'drag-over-bottom');
            if (relY < rect.height / 2) {
                item.classList.add('drag-over-top');
            } else {
                item.classList.add('drag-over-bottom');
            }
        });

        item.addEventListener('dragleave', () => {
            item.classList.remove('drag-over-top', 'drag-over-bottom');
        });

        item.addEventListener('drop', async (e) => {
            e.preventDefault();
            item.classList.remove('drag-over-top', 'drag-over-bottom');
            
            if (draggedItemIndex === null || draggedItemIndex === index) return;
            
            const rect = item.getBoundingClientRect();
            const relY = e.clientY - rect.top;
            let insertIndex = index;
            
            if (relY >= rect.height / 2) {
                insertIndex++;
            }
            
            if (draggedItemIndex < insertIndex) {
                insertIndex--;
            }
            
            if (draggedItemIndex !== insertIndex) {
                const movedItem = currentQueue.splice(draggedItemIndex, 1)[0];
                currentQueue.splice(insertIndex, 0, movedItem);
                
                if (window.pywebview?.api?.reorder_queue) {
                    try {
                        const result = await window.pywebview.api.reorder_queue(draggedItemIndex, insertIndex, movedItem?.entry_id ?? null, renderedRevision);
                        if (result === false || result?.success === false) throw new Error('Reorder rejected');
                    } catch(err) {
                        console.error('reorder_queue failed:', err);
                        showToast('Не удалось изменить порядок очереди', 'error');
                    } finally {
                        await loadQueue();
                    }
                }
            }
        });

        fragment.appendChild(item);
    });

    renderIcons(fragment);
    content.appendChild(fragment);
}



