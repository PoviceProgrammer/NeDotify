// NeDotify - Lyrics Module (Synchronized Lyrics Engine)
import { getCurrentTrack, getLyricsPlaybackClock, seekTo } from './player.js';
import { renderIcons } from './utils.js';
import { normalizedTimedLines, WordPainter } from './lyrics-word-engine.js';
import { initLyricsSettingsPopover, openLyricsSettingsPopover, applyLyricsDisplaySettings } from './lyrics-settings-popover.js';
import { initLyricsSearchModal, openLyricsSearchModal } from './lyrics-search-modal.js';
import { initLyricsCustomModal, openLyricsCustomModal } from './lyrics-custom-modal.js';

let parsedLyrics = [];
let currentLineIndex = -1;
let isOverlayVisible = false;
let currentOffsetMs = 0;
let isTranslationEnabled = false;
let currentTranslationMap = {};
let currentRawLyricsText = "";
let lastLyricsData = null;
let lastLoadedTrackKey = "";
let lastPosMs = 0;

// Freshness guard — stale get_lyrics responses must not overwrite a newer track
let lyricsLoadGeneration = 0;
let activeLyricsRequestId = null;
let lastLyricsRevision = 0;
let requestedLyricsDurationMs = 0;
let pendingLyricsRequest = null;
let deferredLyricsRequest = null;
const lyricsMemoryCache = new Map();
const LYRICS_MEMORY_CACHE_LIMIT = 40;
const LYRICS_PENDING_MAX_AGE_MS = 15000;
let lyricsInitialized = false;
let wordPainter = null;
let wordRows = [];
let wordFrameId = null;
function lyricsPreferences() {
    const settings = window.settings?.lyrics || {};
    return {mode: ['auto', 'word', 'line'].includes(settings.mode) ? settings.mode : 'auto',
        animations: ['standard', 'reduced', 'off'].includes(settings.animations) ? settings.animations : 'standard'};
}

function clearWordLyrics() {
    if (wordFrameId !== null) cancelAnimationFrame(wordFrameId);
    wordFrameId = null;
    wordPainter = null;
    wordRows = [];
}

function lyricsAreVisible() {
    if (document.hidden) return false;
    return getContainers().some(container => container.getClientRects().length > 0);
}

function paintWordLyrics(positionMs, force = false) {
    if (!wordPainter) return;
    wordPainter.paint(wordRows, positionMs + currentOffsetMs, lyricsPreferences().animations, force);
}

function syncWordLyrics() {
    if (!wordPainter) return;
    const clock = getLyricsPlaybackClock();
    if (clock.trackKey !== lastLoadedTrackKey) return;
    updateLyricsPosition(clock.positionMs);
    if (wordFrameId !== null || clock.paused || clock.buffering || clock.seeking || !lyricsAreVisible()) return;
    wordFrameId = requestAnimationFrame(() => {
        wordFrameId = null;
        syncWordLyrics();
    });
}

function appendTimedWords(parent, line) {
    return line.words.map(word => {
        const span = document.createElement('span');
        span.className = 'lyric-word';
        span.textContent = word.text;
        span.dataset.wordState = 'upcoming';
        span.addEventListener('click', event => {
            event.stopPropagation();
            const position = Math.max(0, word.startMs - currentOffsetMs);
            seekTo(position);
            lastManualScrollAt = 0;
            currentLineIndex = -1;
            updateLyricsPosition(position);
            syncWordLyrics();
        });
        parent.appendChild(span);
        return span;
    });
}

// Duration unit contract (BUG-L2-005). The backend persists SECONDS:
// core/database.py stores tracks.duration as REAL seconds and every provider
// converts before persisting (spotify trackTimeMillis/1000, soundcloud
// /1000, youtube "mm:ss"). player.js ships this exact normalizer for the same
// value; lyrics.js used an ad-hoc `> 10000` threshold instead, which
// disagreed with the player for anything above 2.8 h stored in seconds
// (podcasts/long mixes became "10 s") and would disagree for the 10-50 s
// band the other way. One shared rule: a value above 50000 cannot be seconds
// (13.9 h), so it passes through as milliseconds; anything else is seconds.
function normalizeDurationMs(dur) {
    const d = Number(dur);
    if (!d || isNaN(d) || d <= 0) return 0;
    return d > 50000 ? Math.round(d) : Math.round(d * 1000);
}

