// NeDotify - Lyrics Display Settings Popover (Screenshot #1)
import { renderIcons, showToast } from './utils.js';
import { getCurrentTrack } from './player.js';

let popoverInitialized = false;
let saveDebounceTimer = null;

const DEFAULT_SETTINGS = {
    font_size: 24,
    font_weight: 700,
    line_height: 1.45,
    text_align: 'center'
};

let currentSettings = { ...DEFAULT_SETTINGS };

/**
 * Apply display settings to DOM, CSS variables and viewport kinetic scrollers.
 * @param {object} settings 
 * @param {boolean} shouldPersist 
 */
export function applyLyricsDisplaySettings(settings, shouldPersist = false) {
    currentSettings = {
        font_size: Math.max(14, Math.min(36, parseInt(settings.font_size, 10) || 24)),
        font_weight: Math.max(400, Math.min(800, parseInt(settings.font_weight, 10) || 700)),
        line_height: Math.max(1.1, Math.min(2.2, parseFloat(settings.line_height) || 1.45)),
        text_align: settings.text_align === 'left' ? 'left' : 'center'
    };

    const fontSizePx = `${currentSettings.font_size}px`;
    const fontWeightStr = String(currentSettings.font_weight);
    const lineHeightStr = String(currentSettings.line_height);

    // 1. Update CSS Custom Properties on document root and body
    const root = document.documentElement;
    root.style.setProperty('--lyrics-font-size', fontSizePx);
    root.style.setProperty('--lyrics-font-weight', fontWeightStr);
    root.style.setProperty('--lyrics-line-height', lineHeightStr);
    root.style.setProperty('--lyrics-text-align', currentSettings.text_align);

    if (document.body) {
        document.body.style.setProperty('--lyrics-font-size', fontSizePx);
        document.body.style.setProperty('--lyrics-font-weight', fontWeightStr);
        document.body.style.setProperty('--lyrics-line-height', lineHeightStr);
        document.body.style.setProperty('--lyrics-text-align', currentSettings.text_align);
    }

    // 2. Set data-align and scoped CSS properties on lyrics viewports & tracks
    const viewports = document.querySelectorAll(
        '.lyrics-viewport, .player-lyrics-container, .lyrics-scroll-container, #lyrics-overlay, .lyrics-track, #lyrics-content, #overlay-lyrics-content'
    );
    viewports.forEach(vp => {
        vp.dataset.align = currentSettings.text_align;
        vp.style.setProperty('--lyrics-font-size', fontSizePx);
        vp.style.setProperty('--lyrics-font-weight', fontWeightStr);
        vp.style.setProperty('--lyrics-line-height', lineHeightStr);
        vp.style.setProperty('--lyrics-text-align', currentSettings.text_align);
    });

    // 3. Directly update existing rendered lines for immediate visual response
    const lyricElements = document.querySelectorAll('.lyric-line, .lyric-orig-text, .lyric-word, .lyric-plain');
    lyricElements.forEach(el => {
        el.style.fontSize = fontSizePx;
        el.style.fontWeight = fontWeightStr;
        el.style.lineHeight = lineHeightStr;
    });

    // 3. Update Popover UI Controls if present
    const sliderSize = document.getElementById('slider-lyrics-font-size');
    const valSize = document.getElementById('val-lyrics-font-size');
    if (sliderSize) sliderSize.value = currentSettings.font_size;
    if (valSize) valSize.textContent = `${currentSettings.font_size}px`;

    const sliderWeight = document.getElementById('slider-lyrics-font-weight');
    const valWeight = document.getElementById('val-lyrics-font-weight');
    if (sliderWeight) sliderWeight.value = currentSettings.font_weight;
    if (valWeight) valWeight.textContent = String(currentSettings.font_weight);

    const sliderLh = document.getElementById('slider-lyrics-line-height');
    const valLh = document.getElementById('val-lyrics-line-height');
    if (sliderLh) sliderLh.value = currentSettings.line_height;
    if (valLh) valLh.textContent = Number(currentSettings.line_height).toFixed(2).replace(/\.?0+$/, '');

    const btnLeft = document.getElementById('btn-lyrics-align-left');
    const btnCenter = document.getElementById('btn-lyrics-align-center');
    if (btnLeft) btnLeft.classList.toggle('active', currentSettings.text_align === 'left');
    if (btnCenter) btnCenter.classList.toggle('active', currentSettings.text_align === 'center');

    // 4. Invalidate Kinetic Scroller layout so lines re-measure
    if (window.NeDotify?.invalidateLyricsKineticLayout) {
        window.NeDotify.invalidateLyricsKineticLayout();
    }

    // 5. Local Storage & Backend Persistence
    try {
        localStorage.setItem('nedotify_lyrics_display_settings', JSON.stringify(currentSettings));
    } catch (e) {
        console.warn('Could not save lyrics display settings to localStorage:', e);
    }

    if (shouldPersist) {
        if (saveDebounceTimer) clearTimeout(saveDebounceTimer);
        saveDebounceTimer = setTimeout(() => {
            if (window.pywebview?.api?.save_lyrics_display_settings) {
                window.pywebview.api.save_lyrics_display_settings(
                    currentSettings.font_size,
                    currentSettings.font_weight,
                    currentSettings.line_height,
                    currentSettings.text_align
                ).catch(err => console.warn('Failed to persist lyrics display settings to backend:', err));
            }
        }, 300);
    }
}

