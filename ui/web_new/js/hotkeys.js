import { togglePlayPause } from './player.js?v=19';

export const DEFAULT_KEYBINDS = [
    { id: 'play_pause', label: 'Воспроизведение / Пауза', defaultKey: 'Space' },
    { id: 'next_track', label: 'Следующий трек', defaultKey: 'ArrowRight' },
    { id: 'prev_track', label: 'Предыдущий трек', defaultKey: 'ArrowLeft' },
    { id: 'volume_up', label: 'Увеличить громкость (+5%)', defaultKey: 'ArrowUp' },
    { id: 'volume_down', label: 'Уменьшить громкость (-5%)', defaultKey: 'ArrowDown' },
    { id: 'toggle_mute', label: 'Вкл / Выкл звук', defaultKey: 'KeyM' },
    { id: 'toggle_lyrics', label: 'Открыть / закрыть текст', defaultKey: 'KeyL' },
    { id: 'toggle_mini', label: 'Компактный мини-плеер', defaultKey: 'KeyP' },
    { id: 'search', label: 'Фокус на поиск', defaultKey: 'Slash' },
    { id: 'like', label: 'Нравится трек', defaultKey: 'KeyK' }
];

export const activeKeybinds = {};
let listeningKeybindId = null;

export function setListeningKeybind(id) {
    listeningKeybindId = id;
}

export function getListeningKeybindId() {
    return listeningKeybindId;
}

export function saveKeybindsToStorage(keybinds) {
    try {
        localStorage.setItem('nedotify_keybinds', JSON.stringify(keybinds));
    } catch(e) {}
}

export function parseKeyEventCombo(e) {
    const parts = [];
    if (e.ctrlKey) parts.push('Ctrl');
    if (e.altKey) parts.push('Alt');
    if (e.shiftKey) parts.push('Shift');
    if (e.metaKey) parts.push('Meta');

    let keyName = e.code || e.key;
    if (keyName === ' ' || e.key === ' ') keyName = 'Space';
    if (keyName === '/' || e.key === '/') keyName = 'Slash';
    
    // Ignore standalone modifier keypresses
    if (['ControlLeft', 'ControlRight', 'AltLeft', 'AltRight', 'ShiftLeft', 'ShiftRight', 'MetaLeft', 'MetaRight', 'Control', 'Alt', 'Shift', 'Meta'].includes(keyName)) {
        return null;
    }

    parts.push(keyName);
    return parts.join('+');
}

export function initHotkeys() {
    // 1. Set default keybinds
    DEFAULT_KEYBINDS.forEach(kb => {
        activeKeybinds[kb.id] = kb.defaultKey;
    });

    // 2. Load local storage fallback
    const localSaved = localStorage.getItem('nedotify_keybinds');
    if (localSaved) {
        try { Object.assign(activeKeybinds, JSON.parse(localSaved)); } catch(e) {}
    }

    // 3. Load backend keybinds category settings
    if (window.pywebview?.api?.get_settings_by_category) {
        window.pywebview.api.get_settings_by_category('keybinds').then(saved => {
            if (saved && typeof saved === 'object') {
                Object.assign(activeKeybinds, saved);
                saveKeybindsToStorage(activeKeybinds);
            }
            if (window.renderKeybindsList) window.renderKeybindsList();
        }).catch(() => {
            if (window.renderKeybindsList) window.renderKeybindsList();
        });
    }

    // SINGLE AUTHORITATIVE GLOBAL KEYDOWN LISTENER (Eliminates double toggle on Space)
    window.addEventListener('keydown', (e) => {
        // Rebinding Mode inside Settings UI
        if (listeningKeybindId) {
            e.preventDefault();
            e.stopPropagation();
            const combo = parseKeyEventCombo(e);
            if (combo && e.code !== 'Escape') {
                activeKeybinds[listeningKeybindId] = combo;
                saveKeybindsToStorage(activeKeybinds);
                if (window.pywebview?.api?.save_setting) {
                    window.pywebview.api.save_setting(listeningKeybindId, combo, 'keybinds');
                }
            }
            listeningKeybindId = null;
            if (window.renderKeybindsList) window.renderKeybindsList();
            return;
        }

        // Ignore if user is typing in an input or editable element
        const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
        if (activeTag === 'input' || activeTag === 'textarea' || document.activeElement?.isContentEditable || e.target.matches('input, textarea, select, [contenteditable="true"]')) {
            return;
        }

        // F11: Frameless Window Maximize (keeps taskbar visible)
        if (e.key === 'F11' || e.code === 'F11') {
            e.preventDefault();
            if (window.pywebview?.api?.maximize) {
                window.pywebview.api.maximize();
            }
            return;
        }

        // Handle native Media Keys
        if (e.key === 'MediaPlayPause') { e.preventDefault(); togglePlayPause(); return; }
        if (e.key === 'MediaTrackNext') { e.preventDefault(); if (window.pywebview?.api) window.pywebview.api.next_track(); return; }
        if (e.key === 'MediaTrackPrevious') { e.preventDefault(); if (window.pywebview?.api) window.pywebview.api.prev_track(); return; }

        const pressedCombo = parseKeyEventCombo(e);
        if (!pressedCombo) return;

        // Exact combo match against active keybinds
        for (const [actionId, key] of Object.entries(activeKeybinds)) {
            const isMatch = (key === pressedCombo) || 
                            (key === 'Space' && (pressedCombo === 'Space' || e.code === 'Space' || e.key === ' '));
            if (isMatch) {
                e.preventDefault();
                executeHotkeysAction(actionId);
                break;
            }
        }
    });
}

export function executeHotkeysAction(actionId) {
    switch (actionId) {
        case 'play_pause':
            togglePlayPause();
            break;
        case 'next_track':
            if (window.pywebview?.api?.next_track) window.pywebview.api.next_track();
            break;
        case 'prev_track':
            if (window.pywebview?.api?.prev_track) window.pywebview.api.prev_track();
            break;
        case 'volume_up':
            if (window.NeDotify?.adjustVolume) {
                window.NeDotify.adjustVolume(5);
            }
            break;
        case 'volume_down':
            if (window.NeDotify?.adjustVolume) {
                window.NeDotify.adjustVolume(-5);
            }
            break;
        case 'toggle_mute':
        case 'mute':
            const volBtn = document.getElementById('pb-volume-btn');
            if (volBtn) volBtn.click();
            break;
        case 'like':
            const btnLike = document.getElementById('pp-btn-like') || document.getElementById('btn-like');
            if (btnLike) btnLike.click();
            break;
        case 'toggle_lyrics':
            const lyricsBtn = document.getElementById('pp-btn-lyrics');
            if (lyricsBtn) lyricsBtn.click();
            break;
        case 'toggle_mini':
            if (window.NeDotify?.toggleMiniPlayerMode) {
                window.NeDotify.toggleMiniPlayerMode();
            } else if (window.toggleMiniPlayerMode) {
                window.toggleMiniPlayerMode();
            }
            break;
        case 'search':
            if (window.NeDotify?.showPage) window.NeDotify.showPage('home');
            setTimeout(() => {
                const searchInput = document.getElementById('search-input') || document.getElementById('global-search-input');
                if (searchInput) {
                    searchInput.focus();
                    if (searchInput.select) searchInput.select();
                }
            }, 50);
            break;
    }
}
