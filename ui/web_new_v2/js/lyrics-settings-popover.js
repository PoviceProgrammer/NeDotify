// NeDotify - Lyrics Display Settings Popover (Screenshot #1)
import { renderIcons, showToast } from './utils.js';
import { getCurrentTrack } from './player.js';

let popoverInitialized = false;
let saveDebounceTimer = null;
// One kinetic re-measure per frame. Every slider `input` used to re-measure both
// sheets synchronously (write padding, then read offsetHeight/offsetTop), so a
// drag at input rate forced a layout flush per event on a sheet with hundreds of
// lines. The sheet only has to be re-anchored once per painted frame.
let layoutFrame = 0;

const DEFAULT_SETTINGS = {
    font_size: 24,
    font_weight: 700,
    line_height: 1.45,
    text_align: 'center'
};

const STORAGE_KEY = 'nedotify_lyrics_display_settings';

let currentSettings = { ...DEFAULT_SETTINGS };
// Set as soon as the user moves a slider or picks an alignment. A backend
// response that arrives afterwards must not overwrite what they just chose.
let userTouched = false;

/**
 * The bridge and SQLite speak camelCase (`fontSize`, `textAlign`); the DOM side
 * and the ranges speak snake_case. Accept either spelling and return only the
 * keys that are actually present, so a partial backend response can be merged
 * over the localStorage copy instead of resetting the missing fields.
 * @param {*} source
 * @returns {{font_size?:*,font_weight?:*,line_height?:*,text_align?:*}|null}
 */
function normalizeSettings(source) {
    if (!source || typeof source !== 'object') return null;
    const pick = (...names) => {
        for (const name of names) {
            const value = source[name];
            if (value !== undefined && value !== null && value !== '') return value;
        }
        return undefined;
    };
    const size = pick('font_size', 'fontSize');
    const weight = pick('font_weight', 'fontWeight');
    const lineHeight = pick('line_height', 'lineHeight');
    const align = pick('text_align', 'textAlign');
    const normalized = {};
    if (size !== undefined) normalized.font_size = size;
    if (weight !== undefined) normalized.font_weight = weight;
    if (lineHeight !== undefined) normalized.line_height = lineHeight;
    if (align !== undefined) normalized.text_align = align;
    return normalized;
}

/**
 * Apply display settings to DOM, CSS variables and viewport kinetic scrollers.
 * @param {object} settings 
 * @param {boolean} shouldPersist 
 */
export function applyLyricsDisplaySettings(settings, shouldPersist = false) {
    // The DOM side is snake_case; everything coming from the bridge, SQLite or
    // localStorage may be camelCase or partially filled. Normalize once, here,
    // so every caller shares the same tolerance. Missing fields fall back to
    // the defaults; a caller that wants to keep current values merges first.
    const incoming = { ...DEFAULT_SETTINGS, ...(normalizeSettings(settings) || {}) };
    currentSettings = {
        font_size: Math.max(14, Math.min(36, parseInt(incoming.font_size, 10) || 24)),
        font_weight: Math.max(400, Math.min(800, parseInt(incoming.font_weight, 10) || 700)),
        line_height: Math.max(1.1, Math.min(2.2, parseFloat(incoming.line_height) || 1.45)),
        text_align: incoming.text_align === 'left' ? 'left' : 'center'
    };
    if (shouldPersist) userTouched = true;

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

    // 3. Typography is carried entirely by the custom properties above: both
    // lyric.css rules that matter (`font-size`, `font-weight`, `line-height`)
    // already read `var(--lyrics-*)`, and `font-size` is `!important` there, so
    // inline styles on the lines could never win anyway. The old loop wrote
    // fontSize/fontWeight/lineHeight onto every rendered line on each `input`
    // event — hundreds of no-op style writes per slider frame.

    // 4. Update Popover UI Controls if present
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

    // 5. Invalidate Kinetic Scroller layout so lines re-measure. Coalesced to
    // one frame: `measureViewport` writes px padding and reads offsetHeight, so
    // calling it per `input` event forced a layout flush at pointer rate.
    if (window.NeDotify?.invalidateLyricsKineticLayout && !layoutFrame) {
        const schedule = typeof requestAnimationFrame === 'function'
            ? (fn) => requestAnimationFrame(fn)
            : (fn) => setTimeout(fn, 16);
        layoutFrame = schedule(() => {
            layoutFrame = 0;
            window.NeDotify.invalidateLyricsKineticLayout();
        });
    }

    // 6. Local Storage & Backend Persistence
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(currentSettings));
    } catch (e) {
        console.warn('Could not save lyrics display settings to localStorage:', e);
    }

    if (shouldPersist) {
        if (saveDebounceTimer) clearTimeout(saveDebounceTimer);
        saveDebounceTimer = setTimeout(persistToBackend, 300);
    }
}

