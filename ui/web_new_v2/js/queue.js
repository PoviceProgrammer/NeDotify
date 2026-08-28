import { formatTime, renderIcons, getCoverUrl, escapeHtml } from './utils.js';
import { getCurrentTrack, playTrack, incrementQueueVersion } from './player.js';

let isQueueVisible = false;
let draggedItemIndex = null;
let currentQueue = [];

export function initQueue() {
    const btnPP = document.getElementById('pp-btn-queue');
    const btnPB = document.getElementById('pb-btn-queue');
    const closeBtn = document.getElementById('queue-drawer-close');
    const drawer = document.getElementById('queue-drawer');

    // Clean up any legacy backdrop if present
    const oldBackdrop = document.getElementById('queue-backdrop');
    if (oldBackdrop) oldBackdrop.remove();

    const closeQueue = () => {
        isQueueVisible = false;
        if (drawer) drawer.classList.remove('open');
    };

    const openQueue = () => {
        isQueueVisible = true;
        if (drawer) drawer.classList.add('open');
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
        currentQueue = q.tracks || [];
        if (isQueueVisible) {
            renderQueue(q.tracks, q.current_index);
        }
    });

    document.addEventListener('nedotify:track_changed', () => {
        if (isQueueVisible) loadQueue();
    });
}

async function loadQueue() {
    await window.awaitBridge();
    if (!window.pywebview?.api?.get_queue) return;
    const q = await window.pywebview.api.get_queue();
    currentQueue = q.tracks || [];
    renderQueue(currentQueue, q.current_index);
}

function renderQueue(tracks, currentIndex) {
    const content = document.getElementById('queue-drawer-content');
    if (!tracks || tracks.length === 0) {
        content.innerHTML = '<div class="empty-state">Очередь пуста</div>';
        return;
    }

    content.innerHTML = '';
    
    tracks.forEach((track, index) => {
        const item = document.createElement('div');
        item._trackData = track;
        item.className = 'track-item' + (index === currentIndex ? ' playing' : '');
        item.draggable = false;
        item.dataset.index = index;
        item.style.cursor = 'pointer';
        
        // We'll style it similarly to library tracks but with a drag handle
        const coverUrl = getCoverUrl(track);
        item.innerHTML = `
            <div style="display:flex; align-items:center; color:var(--text-dim); cursor:grab; padding:0 6px; flex-shrink:0;" class="drag-handle" title="Зажмите чтобы перетащить">
                <i data-lucide="grip-vertical" style="width:14px;height:14px"></i>
            </div>
            ${coverUrl ? `<img class="track-item-cover" src="${escapeHtml(coverUrl)}" alt="" width="42" height="42" style="width:42px;height:42px;min-width:42px;max-width:42px;border-radius:8px;object-fit:cover;flex-shrink:0;display:block;" onerror="this.onerror=null;this.style.display=\'none\';" loading="lazy">` : `<div class="track-item-cover fallback-note-cover" style="width:42px;height:42px;min-width:42px;max-width:42px;display:flex;align-items:center;justify-content:center;background:#18181f;border-radius:8px;flex-shrink:0;"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#555" stroke-width="2"><path d="M9 18V5l12-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="18" cy="16" r="3"></circle></svg></div>`}
            <div class="track-item-info">
                <div class="track-item-title" style="${index === currentIndex ? 'color:var(--primary)' : ''}">${escapeHtml(track.title || 'Unknown')}</div>
                <div class="track-item-artist">${escapeHtml(track.artist || 'Unknown Artist')}</div>
            </div>
            <div class="track-item-duration">${formatTime(track.duration || 0)}</div>
        `;

        const handle = item.querySelector('.drag-handle');
        if (handle) {
            handle.addEventListener('mousedown', () => { item.draggable = true; });
            handle.addEventListener('mouseup', () => { item.draggable = false; });
            handle.addEventListener('mouseleave', () => { if (draggedItemIndex === null) item.draggable = false; });
        }

        // Click to play track instantly
        item.addEventListener('click', (e) => {
            if (e.target.closest('.drag-handle')) return;
            e.stopPropagation();

            if (window.pywebview?.api?.play_track) {
                window.pywebview.api.play_track(track, currentQueue, index);
            } else if (window.NeDotify?.playTrack) {
                window.NeDotify.playTrack(track);
            }
        });

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
                    await window.pywebview.api.reorder_queue(draggedItemIndex, insertIndex);
                    loadQueue();
                }
            }
        });

        content.appendChild(item);
    });

    renderIcons();
}



