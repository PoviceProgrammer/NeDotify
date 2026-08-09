import { togglePlayPause } from './player.js?v=19';

export function initHotkeys() {
    document.addEventListener('keydown', (e) => {
        // Ignore if user is typing in an input
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

        // Spacebar is a hardcoded fallback
        if (e.code === 'Space') {
            e.preventDefault();
            togglePlayPause();
            return;
        }

        if (!window.pywebview || !window.pywebview.api) return;

        // Fetch settings or just use the API if needed.
        // Actually, we can just send the pressed key combination to python
        // and let python decide, OR check against local settings.
        
        let keys = [];
        if (e.ctrlKey) keys.push('Ctrl');
        if (e.shiftKey) keys.push('Shift');
        if (e.altKey) keys.push('Alt');
        
        // Convert JS key names to match python setting format like "Ctrl+Right"
        let keyName = e.key;
        if (keyName === 'ArrowRight') keyName = 'Right';
        else if (keyName === 'ArrowLeft') keyName = 'Left';
        else if (keyName === 'ArrowUp') keyName = 'Up';
        else if (keyName === 'ArrowDown') keyName = 'Down';
        else if (keyName.length === 1) keyName = keyName.toUpperCase(); // e.g. 'm' -> 'M'
        
        if (['Control', 'Shift', 'Alt', 'Meta'].includes(keyName)) return;
        
        keys.push(keyName);
        const combo = keys.join('+');
        
        // Handle Media Keys natively (no modifier needed)
        if (e.key === 'MediaPlayPause') { e.preventDefault(); togglePlayPause(); return; }
        if (e.key === 'MediaTrackNext') { e.preventDefault(); window.pywebview.api.next_track(); return; }
        if (e.key === 'MediaTrackPrevious') { e.preventDefault(); window.pywebview.api.prev_track(); return; }
        
        // Get hotkeys config from backend directly
        window.pywebview.api.get_settings_by_category('hotkeys').then(hotkeys => {
            if (!hotkeys) return;
            
            for (const [action, bind] of Object.entries(hotkeys)) {
                if (bind === combo) {
                    e.preventDefault();
                    executeAction(action);
                    break;
                }
            }
        });
    });
}

function executeAction(action) {
    if (!window.pywebview || !window.pywebview.api) return;
    
    switch (action) {
        case 'play_pause':
            togglePlayPause();
            break;
        case 'next_track':
            window.pywebview.api.next_track();
            break;
        case 'prev_track':
            window.pywebview.api.prev_track();
            break;
        case 'volume_up':
            // we should ideally read volume from JS but it's simpler to send to python or change JS audio
            window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Громкость +' } }));
            break;
        case 'volume_down':
            window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Громкость -' } }));
            break;
        case 'mute':
            window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Без звука' } }));
            break;
        case 'like':
            const btnLike = document.getElementById('btn-like');
            if (btnLike) btnLike.click();
            break;
        case 'search':
            const searchInput = document.getElementById('search-input');
            if (searchInput) {
                // switch tab if needed
                const tabSearch = document.getElementById('tab-search');
                if (tabSearch) tabSearch.click();
                searchInput.focus();
            }
            break;
    }
}