/**
 * Send the current settings to the Python side. The bridge forwards arguments
 * as-is and the method takes a single `settings` dict; the old call passed four
 * positional numbers, failed `isinstance(settings, dict)` and saved nothing.
 */
function persistToBackend() {
    saveDebounceTimer = null;
    const api = window.pywebview?.api;
    if (!api?.save_lyrics_display_settings) return;
    api.save_lyrics_display_settings({
        fontSize: currentSettings.font_size,
        fontWeight: currentSettings.font_weight,
        lineHeight: currentSettings.line_height,
        textAlign: currentSettings.text_align,
    }).then(result => {
        if (result === false) console.warn('Backend rejected lyrics display settings');
    }).catch(err => console.warn('Failed to persist lyrics display settings to backend:', err));
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

    popover.inert = false;
    popover.classList.remove('hidden');
    renderIcons(popover);

    if (triggerEl) {
        const rect = triggerEl.getBoundingClientRect();
        // Measure, do not guess: the popover is ~500px tall, and the old
        // hard-coded 360 pointed the flip test at the wrong edge.
        const popoverWidth = popover.offsetWidth || 320;
        const popoverHeight = popover.offsetHeight || 360;

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
    // A pending debounce would be lost if the app closes right after the user
    // picks a value, so flush it when the popover is dismissed.
    if (saveDebounceTimer) {
        clearTimeout(saveDebounceTimer);
        persistToBackend();
    }
    const popover = document.getElementById('lyrics-display-settings-popover');
    if (popover) {
        popover.inert = true;
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

    // `#app-container` is a stacking context (position: relative; z-index: 10).
    // The expanded player is moved to <body> with z-index: 80, so a fixed
    // popover kept inside the container is painted *underneath* the expanded
    // player — it opened correctly but every click looked dead. A global
    // overlay belongs at the top level, outside every stacking context.
    if (popover.parentElement !== document.body) document.body.appendChild(popover);

    // Load initial settings: localStorage paints immediately, the backend is the
    // source of truth and may correct it. Both are normalized because they use
    // different key spellings (snake_case vs camelCase).
    try {
        const stored = localStorage.getItem(STORAGE_KEY);
        applyLyricsDisplaySettings(stored ? JSON.parse(stored) : DEFAULT_SETTINGS, false);
    } catch (e) {
        applyLyricsDisplaySettings(DEFAULT_SETTINGS, false);
    }

    if (window.pywebview?.api?.get_lyrics_display_settings) {
        window.pywebview.api.get_lyrics_display_settings().then(res => {
            // Accept either the wrapped `{success, settings}` shape or a flat
            // settings object, and merge over what localStorage already painted:
            // the backend returns only stored keys, so a fresh database must not
            // wipe a value the user chose before saves were fixed.
            const incoming = normalizeSettings(res?.settings ?? res);
            if (!incoming || userTouched || !Object.keys(incoming).length) return;
            applyLyricsDisplaySettings({ ...currentSettings, ...incoming }, false);
        }).catch(err => console.warn('Could not fetch lyrics display settings from backend:', err));
    }

    // Last-chance flush if the window closes inside the debounce window.
    window.addEventListener('pagehide', () => {
        if (saveDebounceTimer) {
            clearTimeout(saveDebounceTimer);
            persistToBackend();
        }
    });

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
        btnResearch.addEventListener('click', async () => {
            closeLyricsSettingsPopover();
            const track = getCurrentTrack();
            if (track && window.pywebview?.api?.delete_custom_lyrics) {
                try {
                    const response = await window.pywebview.api.delete_custom_lyrics(track);
                    if (!response?.success) throw new Error();
                } catch {
                    showToast('Не удалось сбросить выбранный текст', 'error');
                    return;
                }
                if (getCurrentTrack() !== track) return;
            }
            showToast('Повторный поиск текста...', 'info');
            if (window.NeDotify?.reloadCurrentTrackLyrics) {
                window.NeDotify.reloadCurrentTrackLyrics(true);
            }
        });
    }

    // Action: «Найти текст по названию»
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