function lyricsTrackKey(track) {
    // Stream URLs expire and can arrive after track_changed. Only local paths
    // affect embedded lyrics; resolving a CDN URL must keep the same lookup.
    const path = track?.file_path || '';
    return track ? JSON.stringify([track.source || 'local', track.source_id || track.id || '',
        track.title || '', track.artist || '', track.album || '', /^https?:\/\//i.test(path) ? '' : path]) : '';
}

function rememberLyrics(data) {
    if (!lastLoadedTrackKey || data?.phase === 'partial' || (!data?.plainLyrics && !data?.syncedLyrics)) return;
    lyricsMemoryCache.delete(lastLoadedTrackKey);
    lyricsMemoryCache.set(lastLoadedTrackKey, {data: {...data}, durationMs: requestedLyricsDurationMs});
    while (lyricsMemoryCache.size > LYRICS_MEMORY_CACHE_LIMIT) {
        lyricsMemoryCache.delete(lyricsMemoryCache.keys().next().value);
    }
}

// Build the line-text -> translation map the renderers consume.
//
// Every display surface (synced sheet, plain sheet, player page panel and the
// PiP widget via the lyrics:line-changed event) looks translations up by the
// ORIGINAL line text, so the backend's full translated text has to be aligned
// line-by-line here. The bridge answers {'success': True, 'text': <str>,
// 'error': None} (core/api.py get_lyrics_translation) -- the envelope itself
// was once assigned as the map, which keyed every lookup by 'success'/'text'/
// 'error' and left all three surfaces permanently without subtitles
// (BUG-L2-001). Both response shapes funnel through this one builder.
function buildTranslationMap(res, cleanText) {
    let translated;
    if (typeof res === 'string') {
        translated = res;
    } else {
        if (!res || res.success === false || res.error) throw new Error('Translation unavailable');
        translated = String(res.text ?? '');
    }
    if (!translated.trim() || translated.trim() === cleanText.trim()) throw new Error('Translation unavailable');
    // Backend returns full translated text: align line-by-line with parsedLyrics
    const transLines = translated.split(/\r?\n/).map(s => s.trim());
    const origLines = cleanText.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    const map = {};
    // Prefer parsedLyrics order (synced), fallback to raw order
    const keys = parsedLyrics.length > 0 ? parsedLyrics.map(l => l.text) : origLines;
    keys.forEach((k, i) => {
        const trans = (k && transLines[i] && transLines[i] !== k)
            ? transLines[i]
            : (k && origLines[i] && transLines[i] && transLines[i] !== origLines[i] ? transLines[i] : null);
        if (trans) {
            if (!map[k]) map[k] = trans;
            if (origLines[i] && !map[origLines[i]]) map[origLines[i]] = trans;
            Object.defineProperty(map, i, { value: trans, enumerable: false, writable: true, configurable: true });
            Object.defineProperty(map, `${i}:${k}`, { value: trans, enumerable: false, writable: true, configurable: true });
            if (origLines[i]) Object.defineProperty(map, `${i}:${origLines[i]}`, { value: trans, enumerable: false, writable: true, configurable: true });
        }
    });
    // If line counts mismatch, fall back to index alignment with origLines
    if (Object.keys(map).length === 0) {
        origLines.forEach((k, i) => {
            if (k && transLines[i] && transLines[i] !== k) {
                if (!map[k]) map[k] = transLines[i];
                Object.defineProperty(map, i, { value: transLines[i], enumerable: false, writable: true, configurable: true });
                Object.defineProperty(map, `${i}:${k}`, { value: transLines[i], enumerable: false, writable: true, configurable: true });
            }
        });
    }
    return map;
}

export function toggleTranslation(forceState = null) {
    isTranslationEnabled = typeof forceState === 'boolean' ? forceState : !isTranslationEnabled;
    const btns = [
        document.getElementById('btn-toggle-lyrics-translation'),
        document.getElementById('btn-toggle-lyrics-translation-page')
    ].filter(Boolean);

    btns.forEach(btnTrans => {
        btnTrans.classList.toggle('active', isTranslationEnabled);
        btnTrans.style.background = '';
        btnTrans.style.color = '';
        btnTrans.style.borderColor = '';
    });

    if (isTranslationEnabled && Object.keys(currentTranslationMap).length === 0 && currentRawLyricsText) {
        if (window.pywebview?.api?.get_lyrics_translation) {
            // BUG-L2-007: a long translation occupies the bridge for seconds —
            // disable the buttons so repeated clicks cannot stack duplicate
            // requests; re-enabled by every completion path below.
            btns.forEach(b => { b.disabled = true; });
            const enableButtons = () => btns.forEach(b => { b.disabled = false; });
            window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Переводим текст песни...', type: 'info' } }));
            // Strip LRC timestamps: backend translates plain lines, not "[00:12.34]" tags
            const cleanText = String(currentRawLyricsText).replace(/\[\d{1,2}:\d{2}(?:\.\d{1,3})?\]/g, '').replace(/^\s*\n/gm, '\n').trim();
            const translationTrackKey = lastLoadedTrackKey;
            window.pywebview.api.get_lyrics_translation(cleanText, 'ru').then(res => {
                enableButtons();
                if (translationTrackKey !== lastLoadedTrackKey || cleanPlainLyrics(currentRawLyricsText).join('\n') !== cleanPlainLyrics(cleanText).join('\n')) return;
                currentTranslationMap = buildTranslationMap(res, cleanText);
                renderLyrics(lastLyricsData, true);
            }).catch(err => {
                enableButtons();
                console.error("Translation failed:", err);
                if (translationTrackKey !== lastLoadedTrackKey) return;
                toggleTranslation(false);
                window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Перевод недоступен. Попробуйте ещё раз.', type: 'error' } }));
            });
        }
    } else {
        renderLyrics(lastLyricsData, true);
    }
}

export function updateOffsetBadges() {
    const text = (currentOffsetMs === 0) ? '0.0s' : `${currentOffsetMs > 0 ? '+' : ''}${(currentOffsetMs / 1000).toFixed(1)}s`;
    const badges = [
        document.getElementById('btn-lyrics-offset-reset'),
        document.getElementById('btn-lyrics-offset-reset-page')
    ].filter(Boolean);
    badges.forEach(b => {
        b.textContent = text;
        if (currentOffsetMs !== 0) {
            b.style.borderColor = 'var(--color-primary, var(--primary, #f43f5e))';
            b.style.color = 'var(--color-primary, var(--primary, #f43f5e))';
            b.style.fontWeight = '700';
        } else {
            b.style.borderColor = '';
            b.style.color = '';
            b.style.fontWeight = '';
        }
    });
}

export function resetLyricsOffset() {
    currentOffsetMs = 0;
    updateOffsetBadges();
    const track = getCurrentTrack();
    if (track) {
        const trackKey = String(track.source_id || track.id || track.title || '');
        if (trackKey) {
            try {
                localStorage.removeItem(`nedotify_lyrics_offset_${trackKey}`);
            } catch(e) {}
            if (window.pywebview?.api?.save_setting) {
                window.pywebview.api.save_setting(`lyrics_offset_${trackKey}`, 0, 'lyrics');
            }
        }
    }
    try {
        localStorage.removeItem('nedotify_lyrics_offset_current');
    } catch(e) {}
    window.dispatchEvent(new CustomEvent('nedotify:toast', {
        detail: { msg: 'Смещение текста сброшено на 0.0s', type: 'info' }
    }));
    currentLineIndex = -1;
    updateLyricsPosition(lastPosMs);
}

// The offset only means something for timed lyrics: updateLyricsPosition()
// returns immediately when parsedLyrics is empty, so on plain lyrics the buttons
// moved the badge and did nothing else. Disable them instead of shipping a
// control that silently does nothing.
export function setOffsetControlsEnabled(enabled) {
    const ids = [
        'btn-lyrics-offset-minus', 'btn-lyrics-offset-reset', 'btn-lyrics-offset-plus',
        'btn-lyrics-offset-minus-page', 'btn-lyrics-offset-reset-page', 'btn-lyrics-offset-plus-page'
    ];
    ids.forEach(id => {
        const b = document.getElementById(id);
        if (!b) return;
        b.disabled = !enabled;
        b.style.opacity = enabled ? '' : '0.4';
        b.style.cursor = enabled ? '' : 'not-allowed';
        b.title = enabled
            ? 'Сдвинуть текст по времени'
            : 'Смещение доступно только для синхронизированного текста';
    });
}

export function adjustLyricsOffset(deltaMs) {
    currentOffsetMs += deltaMs;
    updateOffsetBadges();
    window.dispatchEvent(new CustomEvent('nedotify:toast', {
        detail: {
            msg: `Смещение текста: ${currentOffsetMs > 0 ? '+' : ''}${(currentOffsetMs / 1000).toFixed(1)}s`,
            type: 'info'
        }
    }));
    const track = getCurrentTrack();
    if (track) {
        const trackKey = String(track.source_id || track.id || track.title || '');
        if (trackKey) {
            try {
                localStorage.setItem(`nedotify_lyrics_offset_${trackKey}`, String(currentOffsetMs));
            } catch(e) {}
            if (window.pywebview?.api?.save_setting) {
                window.pywebview.api.save_setting(`lyrics_offset_${trackKey}`, currentOffsetMs, 'lyrics');
            }
        }
    }
    currentLineIndex = -1;
    updateLyricsPosition(lastPosMs);
}

export function invalidateLyricsKineticLayout() {
    getContainers().forEach(track => {
        const st = track._kinetic;
        if (!st) return;
        st.dirty = true;
        st.measured = false;
        measureViewport(st);
        if (st.activeEl) {
            focusActiveLine(st, false);
        }
    });
}

export function reloadCurrentTrackLyrics(forceNetwork = true) {
    if (lastLoadedTrackKey) {
        lyricsMemoryCache.delete(lastLoadedTrackKey);
    }
    lastLyricsData = null;
    loadCurrentTrackLyrics(0, forceNetwork);
}

export function getCurrentLyricsData() {
    return lastLyricsData;
}

function resumeDeferredLyrics() {
    const pending = deferredLyricsRequest;
    if (!pending) return;
    const track = getCurrentTrack();
    if (!track || lyricsTrackKey(track) !== pending.trackKey) {
        deferredLyricsRequest = null;
        return;
    }
    const clock = getLyricsPlaybackClock();
    if ((track.stream_url || track.file_path) && !clock.paused && !clock.buffering && clock.positionMs > 0) {
        loadCurrentTrackLyrics(pending.durationMs);
    }
}

export function initLyrics() {
    if (lyricsInitialized) return;
    lyricsInitialized = true;
    const btn = document.getElementById('pp-btn-lyrics');
    const closeBtn = document.getElementById('btn-close-lyrics') || document.getElementById('lyrics-close');
    const overlay = document.getElementById('lyrics-overlay');

    window.NeDotify = window.NeDotify || {};
    window.NeDotify.loadCurrentTrackLyrics = loadCurrentTrackLyrics;
    window.NeDotify.updateLyricsPosition = updateLyricsPosition;
    window.NeDotify.adjustLyricsOffset = adjustLyricsOffset;
    window.NeDotify.resetLyricsOffset = resetLyricsOffset;
    window.NeDotify.setOffsetControlsEnabled = setOffsetControlsEnabled;
    window.NeDotify.toggleTranslation = toggleTranslation;
    window.NeDotify.invalidateLyricsKineticLayout = invalidateLyricsKineticLayout;
    window.NeDotify.reloadCurrentTrackLyrics = reloadCurrentTrackLyrics;
    window.NeDotify.getCurrentLyricsData = getCurrentLyricsData;
    window.NeDotify.openLyricsSettingsPopover = openLyricsSettingsPopover;
    window.NeDotify.openLyricsSearchModal = openLyricsSearchModal;
    window.NeDotify.openLyricsCustomModal = openLyricsCustomModal;

    initLyricsSettingsPopover();
    initLyricsSearchModal();
    initLyricsCustomModal();

    // Purge stale unbounded global offset from previous buggy sessions
    try { localStorage.removeItem('nedotify_lyrics_offset_current'); } catch(e) {}

    if (btn) {
        btn.addEventListener('click', () => {
            if (overlay) {
                if (overlay.classList.contains('active')) {
                    isOverlayVisible = false;
                    overlay.classList.remove('active');
                } else {
                    isOverlayVisible = true;
                    overlay.classList.add('active');
                    loadCurrentTrackLyrics();
                }
            }
        });
    }

    // Focal-point geometry is derived from the measured viewport, so both the
    // resize path and the webfont swap have to re-anchor the sheet.
    bindKineticResize();
    bindFontsReady();

    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            if (overlay) {
                isOverlayVisible = false;
                overlay.classList.remove('active');
            }
        });
    }

    // Close overlay on Escape key or backdrop click
    if (overlay) {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                isOverlayVisible = false;
                overlay.classList.remove('active');
            }
        });
    }

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && overlay && overlay.classList.contains('active')) {
            isOverlayVisible = false;
            overlay.classList.remove('active');
        }
    });

    const btnMinus = document.getElementById('btn-lyrics-offset-minus');
    const btnReset = document.getElementById('btn-lyrics-offset-reset');
    const btnPlus = document.getElementById('btn-lyrics-offset-plus');
    const btnTrans = document.getElementById('btn-toggle-lyrics-translation');

    const btnMinusPage = document.getElementById('btn-lyrics-offset-minus-page');
    const btnResetPage = document.getElementById('btn-lyrics-offset-reset-page');
    const btnPlusPage = document.getElementById('btn-lyrics-offset-plus-page');
    const btnTransPage = document.getElementById('btn-toggle-lyrics-translation-page');

    // Hold-to-repeat. Each click is only 0.5s, so reaching a usable offset takes
    // many clicks; holding accelerates after a short delay, the way volume
    // controls do. Disabled buttons ignore the press entirely.
    const bindOffsetRepeat = (button, stepMs) => {
        if (!button) return;
        let holdTimer = null, repeatTimer = null;
        const stop = () => {
            if (holdTimer) { clearTimeout(holdTimer); holdTimer = null; }
            if (repeatTimer) { clearInterval(repeatTimer); repeatTimer = null; }
        };
        button.addEventListener('pointerdown', (e) => {
            if (button.disabled) return;
            e.preventDefault();
            adjustLyricsOffset(stepMs);
            holdTimer = setTimeout(() => {
                repeatTimer = setInterval(() => adjustLyricsOffset(stepMs), 90);
            }, 450);
        });
        ['pointerup', 'pointerleave', 'pointercancel'].forEach(ev =>
            button.addEventListener(ev, stop));
        // Keyboard activation must not leave a repeat running.
        button.addEventListener('keyup', stop);
        button.addEventListener('blur', stop);
    };

    bindOffsetRepeat(btnMinus, -500);
    bindOffsetRepeat(btnPlus, 500);
    bindOffsetRepeat(btnMinusPage, -500);
    bindOffsetRepeat(btnPlusPage, 500);

    if (btnReset) btnReset.addEventListener('click', () => resetLyricsOffset());
    if (btnResetPage) btnResetPage.addEventListener('click', () => resetLyricsOffset());
    if (btnTrans) btnTrans.addEventListener('click', () => toggleTranslation());
    if (btnTransPage) btnTransPage.addEventListener('click', () => toggleTranslation());

    // Listen to track/position events dispatched by events.js via custom events
    document.addEventListener('nedotify:track_changed', () => {
        clearWordLyrics();
        loadCurrentTrackLyrics();
    });

    // Time synchronization: nedotify:position_changed provides position in milliseconds (posMs / pos).
    // Parsed LRC timestamps (parseLrc) are in milliseconds (timeMs).
    // Standardized to milliseconds for pixel-perfect kinetic lyrics synchronization.
    document.addEventListener('nedotify:position_changed', (e) => {
        const posMs = e.detail?.posMs !== undefined ? e.detail.posMs : (typeof e.detail?.pos === 'number' ? e.detail.pos : 0);
        resumeDeferredLyrics();
        updateLyricsPosition(posMs);
        syncWordLyrics();
        const durationMs = Number(e.detail?.durationMs ?? e.detail?.duration);
        if (!requestedLyricsDurationMs && durationMs > 0 && lastLoadedTrackKey) {
            loadCurrentTrackLyrics(durationMs);
        }
    });

    document.addEventListener('nedotify:lyrics_ready', (e) => {
        if (e.detail?.request_id !== activeLyricsRequestId) return;
        renderLyrics(e.detail);
    });
    document.addEventListener('nedotify:lyrics_clock_changed', syncWordLyrics);
    document.addEventListener('nedotify:lyrics_clock_changed', resumeDeferredLyrics);
    document.addEventListener('visibilitychange', syncWordLyrics);
    window.addEventListener('nedotify:lyrics_settings_changed', () => {
        renderLyrics(lastLyricsData, true);
    });
    window.addEventListener('nedotify:appearance_changed', syncWordLyrics);
    window.addEventListener('nedotify:page_changed', syncWordLyrics);
}