/**
 * Open popover anchored near the trigger button.
 * @param {HTMLElement} triggerEl 
 */
export function openLyricsSettingsPopover(triggerEl) {
    const popover = document.getElementById('lyrics-display-settings-popover');
    if (!popover) return;

    if (!popover.classList.contains('hidden')) {
        closeLyricsSettingsPopover();
        return;
    }

    popover.classList.remove('hidden');
    renderIcons(popover);

    if (triggerEl) {
        const rect = triggerEl.getBoundingClientRect();
        const popoverWidth = 320;
        const popoverHeight = 360;

        // Position horizontally: align with right edge of trigger, or clamp within viewport
        let left = rect.right - popoverWidth;
        if (left < 14) left = 14;
        if (left + popoverWidth > window.innerWidth - 14) {
            left = window.innerWidth - popoverWidth - 14;
        }

        // Position vertically: below trigger, or flip above if it overflows window bottom
        let top = rect.bottom + 10;
        if (top + popoverHeight > window.innerHeight - 14) {
            top = Math.max(14, rect.top - popoverHeight - 10);
        }

        popover.style.top = `${Math.round(top)}px`;
        popover.style.left = `${Math.round(left)}px`;
    }
}

export function closeLyricsSettingsPopover() {
    const popover = document.getElementById('lyrics-display-settings-popover');
    if (popover) {
        popover.classList.add('hidden');
    }
}

