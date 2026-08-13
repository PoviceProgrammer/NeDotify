// NeDotify - Queue Module
import { formatTime, renderIcons, getCoverUrl } from './utils.js?v=20260813';
import { getCurrentTrack, playTrack } from './player.js?v=20260813';

let isQueueVisible = false;
let draggedItemIndex = null;
let currentQueue = [];

export function initQueue() {
    const btnPP = document.getElementById('pp-btn-queue');
    const btnPB = document.getElementById('pb-btn-queue');
    const closeBtn = document.getElementById('btn-close-queue') || document.getElementById('queue-drawer-close');
    const overlay = document.getElementById('queue-overlay') || document.getElementById('queue-drawer');

    // Create a transparent backdrop for clicking outside
    let backdrop = document.getElementById('queue-backdrop');
    if (!backdrop) {
        backdrop = document.createElement('div');
        backdrop.id = 'queue-backdrop';
        backdrop.style.cssText = `
            position: fixed; inset: 0;
            z-index: 999;
            background: transparent;
            display: none;
            cursor: default;
        `;
        document.body.appendChild(backdrop);
    }

    const closeQueue = () => {
        isQueueVisible = false;
        if (overlay) overlay.classList.remove('open');
        backdrop.style.display = 'none';
    };

    const openQueue = () => {
        isQueueVisible = true;
        if (overlay) overlay.classList.add('open');
        backdrop.style.display = 'block';
        loadQueue();
    };

    backdrop.addEventListener('click', closeQueue);

    if (btnPP) btnPP.addEventListener('click', openQueue);
    if (btnPB) btnPB.addEventListener('click', openQueue);
    if (closeBtn) closeBtn.addEventListener('click', closeQueue);

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && isQueueVisible) closeQueue();
    });

    // Listen to queue updates from python
    window.addEventListener('pywebviewready', () => {
        window.pywebview.api.on_queue_updated = (q) => {
            if (isQueueVisible) {
                currentQueue = q.tracks;
                renderQueue(q.tracks, q.current_index);
            }
        };
    });

    document.addEventListener('nedotify:track_changed', () => {
        if (isQueueVisible) loadQueue();
    });
}

async function loadQueue() {
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
        item.className = 'track-item' + (index === currentIndex ? ' playing' : '');
        item.draggable = true;
        item.dataset.index = index;
        item.style.cursor = 'pointer';
        
        // We'll style it similarly to library tracks but with a drag handle
        item.innerHTML = `
            <div style="display:flex; align-items:center; color:var(--text-dim); cursor:grab; padding:0 8px;" class="drag-handle" title="Зажмите чтобы перетащить">
                <i data-lucide="grip-vertical" style="width:16px;height:16px"></i>
            </div>
            <img class="track-item-cover" src="${getCoverUrl(track)}" onerror="this.src='data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI0OCIgaGVpZ2h0PSI0OCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IiM1NTUiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIj48cGF0aCBkPSJNOSAxOHYtN20wIDd2LW0wIDdhNSA1IDAgMCAxLTUgNW01LTV2LTRtMC00VjRtMCAwdjNtMCAwaDlNMCAwdjNtMCAwdi0zbTkgM2g5bTAgMHYzbTAgMHYtM20tOSAzdi0zbTkgM2gybTAgMHYtbTAgMGgyIi8+PC9zdmc+'">
            <div class="track-item-info">
                <div class="track-item-title" style="${index === currentIndex ? 'color:var(--primary)' : ''}">${track.title || 'Unknown'}</div>
                <div class="track-item-artist">${track.artist || 'Unknown Artist'}</div>
            </div>
            <div class="track-item-duration">${formatTime(track.duration || 0)}</div>
        `;

        let isDraggingThis = false;

        // Click to play track instantly
        item.addEventListener('click', (e) => {
            if (e.target.closest('.drag-handle')) return;
            if (isDraggingThis) {
                isDraggingThis = false;
                return;
            }
            if (item.classList.contains('playing')) {
                return; // Already playing
            }

            if (window.pywebview?.api?.play_track) {
                window.pywebview.api.play_track(track, currentQueue);
            }
        });

        // Drag & Drop Events
        item.addEventListener('dragstart', (e) => {
            draggedItemIndex = index;
            isDraggingThis = true;
            item.style.opacity = '0.5';
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', index);
        });

        item.addEventListener('dragend', () => {
            draggedItemIndex = null;
            setTimeout(() => { isDraggingThis = false; }, 50);
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