// ==========================================================================
// KINETIC TRANSFORM ENGINE (Apple Music style)
// ==========================================================================
//
// The sheet is positioned by a single translateY() on the track instead of
// native scrolling. Native scrolling was the source of the stepped, discrete
// motion: every line change ran scrollTo(..., 'smooth'), which Chromium
// restarts from scratch, so lines visibly snapped line-to-line. One transform
// written once per index change, animated by one springy CSS transition, is
// continuous and costs the compositor nothing.
//
// Geometry contract:
//   viewport  clips (overflow:hidden) and supplies the focal line at 45% height
//   track     position:relative, so line.offsetTop is already track-local
//   track pad top    = 45% of viewport height  -> line 1 can reach the focal line
//   track pad bottom = 55% of viewport height  -> the last line can too
// ==========================================================================

// Where the active line's centre sits, as a fraction of viewport height.
// 0.45 rather than a dead 0.5: the active line is optically centred but the
// small remainder below it keeps the next lines in frame, so the sheet does not
// look like it is sitting low in an empty box.
const LYRICS_FOCAL_RATIO = 0.45;

// Past-the-edge damping. 1.0 tracks the pointer exactly (a hard stop at the
// padding limit reads as a broken scroller); 0.35 gives the elastic give.
const RUBBER_BAND_FACTOR = 0.35;