export function initLyricsSettingsPopover() {
    if (popoverInitialized) return;
    popoverInitialized = true;

    window.NeDotify = window.NeDotify || {};
    window.NeDotify.getLyricsDisplaySettings = () => ({ ...currentSettings });

    const popover = document.getElementById('lyrics-display-settings-popover');
    if (!popover) return;

    // Load initial settings: try localStorage first, then backend
    try {
        const stored = localStorage.getItem('nedotify_lyrics_display_settings');
        if (stored) {
            const parsed = JSON.parse(stored);
            applyLyricsDisplaySettings(parsed, false);
        } else {
            applyLyricsDisplaySettings(DEFAULT_SETTINGS, false);
        }
    } catch (e) {
        applyLyricsDisplaySettings(DEFAULT_SETTINGS, false);
    }

    if (window.pywebview?.api?.get_lyrics_display_settings) {
        window.pywebview.api.get_lyrics_display_settings().then(res => {
            if (res && res.success && res.settings) {
                applyLyricsDisplaySettings(res.settings, false);
            }
        }).catch(err => console.warn('Could not fetch lyrics display settings from backend:', err));
    }

    // Bind Trigger Buttons
    const triggerPage = document.getElementById('btn-lyrics-settings-page');
    const triggerOverlay = document.getElementById('btn-lyrics-settings-overlay');

    if (triggerPage) {
        triggerPage.addEventListener('click', (e) => {
            e.stopPropagation();
            openLyricsSettingsPopover(triggerPage);
        });
    }

    if (triggerOverlay) {
        triggerOverlay.addEventListener('click', (e) => {
            e.stopPropagation();
            openLyricsSettingsPopover(triggerOverlay);
        });
    }

    // Close button
    const closeBtn = document.getElementById('btn-close-lsp');
    if (closeBtn) {
        closeBtn.addEventListener('click', () => closeLyricsSettingsPopover());
    }

    // Close on outside click
    document.addEventListener('pointerdown', (e) => {
        if (!popover.classList.contains('hidden')) {
            if (!popover.contains(e.target) &&
                (!triggerPage || !triggerPage.contains(e.target)) &&
                (!triggerOverlay || !triggerOverlay.contains(e.target))) {
                closeLyricsSettingsPopover();
            }
        }
    });

    // Close on Escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !popover.classList.contains('hidden')) {
            closeLyricsSettingsPopover();
        }
    });

    // Font size slider
    const sliderSize = document.getElementById('slider-lyrics-font-size');
    if (sliderSize) {
        sliderSize.addEventListener('input', (e) => {
            applyLyricsDisplaySettings({ ...currentSettings, font_size: e.target.value }, true);
        });
    }

    // Font weight slider
    const sliderWeight = document.getElementById('slider-lyrics-font-weight');
    if (sliderWeight) {
        sliderWeight.addEventListener('input', (e) => {
            applyLyricsDisplaySettings({ ...currentSettings, font_weight: e.target.value }, true);
        });
    }

    // Line height slider
    const sliderLh = document.getElementById('slider-lyrics-line-height');
    if (sliderLh) {
        sliderLh.addEventListener('input', (e) => {
            applyLyricsDisplaySettings({ ...currentSettings, line_height: e.target.value }, true);
        });
    }

    // Segmented align buttons
    const btnLeft = document.getElementById('btn-lyrics-align-left');
    const btnCenter = document.getElementById('btn-lyrics-align-center');
    if (btnLeft) {
        btnLeft.addEventListener('click', () => {
            applyLyricsDisplaySettings({ ...currentSettings, text_align: 'left' }, true);
        });
    }
    if (btnCenter) {
        btnCenter.addEventListener('click', () => {
            applyLyricsDisplaySettings({ ...currentSettings, text_align: 'center' }, true);
        });
    }

    // Action: «Искать заново»
    const btnResearch = document.getElementById('btn-lsp-action-research');
    if (btnResearch) {
        btnResearch.addEventListener('click', () => {
            closeLyricsSettingsPopover();
            const track = getCurrentTrack();
            if (track && window.pywebview?.api?.delete_custom_lyrics) {
                window.pywebview.api.delete_custom_lyrics(track).catch(() => {});
            }
            showToast('Повторный поиск текста...', 'info');
            if (window.NeDotify?.reloadCurrentTrackLyrics) {
                window.NeDotify.reloadCurrentTrackLyrics(true);
            }
        });
    }

    // Action: «Выбрать другую версию»
    const btnPickVersion = document.getElementById('btn-lsp-action-pick-version');
    if (btnPickVersion) {
        btnPickVersion.addEventListener('click', () => {
            closeLyricsSettingsPopover();
            if (window.NeDotify?.openLyricsSearchModal) {
                window.NeDotify.openLyricsSearchModal();
            }
        });
    }

    // Action: «Добавить свой текст»
    const btnCustom = document.getElementById('btn-lsp-action-custom');
    if (btnCustom) {
        btnCustom.addEventListener('click', () => {
            closeLyricsSettingsPopover();
            if (window.NeDotify?.openLyricsCustomModal) {
                window.NeDotify.openLyricsCustomModal();
            }
        });
    }

    // Action: «Сбросить настройки»
    const btnReset = document.getElementById('btn-lsp-action-reset');
    if (btnReset) {
        btnReset.addEventListener('click', () => {
            applyLyricsDisplaySettings(DEFAULT_SETTINGS, true);
            showToast('Настройки оформления сброшены', 'info');
        });
    }
}
