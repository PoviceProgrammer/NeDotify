export function initContextMenu() {
    const menu = document.getElementById('custom-context-menu');
    let currentTargetTrack = null;

    if (!menu) return;

    document.addEventListener('contextmenu', (e) => {
        const trackItem = e.target.closest('.track-item, .album-track-item, .queue-item');
        if (trackItem && trackItem.dataset.track) {
            e.preventDefault();
            try {
                currentTargetTrack = JSON.parse(trackItem.dataset.track);
                
                // Position menu
                let x = e.clientX;
                let y = e.clientY;
                
                menu.classList.add('active');
                
                // Ensure menu doesn't go off screen
                const rect = menu.getBoundingClientRect();
                if (x + rect.width > window.innerWidth) x = window.innerWidth - rect.width - 10;
                if (y + rect.height > window.innerHeight) y = window.innerHeight - rect.height - 10;
                
                menu.style.left = `${x}px`;
                menu.style.top = `${y}px`;
            } catch (err) {
                console.error("Failed to parse track data for context menu", err);
            }
        } else {
            menu.classList.remove('active');
        }
    });

    document.addEventListener('click', (e) => {
        if (!e.target.closest('#custom-context-menu')) {
            menu.classList.remove('active');
        }
    });

    // Menu actions
    document.getElementById('cmenu-playnext')?.addEventListener('click', () => {
        if (currentTargetTrack && window.pywebview?.api?.add_to_queue) {
            window.pywebview.api.add_to_queue(currentTargetTrack);
            window.dispatchEvent(new CustomEvent('nedotify:toast', {detail: {msg: 'Добавлено в очередь'}}));
        }
        menu.classList.remove('active');
    });

    document.getElementById('cmenu-addplaylist')?.addEventListener('click', () => {
        if (currentTargetTrack && window.NeDotify?.openPlaylistMenu) {
            window.NeDotify.openPlaylistMenu(currentTargetTrack);
        }
        menu.classList.remove('active');
    });
    
    document.getElementById('cmenu-info')?.addEventListener('click', () => {
        if (currentTargetTrack) {
            alert(`Исполнитель: ${currentTargetTrack.artist}\\nНазвание: ${currentTargetTrack.title}\\nАльбом: ${currentTargetTrack.album || 'Неизвестно'}`);
        }
        menu.classList.remove('active');
    });

    document.getElementById('cmenu-download')?.addEventListener('click', () => {
        if (currentTargetTrack && window.pywebview?.api?.download_track) {
            window.pywebview.api.download_track(currentTargetTrack);
            window.dispatchEvent(new CustomEvent('nedotify:toast', {detail: {msg: 'Скачивание начато'}}));
        }
        menu.classList.remove('active');
    });
}