// Wheel deltas arrive in lines on some WebView2/Chromium configurations.
const LINE_HEIGHT_PX = 16;

// Auto-follow stays suspended this long after the user's last wheel/drag, so
// browsing the sheet is not fought by the karaoke follow.
const MANUAL_SCROLL_PAUSE_MS = 4000;

// Module-level: a single "user is browsing" clock shared by both sheets. Only
// one sheet is ever visible, so per-container bookkeeping here would just add
// state that has to be kept in sync.
let lastManualScrollAt = 0;
let followResumeTimer = null;
let kineticResizeObserver = null;
let kineticListenersBound = false;

/**
 * True only while the user is actively browsing the sheet.
 *
 * The `lastManualScrollAt !== 0` guard is load-bearing, not defensive: 0 is the
 * "never browsed" sentinel and performance.now() starts near 0 on page load, so
 * `now - 0` is a *small* number. Testing the difference alone would report
 * "browsing" for the first MANUAL_SCROLL_PAUSE_MS of the app's life, and the
 * karaoke follow would silently never run.
 */
function isManualBrowsing() {
    return lastManualScrollAt !== 0 &&
           (performance.now() - lastManualScrollAt) < MANUAL_SCROLL_PAUSE_MS;
}

/**
 * The scrolling sheet elements. Kept as one call site so both the panel and
 * the overlay stay in lockstep.
 * @returns {HTMLElement[]} the `.lyrics-track` nodes.
 */
function getContainers() {
    return [
        document.getElementById('lyrics-content'),
        document.getElementById('overlay-lyrics-content')
    ].filter(Boolean);
}

function resolveViewport(track) {
    const parent = track.parentElement;
    if (parent && parent.classList.contains('lyrics-viewport')) return parent;
    return track.closest('.player-lyrics-container, .lyrics-scroll-container') || parent || track;
}

/**
 * Per-sheet kinematic state. Attached to the DOM node rather than kept in a
 * module variable because there are two independent sheets (panel + overlay)
 * with their own measurements, offsets and interaction state.
 */
function ensureKineticState(track) {
    let st = track._kinetic;
    if (st) return st;
    st = track._kinetic = {
        track,
        viewport: resolveViewport(track),
        lines: [],
        activeEl: null,
        lastIndex: -1,
        manual: 0,       // extra px the user dragged/wheeled past the focal line
        base: 0,         // transform for the focal line, negative
        applied: '',     // last transform string written, to skip no-op writes
        vpH: 0,
        trackH: 0,
        minY: 0,         // most negative allowed translateY (bottom of the sheet)
        measured: false,
        dirty: true,     // line cache must be rebuilt (sheet was re-rendered)
        dragging: false,
        pointerId: null,
        dragStartY: 0,
        dragStartManual: 0,
        moved: false
    };
    bindKineticInput(st);
    return st;
}

/**
 * Re-measure and rebuild the line cache. Called after every re-render, since
 * renderLyrics() replaces the sheet's children wholesale.
 */
function refreshKineticState(track) {
    const st = ensureKineticState(track);
    st.lines = Array.prototype.slice.call(track.querySelectorAll('.lyric-line'));
    st.dirty = false;
    return st;
}

/**
 * Apply the focal-space padding and the scroll bounds.
 *
 * The padding is written in px rather than left to the CSS defaults because a
 * percentage padding resolves against the box *width*, not its height — a
 * 35%-of-viewport focal space cannot be expressed in CSS.
 * @returns {boolean} false when the sheet is not laid out (hidden panel).
 */
function measureViewport(st) {
    const vpH = st.viewport.clientHeight;
    if (!vpH) return false;               // hidden panel: nothing meaningful to measure
    st.vpH = vpH;
    st.track.style.paddingTop = Math.round(vpH * LYRICS_FOCAL_RATIO) + 'px';
    st.track.style.paddingBottom = Math.round(vpH * (1 - LYRICS_FOCAL_RATIO)) + 'px';
    st.trackH = st.track.offsetHeight;
    // A sheet shorter than its viewport cannot move at all.
    st.minY = Math.min(0, vpH - st.trackH);
    st.measured = true;
    return true;
}

function ensureMeasured(st) {
    if (!st.measured || st.vpH !== st.viewport.clientHeight) measureViewport(st);
    return st.measured;
}

/**
 * Transform that puts a line's centre on the focal line, clamped to the scroll
 * bounds. Uses offsetTop/clientHeight (layout-local) rather than
 * getBoundingClientRect, which would force a full paint-time flush.
 *
 * The focal offset is a *distance*, so the translate is its negation: the line
 * has to travel upward out of the sheet, never downward.
 * @param {object} st
 * @param {HTMLElement} lineEl
 * @returns {number} translateY in px (negative, or 0 at the very top).
 */
function focalOffsetFor(st, lineEl) {
    if (!lineEl) return 0;
    const distance = lineEl.offsetTop - (st.vpH * LYRICS_FOCAL_RATIO) + (lineEl.clientHeight / 2);
    const y = -distance;
    return Math.max(st.minY, Math.min(0, y));
}

/**
 * Write the track transform. The only place in this module that touches
 * `.style.transform`, so the write can be deduped.
 * @param {object} st
 * @param {number} y translateY in px (negative).
 * @param {boolean} animate false for resize/re-render/wheel frames.
 */
function applyTransform(st, y, animate) {
    // Toggle before the dedup check: an identical value still has to land with
    // the right animation mode, otherwise a sheet left in no-anim stays frozen
    // for every subsequent identical write.
    st.track.classList.toggle('no-anim', !animate);
    const next = 'translate3d(0,' + y.toFixed(2) + 'px,0)';
    if (next === st.applied) return;
    st.applied = next;
    st.track.style.transform = next;
}

/**
 * Allowed range for `manual`, expressed so that y = base - manual stays within
 * [minY, 0]:
 *   manual = base        -> y = 0      (very top of the sheet)
 *   manual = base - minY -> y = minY   (very bottom)
 *   manual = 0           -> y = base   (focal line centred)
 */
function manualRange(st) {
    return { lo: st.base, hi: st.base - st.minY };
}

/**
 * Constrain a desired manual offset to the scroll bounds, damping whatever falls
 * outside so the sheet can be pulled past the end and springs back.
 * @param {object} st
 * @param {number} desired raw offset from the gesture.
 * @returns {number} the damped offset.
 */
function clampManual(st, desired) {
    const { lo, hi } = manualRange(st);
    if (desired < lo) return lo + (desired - lo) * RUBBER_BAND_FACTOR;
    if (desired > hi) return hi + (desired - hi) * RUBBER_BAND_FACTOR;
    return desired;
}

function writeManual(st, manual, animate) {
    st.manual = manual;
    applyTransform(st, st.base - st.manual, animate);
}

/**
 * Swap `.active` / `.past` across the sheet.
 *
 * Only the lines between the old and the new index change state, so a seek
 * across a long sheet costs a handful of class writes rather than a full pass.
 * @param {object} st
 * @param {number} newIndex -1 for "before the first line".
 */
function updateLineClasses(st, newIndex) {
    const lines = st.lines;
    const oldIndex = st.lastIndex;

    if (st.activeEl) {
        st.activeEl.classList.remove('active');
        st.activeEl = null;
    }

    // `.past` is a contiguous prefix [0, newIndex), so clearing the old
    // boundary is enough — never touch the untouched middle of the sheet.
    if (newIndex > oldIndex) {
        for (let i = Math.max(0, oldIndex); i < newIndex; i++) {
            if (lines[i]) lines[i].classList.add('past');
        }
    } else if (newIndex < oldIndex) {
        for (let i = Math.max(0, newIndex); i < oldIndex; i++) {
            if (lines[i]) lines[i].classList.remove('past');
        }
    }

    if (newIndex !== -1 && lines[newIndex]) {
        lines[newIndex].classList.add('active');
        st.activeEl = lines[newIndex];
    }

    st.lastIndex = newIndex;
}

/**
 * Recentre the sheet on the active line unless the user is browsing it.
 *
 * @param {object} st
 * @param {boolean} animate
 */
function focusActiveLine(st, animate) {
    st.base = focalOffsetFor(st, st.activeEl);
    if (isManualBrowsing()) {
        // Freeze the focal point under the user; the resume timer re-anchors it.
        return;
    }
    st.manual = 0;
    applyTransform(st, st.base, animate);
}

/**
 * Wheel + drag scrubbing. The viewport no longer scrolls natively, so both
 * gestures are mapped onto `manual` (see manualRange).
 *
 * Bound once per sheet. The listeners stay on the viewport and use an internal
 * dragging flag rather than per-drag document listeners, so a sheet re-render
 * cannot orphan a live drag the way add/removeEventListener juggling can.
 */
function bindKineticInput(st) {
    const vp = st.viewport;

    // Wheel: direct manipulation, so no transition — a spring here would lag
    // the wheel and feel like ice.
    vp.addEventListener('wheel', (e) => {
        if (!ensureMeasured(st)) return;
        e.preventDefault();
        const delta = e.deltaMode === 1 ? e.deltaY * LINE_HEIGHT_PX
            : e.deltaMode === 2 ? e.deltaY * st.vpH
                : e.deltaY;
        if (!delta) return;
        // Scrolling down reveals later lines, i.e. a larger manual offset,
        // because the transform is y = base - manual.
        markManualInput();
        writeManual(st, clampManual(st, st.manual + delta), false);
    }, { passive: false });

    let dragMoved = false;

    vp.addEventListener('pointerdown', (e) => {
        if (e.button !== 0 || !ensureMeasured(st)) return;
        st.dragging = true;
        st.pointerId = e.pointerId;
        st.dragStartY = e.clientY;
        st.dragStartManual = st.manual;
        st.moved = false;
        dragMoved = false;
        markManualInput();
    });

    vp.addEventListener('pointermove', (e) => {
        if (!st.dragging || e.pointerId !== st.pointerId) return;
        const dy = e.clientY - st.dragStartY;
        // Below the threshold this is a click on a line, not a scrub.
        if (!dragMoved && Math.abs(dy) < 4) return;
        if (!dragMoved) {
            dragMoved = true;
            st.moved = true;
            // Capturing on pointerdown retargets the later click to the
            // viewport, swallowing ordinary clicks on a word or lyric line.
            try { vp.setPointerCapture(e.pointerId); } catch (_) { /* not capturable */ }
            vp.classList.add('is-dragging');
        }
        markManualInput();
        // Dragging down brings earlier lines into view: y = base - manual, so
        // downward travel decreases manual. The origin is re-read every frame
        // instead of accumulating, so the sheet cannot drift on rubber band.
        writeManual(st, clampManual(st, st.dragStartManual - dy), false);
    });

    const endDrag = (e) => {
        if (!st.dragging || (e.pointerId !== undefined && e.pointerId !== st.pointerId)) return;
        st.dragging = false;
        vp.classList.remove('is-dragging');
        try { vp.releasePointerCapture(st.pointerId); } catch (_) { /* already gone */ }
        if (dragMoved) {
            // Settle back inside the bounds with the spring, so releasing at the
            // elastic edge eases home instead of stopping dead.
            const { lo, hi } = manualRange(st);
            writeManual(st, Math.max(lo, Math.min(hi, st.manual)), true);
        }
    };

    vp.addEventListener('pointerup', endDrag);
    vp.addEventListener('pointercancel', endDrag);
    vp.addEventListener('pointerleave', event => { if (!dragMoved) endDrag(event); });
    vp.addEventListener('lostpointercapture', endDrag);

    // A scrub must not also register as a line click (which would seek). The
    // flag is cleared here rather than in endDrag because click fires after
    // pointerup.
    vp.addEventListener('click', (e) => {
        if (st.moved) {
            e.stopPropagation();
            e.preventDefault();
        }
        st.moved = false;
    }, true);
}

/**
 * Flag user browsing and arm the auto-follow resume.
 *
 * The resume is timer-driven rather than riding the next position tick: when
 * playback is paused there are no ticks at all, so a tick-driven resume would
 * never fire and the sheet would stay parked wherever the user left it.
 */
function markManualInput() {
    lastManualScrollAt = performance.now();
    if (followResumeTimer) clearTimeout(followResumeTimer);
    followResumeTimer = setTimeout(resumeAutoFollow, MANUAL_SCROLL_PAUSE_MS + 60);
}

function resumeAutoFollow() {
    followResumeTimer = null;
    if (isManualBrowsing()) return;         // a new gesture re-armed the timer
    lastManualScrollAt = 0;
    getContainers().forEach(track => {
        const st = track._kinetic;
        if (!st || !st.measured || !st.activeEl) return;
        st.base = focalOffsetFor(st, st.activeEl);
        writeManual(st, 0, true);
    });
}

/**
 * Re-measure on viewport resize. The focal point is a fraction of the viewport,
 * so a resize invalidates both the padding and every cached offsetTop.
 */
function bindKineticResize() {
    if (kineticResizeObserver) return;
    const ro = new ResizeObserver((entries) => {
        let visible = false;
        for (const entry of entries) {
            if (entry.contentRect.height > 0) visible = true;
        }
        // Skip the burst of callbacks while the window is being dragged.
        if (!visible) return;
        getContainers().forEach(track => {
            const st = track._kinetic;
            if (!st || !measureViewport(st)) return;
            st.base = focalOffsetFor(st, st.activeEl);
            const { lo, hi } = manualRange(st);
            writeManual(st, Math.max(lo, Math.min(hi, st.manual)), false);
        });
    });
    getContainers().forEach(track => ro.observe(ensureKineticState(track).viewport));
    kineticResizeObserver = ro;
}

/**
 * Font swap changes every line height, so offsets measured against the fallback
 * face are wrong. Re-anchor once the real faces are in.
 */
function bindFontsReady() {
    if (kineticListenersBound || !document.fonts || !document.fonts.ready) return;
    kineticListenersBound = true;
    document.fonts.ready.then(() => {
        getContainers().forEach(track => {
            const st = track._kinetic;
            if (!st || !st.measured) return;
            st.base = focalOffsetFor(st, st.activeEl);
            applyTransform(st, st.base - st.manual, false);
        });
    }).catch(() => { /* font loading failed: keep the measured layout */ });
}

/**
 * Reset the sheet to its neutral pose. Called whenever the content is replaced.
 */
function resetLyricsScroll() {
    currentLineIndex = -1;
    // A new track starts a new karaoke run, so do not inherit a browse pause
    // left over from the user scrolling the previous one.
    lastManualScrollAt = 0;
    getContainers().forEach(track => {
        const st = ensureKineticState(track);
        st.lines = [];
        st.activeEl = null;
        st.lastIndex = -1;
        st.dirty = true;
        st.measured = false;
        st.manual = 0;
        st.base = 0;
        st.minY = 0;
        st.dragging = false;
        st.moved = false;
        st.track.classList.remove('is-dragging');
        st.track.style.paddingTop = '';
        st.track.style.paddingBottom = '';
        // Land at the top of the sheet without animating in from the previous
        // track's position.
        st.applied = '';
        applyTransform(st, 0, false);
    });
}

export function loadCurrentTrackLyrics(durationOverrideMs = 0, forceNetwork = false) {
    deferredLyricsRequest = null;
    const track = getCurrentTrack();
    const containers = getContainers();
    
    // Sync overlay title
    const titleEl = document.getElementById('lyrics-title');
    if (titleEl) {
        titleEl.textContent = track ? (track.title + (track.artist ? ' — ' + track.artist : '')) : 'Текст песни';
    }

    if (!track) {
        clearWordLyrics();
        parsedLyrics = [];
        currentLineIndex = -1;
        activeLyricsRequestId = null;
        pendingLyricsRequest = null;
        lastLoadedTrackKey = '';
        lastLyricsData = null;
        requestedLyricsDurationMs = 0;
        lyricsLoadGeneration++;
        containers.forEach(c => c.innerHTML = '<div class="empty-state">Трек не выбран</div>');
        return;
    }

    const trackKey = lyricsTrackKey(track);
    const metadataDurationMs = normalizeDurationMs(track.duration);
    const durMs = durationOverrideMs || metadataDurationMs || (trackKey === lastLoadedTrackKey ? requestedLyricsDurationMs : 0);

    // Reopening the overlay while a lookup is running must share that request,
    // including its id and streamed plain -> synced upgrades.
    if (pendingLyricsRequest?.trackKey === trackKey &&
        pendingLyricsRequest.durationMs === durMs &&
        Date.now() - pendingLyricsRequest.startedAt < LYRICS_PENDING_MAX_AGE_MS) return;

    // If lyrics are already loaded in memory for this exact track, render immediately without flashing
    if (trackKey && trackKey === lastLoadedTrackKey && lastLyricsData &&
        lastLyricsData.phase !== 'partial' &&
        (!durMs || requestedLyricsDurationMs === durMs) &&
        (lastLyricsData.syncedLyrics || lastLyricsData.plainLyrics)) {
        renderLyrics(lastLyricsData, true);
        return;
    }

    const cached = lyricsMemoryCache.get(trackKey);
    const cachedData = cached && (!durMs || cached.durationMs === durMs) ? cached.data : null;

    const preserve = Boolean(durationOverrideMs && trackKey === lastLoadedTrackKey && lastLyricsData && (lastLyricsData.plainLyrics || lastLyricsData.syncedLyrics));
    lastLoadedTrackKey = trackKey;
    if (!preserve) lastLyricsData = null;
    if (!preserve) resetLyricsScroll();

    if (!preserve) {
        containers.forEach(c => c.innerHTML = '<div class="empty-state"><div class="spinner"></div>Ищем текст...</div>');
        parsedLyrics = [];
        currentLineIndex = -1;
        currentTranslationMap = {};
        currentRawLyricsText = '';
        currentOffsetMs = 0;
    }

    // Bump generation — only the freshest request may render
    const loadGen = ++lyricsLoadGeneration;
    activeLyricsRequestId = `lyrics-${Date.now()}-${loadGen}`;
    lastLyricsRevision = 0;
    pendingLyricsRequest = null;
    requestedLyricsDurationMs = cachedData ? cached.durationMs : durMs;

    if (trackKey && !preserve) {
        try {
            const offsetKey = String(track.source_id || track.id || track.title || '');
            const legacyKey = `${track.source || 'local'}:${track.source_id || track.id || ''}:${track.title || ''}:${track.artist || ''}:${track.album || ''}`;
            const saved = localStorage.getItem(`nedotify_lyrics_offset_${offsetKey}`) ??
                localStorage.getItem(`nedotify_lyrics_offset_${legacyKey}`) ??
                window.settings?.lyrics?.[`lyrics_offset_${offsetKey}`];
            if (saved !== null && saved !== undefined) {
                currentOffsetMs = parseInt(saved, 10) || 0;
            }
        } catch(e) {
            currentOffsetMs = 0;
        }
    }
    updateOffsetBadges();

    // Successful revisits render synchronously. Failures are never retained, so
    // the retry button and recovery after a provider outage still perform I/O.
    if (cachedData) {
        renderLyrics(cachedData);
        return;
    }
    
    // Provider lyric cascades share the network with initial stream resolution.
    // Cached text above and local sidecars stay immediate; an autoplay lookup
    // starts only after this track has decoded audio and its clock has advanced.
    const localFile = track.file_path && !/^https?:/i.test(track.file_path);
    const clock = getLyricsPlaybackClock();
    const audioReady = Boolean(track.stream_url || track.file_path) &&
        !clock.paused && !clock.buffering && clock.positionMs > 0;
    if (!forceNetwork && track.autoplay === true && track.source !== 'local' &&
        !localFile && !audioReady) {
        deferredLyricsRequest = {trackKey, durationMs: durMs};
        containers.forEach(c => {
            c.innerHTML = '<div class="empty-state"><span>Текст появится после начала воспроизведения</span><button type="button" class="home-pill">Найти сейчас</button></div>';
            c.querySelector('button')?.addEventListener('click', () => loadCurrentTrackLyrics(0, true));
        });
        return;
    }

    if (window.pywebview?.api?.get_lyrics) {
        pendingLyricsRequest = {trackKey, durationMs: durMs, id: activeLyricsRequestId, startedAt: Date.now()};
        let p;
        try {
            p = window.pywebview.api.get_lyrics(track.title, track.artist, durMs, track.file_path, track.album || '', activeLyricsRequestId, track.source || '', track.source_id || '');
        } catch (err) {
            pendingLyricsRequest = null;
            console.error("get_lyrics error:", err);
            renderLyrics(null);
            return;
        }
        
        if (p && typeof p.then === 'function') {
            p.then(res => {
                if (loadGen !== lyricsLoadGeneration) return;
                // Backend returns {"status": "loading"} instantly; real data comes via lyrics_ready
                if (res && res.status === 'loading') return;
                if (res) {
                    renderLyrics(res);
                } else {
                    renderLyrics(null);
                }
            }).catch(err => {
                if (loadGen !== lyricsLoadGeneration) return;
                console.error("get_lyrics error:", err);
                renderLyrics(null);
            });
        } else if (p?.status !== 'loading') {
            renderLyrics(p || null);
        }
    } else {
        renderLyrics(null);
    }
}

function cleanPlainLyrics(plainText) {
    if (!plainText) return [];
    return plainText.split(/\r?\n/)
        .map(l => l.replace(/^\[.*?\]\s*/g, '').trim())
        .map(l => l.replace(/^\d*\s*Contributors/i, '').trim())
        .map(l => l.replace(/\d*\s*Embed$/i, '').trim())
        .filter(l => !/^(?:作词|作曲|编曲|词|曲)\s*[:：]/.test(l))
        .filter(l => l.length > 0 && !l.startsWith('[ti:') && !l.startsWith('[ar:') && !l.startsWith('[al:') && !l.startsWith('[by:') && !l.startsWith('[la:'));
}

export function renderLyrics(data, force = false) {
    if (data?.request_id) {
        if (data.request_id !== activeLyricsRequestId || Number(data.revision || 0) <= lastLyricsRevision) return;
        lastLyricsRevision = Number(data.revision || 0);
    }
    if (!data || !data.request_id || data.phase === 'final') pendingLyricsRequest = null;
    const containers = getContainers();
    if (typeof lyricsPreferences === 'function') containers.forEach(container => {
        if (container.dataset) container.dataset.lyricsAnimations = lyricsPreferences().animations;
    });
    if (!data) {
        if (typeof clearWordLyrics === 'function') clearWordLyrics();
        lastLyricsData = null;
        // The sheet's children are about to be replaced, so the cached line
        // nodes and the measured geometry both go stale. Without this reset a
        // later position tick would keep highlighting detached nodes.
        resetLyricsScroll();
        containers.forEach(c => c.innerHTML = '<div class="empty-state">Текст песни не найден</div>');
        return;
    }

    const normalizedData = {
        syncedLyrics: data.syncedLyrics || data.synced_lyrics || (data.synced ? data.lyrics : null) || (typeof data === 'string' ? data : null),
        plainLyrics: data.plainLyrics || data.plain_lyrics || data.lyrics || (typeof data === 'string' ? data : null),
        instrumental: !!data.instrumental,
        status: data.status, source: data.source, match_type: data.match_type, phase: data.phase,
        syncType: data.syncType, lines: Array.isArray(data.lines) ? data.lines : null,
        originalFormat: data.originalFormat, originalLyrics: data.originalLyrics
    };
    if (!normalizedData.plainLyrics && normalizedData.lines?.length) {
        normalizedData.plainLyrics = normalizedData.lines.slice(0, 10000).map(line => (Array.isArray(line?.words) ? line.words : []).map(word => String(word?.text || '')).join('')).join('\n');
    }

    const previousPlain = cleanPlainLyrics(lastLyricsData?.plainLyrics || lastLyricsData?.syncedLyrics || '').join('\n');
    const nextPlain = cleanPlainLyrics(normalizedData.plainLyrics || normalizedData.syncedLyrics || '').join('\n');
    const unchanged = lastLyricsData && lastLyricsData.syncedLyrics === normalizedData.syncedLyrics && lastLyricsData.plainLyrics === normalizedData.plainLyrics && lastLyricsData.status === normalizedData.status && lastLyricsData.match_type === normalizedData.match_type && lastLyricsData.syncType === normalizedData.syncType && JSON.stringify(lastLyricsData.lines) === JSON.stringify(normalizedData.lines);
    if (previousPlain !== nextPlain) currentTranslationMap = {};
    lastLyricsData = normalizedData;
    rememberLyrics(normalizedData);
    if (unchanged && !force) return;
    if (typeof clearWordLyrics === 'function') clearWordLyrics();
    resetLyricsScroll();
    updateOffsetBadges();

    if (!normalizedData.syncedLyrics && !normalizedData.plainLyrics) {
        parsedLyrics = [];
        setOffsetControlsEnabled(false);
        const message = normalizedData.instrumental ? 'Инструментальная версия — без текста' : (normalizedData.status === 'unavailable' ? 'Не удалось загрузить текст: источники временно недоступны' : 'Текст песни не найден');
        containers.forEach(c => {
            c.innerHTML = `<div class="empty-state">${message}${normalizedData.instrumental ? '' : '<button class="btn btn-secondary">Повторить</button>'}</div>`;
            c.querySelector('button')?.addEventListener('click', () => loadCurrentTrackLyrics(0, true));
        });
        return;
    }

    currentRawLyricsText = normalizedData.syncedLyrics || normalizedData.plainLyrics || "";
    if (previousPlain !== nextPlain && isTranslationEnabled) toggleTranslation(true);

    if (normalizedData.syncedLyrics || normalizedData.lines?.length) {
        const normalized = normalizedData.lines ? normalizedTimedLines(normalizedData) : [];
        parsedLyrics = normalized.length ? normalized : parseLrc(normalizedData.syncedLyrics);
        const wordSync = normalized.length && ['word', 'syllable'].includes(normalizedData.syncType) && lyricsPreferences().mode !== 'line';
        if (wordSync) wordPainter = new WordPainter(parsedLyrics);
        if (parsedLyrics.length > 0) {
            containers.forEach(c => {
                c.innerHTML = '';
                const renderedWords = [];
                if (wordSync) wordRows.push(renderedWords);
                parsedLyrics.forEach((line, i) => {
                    const el = document.createElement('div');
                    el.className = 'lyric-line';
                    
                    const origSpan = document.createElement('div');
                    origSpan.className = 'lyric-orig-text';
                    if (wordSync) renderedWords[i] = appendTimedWords(origSpan, line);
                    else origSpan.textContent = line.text;
                    el.appendChild(origSpan);

                    const trans = currentTranslationMap[i] || currentTranslationMap[`${i}:${line.text}`] || currentTranslationMap[line.text];
                    if (isTranslationEnabled && trans) {
                        const subEl = document.createElement('div');
                        subEl.className = 'lyric-translation';
                        subEl.textContent = trans;
                        el.appendChild(subEl);
                    }

                    el.dataset.index = String(i);
                    el.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const position = Math.max(0, line.timeMs - currentOffsetMs);
                        seekTo(position);
                        updateLyricsPosition(position);
                        // Seek and re-centre in one step. Waiting for the next
                        // position tick to re-centre left the sheet parked on
                        // the old line for a frame or two after the click.
                        const st = ensureKineticState(c);
                        if (!st.measured || !ensureMeasured(st)) return;
                        // The click is an explicit intent to be on this line, so
                        // it also clears any active browse pause.
                        lastManualScrollAt = 0;
                        st.base = focalOffsetFor(st, el);
                        st.manual = 0;
                        applyTransform(st, st.base, true);
                    });
                    c.appendChild(el);
                });
            });
            // Update position immediately to highlight matching line
            updateLyricsPosition(lastPosMs);
            if (typeof paintWordLyrics === 'function') paintWordLyrics(lastPosMs, true);
            if (typeof syncWordLyrics === 'function') syncWordLyrics();
            setOffsetControlsEnabled(true);
            return;
        }
    }

    // Fallback to plain lyrics
    parsedLyrics = [];
    // Without timestamps there is no active line, so the offset had nothing to
    // act on: the buttons still responded and the badge changed, which read as a
    // broken control. Disable them and say why.
    setOffsetControlsEnabled(false);
    containers.forEach(c => {
        c.innerHTML = '';
        const lines = cleanPlainLyrics(normalizedData.plainLyrics);
        
        const warnEl = document.createElement('div');
        warnEl.className = 'lyric-notice';
        const message = normalizedData.match_type === 'base' ? 'Текст оригинальной версии — без таймкодов' : 'Текст не синхронизирован с треком';
        warnEl.innerHTML = `<i data-lucide="info" style="width:14px;height:14px"></i><span>${message}</span>`;
        c.appendChild(warnEl);
        renderIcons(warnEl);

        lines.forEach((line, idx) => {
            const el = document.createElement('div');
            el.className = 'lyric-line lyric-plain';
            el.textContent = line;
            const trans = currentTranslationMap[idx] || currentTranslationMap[`${idx}:${line}`] || currentTranslationMap[line];
            if (isTranslationEnabled && trans) {
                const subEl = document.createElement('div');
                subEl.className = 'lyric-translation';
                subEl.textContent = trans;
                el.appendChild(subEl);
            }
            c.appendChild(el);
        });
        // No timestamps means no focal line and no karaoke follow, but the sheet
        // is usually far taller than the viewport, so it still needs its focal
        // padding and bounds measured or the wheel would have nothing to move.
        const st = refreshKineticState(c);
        if (ensureMeasured(st)) {
            st.base = 0;
            writeManual(st, 0, false);
        }
    });
}

export function parseLrc(lrcText) {
    if (!lrcText || typeof lrcText !== 'string') return [];
    const lines = lrcText.split(/\r?\n/);
    const result = [];
    const timeReg = /\[(\d{1,3}):(\d{2})(?:[.:](\d+))?\]/g;
    const offsetTag = [...lrcText.matchAll(/\[offset:\s*([+-]?\d+)\s*\]/gi)].at(-1);
    const embeddedOffsetMs = offsetTag ? Number(offsetTag[1]) : 0;
    
    lines.forEach(line => {
        const trimmed = line.trim();
        if (!trimmed) return;
        // Ignore LRC metadata headers without timestamps
        if (/^\[(ti|ar|al|by|offset|length|re|ve):/i.test(trimmed)) return;

        const matches = [...trimmed.matchAll(timeReg)];
        if (matches.length > 0) {
            const text = trimmed.replace(timeReg, '').trim();
            matches.forEach(match => {
                const min = parseInt(match[1], 10);
                const sec = parseInt(match[2], 10);
                const msStr = match[3] || '0';
                const ms = parseInt(msStr.padEnd(3, '0').substring(0, 3), 10);
                const timeMs = (min * 60 * 1000) + (sec * 1000) + ms - embeddedOffsetMs;
                result.push({ timeMs, text: text || '♪' });
            });
        }
    });

    result.sort((a, b) => a.timeMs - b.timeMs);
    return result;
}

/**
 * Update active lyric line based on current playback position in milliseconds.
 * Unified unit: Milliseconds (ms) to match parsed LRC timeMs and currentOffsetMs.
 *
 * `timeupdate` fires ~4x/second and almost every tick lands on the same line,
 * so this is written to do *zero* layout work unless the index actually moved:
 * no getBoundingClientRect, no scrollTop, no class writes on the steady path.
 * @param {number} posMs - Playback position in milliseconds.
 */
export function updateLyricsPosition(posMs) {
    try {
        if (typeof posMs === 'number' && !isNaN(posMs)) {
            lastPosMs = posMs;
        }
        if (parsedLyrics.length === 0) return;

        const effectivePos = lastPosMs + currentOffsetMs;
        if (typeof paintWordLyrics === 'function') paintWordLyrics(lastPosMs);

        // Binary search: a long song has hundreds of lines and the linear scan
        // ran on every tick.
        let newIndex = -1;
        let lo = 0;
        let hi = parsedLyrics.length - 1;
        while (lo <= hi) {
            const mid = (lo + hi) >> 1;
            if (parsedLyrics[mid].timeMs <= effectivePos) {
                newIndex = mid;
                lo = mid + 1;
            } else {
                hi = mid - 1;
            }
        }

        if (newIndex !== currentLineIndex) {
            getContainers().forEach(track => {
                const st = ensureKineticState(track);
                if (st.dirty) refreshKineticState(track);
                ensureMeasured(st);
                updateLineClasses(st, newIndex);
                focusActiveLine(st, true);
            });
            currentLineIndex = newIndex;

        } else {
            // Steady path. Stays free of layout work in the common case, with one
            // exception: a sheet whose viewport had zero height while the panel
            // was hidden (`.view-page` is display:none) could not be measured,
            // so its transform is still the neutral translateY(0) and the active
            // line sits wherever the padding happens to put it -- possibly out
            // of view. Re-anchor the moment the viewport becomes measurable.
            //
            // The `!st.measured` guard is what keeps this free: once a sheet is
            // measured it is skipped entirely, so this costs a single property
            // read per tick and only while a sheet is still unmeasured.
            getContainers().forEach(track => {
                const st = track._kinetic;
                if (!st || st.measured || !st.activeEl) return;
                if (!ensureMeasured(st)) return;
                st.base = focalOffsetFor(st, st.activeEl);
                writeManual(st, 0, true);
            });
        }
    } catch(e) {
        console.error("Lyrics updateLyricsPosition Error:", e);
    }
}
