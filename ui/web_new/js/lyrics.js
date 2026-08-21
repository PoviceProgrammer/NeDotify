// NeDotify - Lyrics Module
import { getCurrentTrack, seekTo } from './player.js';

let parsedLyrics = [];
let currentLineIndex = -1;
let isOverlayVisible = false;
let currentOffsetMs = 0;
let isTranslationEnabled = false;
let currentTranslationMap = {};
let currentRawLyricsText = "";

// O-12: freshness guard — stale get_lyrics responses must not overwrite a newer track
let lyricsLoadGeneration = 0;

function toggleTranslation() {
    isTranslationEnabled = !isTranslationEnabled;
    const btns = [
        document.getElementById('btn-toggle-lyrics-translation'),
        document.getElementById('btn-toggle-lyrics-translation-page')
    ].filter(Boolean);

    btns.forEach(btnTrans => {
        if (isTranslationEnabled) {
            btnTrans.style.background = 'var(--primary)';
            btnTrans.style.color = 'var(--bg-main)';
            btnTrans.style.borderColor = 'var(--primary)';
        } else {
            btnTrans.style.background = 'rgba(255,255,255,0.1)';
            btnTrans.style.color = 'var(--text-sec)';
            btnTrans.style.borderColor = 'rgba(255,255,255,0.15)';
        }
    });

    if (isTranslationEnabled && Object.keys(currentTranslationMap).length === 0 && currentRawLyricsText) {
        if (window.pywebview?.api?.get_lyrics_translation) {
            window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Переводим текст песни...', type: 'info' } }));
            window.pywebview.api.get_lyrics_translation(currentRawLyricsText, 'ru').then(res => {
                currentTranslationMap = res || {};
                renderLyrics(lastLyricsData);
            }).catch(err => {
                console.error("Translation failed:", err);
            });
        }
    } else {
        renderLyrics(lastLyricsData);
    }
}

function adjustLyricsOffset(deltaMs) {
    currentOffsetMs += deltaMs;
    window.dispatchEvent(new CustomEvent('nedotify:toast', {
        detail: {
            msg: `Смещение текста: ${currentOffsetMs > 0 ? '+' : ''}${(currentOffsetMs / 1000).toFixed(1)}s`,
            type: 'info'
        }
    }));
    const track = getCurrentTrack();
    if (track) {
        try {
            // M-2: single key for the active track — no unbounded per-track localStorage growth
            localStorage.setItem('nedotify_lyrics_offset_current', currentOffsetMs);
        } catch(e) {}
        const trackKey = String(track.source_id || track.id || track.title || '');
        if (trackKey && window.pywebview?.api?.save_setting) {
            window.pywebview.api.save_setting(`lyrics_offset_${trackKey}`, currentOffsetMs, 'lyrics');
        }
    }
    currentLineIndex = -1;
    updateLyricsPosition(lastPosMs);
}

export function initLyrics() {
    const btn = document.getElementById('pp-btn-lyrics');
    const closeBtn = document.getElementById('btn-close-lyrics');
    const overlay = document.getElementById('lyrics-overlay');

    window.NeDotify = window.NeDotify || {};
    window.NeDotify.loadCurrentTrackLyrics = loadCurrentTrackLyrics;

    if (btn) {
        btn.addEventListener('click', () => {
            isOverlayVisible = true;
            overlay.classList.add('active');
            loadCurrentTrackLyrics();
        });
    }

    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            isOverlayVisible = false;
            overlay.classList.remove('active');
        });
    }

    const btnMinus = document.getElementById('btn-lyrics-offset-minus');
    const btnPlus = document.getElementById('btn-lyrics-offset-plus');
    const btnTrans = document.getElementById('btn-toggle-lyrics-translation');

    const btnMinusPage = document.getElementById('btn-lyrics-offset-minus-page');
    const btnPlusPage = document.getElementById('btn-lyrics-offset-plus-page');
    const btnTransPage = document.getElementById('btn-toggle-lyrics-translation-page');

    if (btnMinus) btnMinus.addEventListener('click', () => adjustLyricsOffset(-500));
    if (btnPlus) btnPlus.addEventListener('click', () => adjustLyricsOffset(500));
    if (btnTrans) btnTrans.addEventListener('click', () => toggleTranslation());

    if (btnMinusPage) btnMinusPage.addEventListener('click', () => adjustLyricsOffset(-500));
    if (btnPlusPage) btnPlusPage.addEventListener('click', () => adjustLyricsOffset(500));
    if (btnTransPage) btnTransPage.addEventListener('click', () => toggleTranslation());

    // Listen to track/position events dispatched by events.js via custom events
    document.addEventListener('nedotify:track_changed', (e) => {
        loadCurrentTrackLyrics();
    });
    // Time synchronization: nedotify:position_changed provides position in milliseconds (posMs / pos).
    // Parsed LRC timestamps (parseLrc) are in milliseconds (timeMs).
    // Standardized here to milliseconds for pixel-perfect lyrics synchronization.
    document.addEventListener('nedotify:position_changed', (e) => {
        const posMs = e.detail?.posMs !== undefined ? e.detail.posMs : (typeof e.detail?.pos === 'number' ? e.detail.pos : 0);
        updateLyricsPosition(posMs);
    });
    document.addEventListener('nedotify:lyrics_ready', (e) => {
        renderLyrics(e.detail);
    });
}

function getContainers() {
    return [
        document.getElementById('lyrics-content'),
        document.getElementById('overlay-lyrics-content')
    ].filter(Boolean);
}

function resetLyricsScroll() {
    currentLineIndex = -1;
    getContainers().forEach(c => {
        const scrollParent = c.closest('.player-lyrics-container') || c.closest('.lyrics-scroll-container') || c.parentElement;
        if (scrollParent) {
            scrollParent.scrollTop = 0;
            if (typeof scrollParent.scrollTo === 'function') {
                scrollParent.scrollTo({ top: 0, behavior: 'instant' });
            }
        }
        c.scrollTop = 0;
    });
}

function loadCurrentTrackLyrics() {
    resetLyricsScroll();
    const track = getCurrentTrack();
    const containers = getContainers();
    if (!track) {
        containers.forEach(c => c.innerHTML = '<div class="empty-state">Трек не выбран</div>');
        return;
    }
    containers.forEach(c => c.innerHTML = '<div class="empty-state"><div class="spinner"></div>Ищем текст...</div>');
    parsedLyrics = [];
    currentLineIndex = -1;
    currentTranslationMap = {};
    currentRawLyricsText = "";
    currentOffsetMs = 0;

    // O-12: bump generation — only the freshest request may render
    const loadGen = ++lyricsLoadGeneration;

    // M-2: localStorage keeps only the active track's offset (no unbounded per-track keys)
    try {
        const saved = localStorage.getItem('nedotify_lyrics_offset_current');
        if (saved) currentOffsetMs = parseInt(saved) || 0;
    } catch(e) {
        currentOffsetMs = 0;
    }
    
    if (window.pywebview?.api) {
        const durMs = track.duration ? (track.duration > 10000 ? track.duration : Math.round(track.duration * 1000)) : 0;
        const p = window.pywebview.api.get_lyrics(track.title, track.artist, durMs, track.file_path);
        
        if (p && p.then) {
            p.then(res => {
                if (loadGen !== lyricsLoadGeneration) return;
                // C-2: backend returns {"status": "loading"} instantly; real data comes via lyrics_ready
                if (res && res.status === 'loading') return;
                if (res) {
                    renderLyrics({
                        syncedLyrics: res.syncedLyrics || res.synced_lyrics || (typeof res === 'string' ? res : null),
                        plainLyrics: res.plainLyrics || res.plain_lyrics || (typeof res === 'string' ? res : null),
                        instrumental: res.instrumental
                    });
                } else {
                    renderLyrics(null);
                }
            }).catch(err => {
                if (loadGen !== lyricsLoadGeneration) return;
                console.error("get_lyrics error:", err);
                renderLyrics(null);
            });
        }
    }
}

function cleanPlainLyrics(plainText) {
    if (!plainText) return [];
    return plainText.split('\n')
        .map(l => l.replace(/^\[.*?\]\s*/g, '').trim())
        .map(l => l.replace(/^\d*\s*Contributors/i, '').trim())
        .map(l => l.replace(/\d*\s*Embed$/i, '').trim())
        .filter(l => l.length > 0 && !l.startsWith('[ti:') && !l.startsWith('[ar:') && !l.startsWith('[al:') && !l.startsWith('[by:') && !l.startsWith('[la:'));
}

let lastLyricsData = null;

function renderLyrics(data) {
    lastLyricsData = data;
    resetLyricsScroll();
    const containers = getContainers();
    if (!data || (!data.syncedLyrics && !data.plainLyrics)) {
        containers.forEach(c => c.innerHTML = '<div class="empty-state">Текст песни не найден</div>');
        return;
    }

    currentRawLyricsText = data.syncedLyrics || data.plainLyrics || "";

    if (data.syncedLyrics) {
        parsedLyrics = parseLrc(data.syncedLyrics);
        if (parsedLyrics.length > 0) {
            containers.forEach(c => {
                c.innerHTML = '';
                parsedLyrics.forEach((line, i) => {
                    const el = document.createElement('div');
                    el.className = 'lyric-line';
                    
                    const origSpan = document.createElement('div');
                    origSpan.className = 'lyric-orig-text';
                    origSpan.style.textAlign = 'center';
                    origSpan.style.width = '100%';
                    origSpan.textContent = line.text;
                    el.appendChild(origSpan);

                    if (isTranslationEnabled && currentTranslationMap[line.text]) {
                        const subEl = document.createElement('div');
                        subEl.className = 'lyric-translation';
                        subEl.style.fontSize = '13px';
                        subEl.style.color = 'var(--text-sec)';
                        subEl.style.marginTop = '4px';
                        subEl.style.fontWeight = '400';
                        subEl.style.textAlign = 'center';
                        subEl.style.width = '100%';
                        subEl.textContent = currentTranslationMap[line.text];
                        el.appendChild(subEl);
                    }

                    el.dataset.index = i;
                    el.addEventListener('click', () => {
                        seekTo(line.timeMs);
                        scrollToElement(el, c);
                    });
                    c.appendChild(el);
                });
            });
            return;
        }
    }

    // Fallback to plain lyrics
    parsedLyrics = [];
    containers.forEach(c => {
        c.innerHTML = '';
        const lines = cleanPlainLyrics(data.plainLyrics);
        
        const warnEl = document.createElement('div');
        warnEl.className = 'lyric-notice';
        warnEl.style.fontSize = '12px';
        warnEl.style.color = 'var(--text-dim)';
        warnEl.style.marginBottom = '20px';
        warnEl.style.display = 'flex';
        warnEl.style.justifyContent = 'center';
        warnEl.style.alignItems = 'center';
        warnEl.style.gap = '8px';
        warnEl.innerHTML = '<i data-lucide="info" style="width:14px;height:14px"></i><span>Текст не синхронизирован с треком</span>';
        c.appendChild(warnEl);

        lines.forEach(line => {
            const el = document.createElement('div');
            el.className = 'lyric-line lyric-plain';
            el.textContent = line;
            c.appendChild(el);
        });
    });
}

function parseLrc(lrcText) {
    const lines = lrcText.split('\n');
    const result = [];
    const timeReg = /\[(\d{2}):(\d{2})(?:\.(\d{1,3}))?\]/g;
    
    lines.forEach(line => {
        const matches = [...line.matchAll(timeReg)];
        if (matches.length > 0) {
            const text = line.replace(timeReg, '').trim();
            if (text) {
                matches.forEach(match => {
                    const min = parseInt(match[1]);
                    const sec = parseInt(match[2]);
                    const msStr = match[3] || '0';
                    const ms = parseInt(msStr.padEnd(3, '0').substring(0, 3));
                    const timeMs = (min * 60 * 1000) + (sec * 1000) + ms;
                    result.push({ timeMs, text });
                });
            }
        }
    });

    result.sort((a, b) => a.timeMs - b.timeMs);
    return result;
}

function scrollToElement(targetLine, c) {
    if (!targetLine || !c) return;
    const scrollParent = c.closest('.player-lyrics-container') || c.closest('.lyrics-scroll-container') || c.parentElement;
    if (!scrollParent) return;

    const parentRect = scrollParent.getBoundingClientRect();
    const lineRect = targetLine.getBoundingClientRect();
    const relativeTop = lineRect.top - parentRect.top + scrollParent.scrollTop;
    const targetScroll = relativeTop - (scrollParent.clientHeight / 2) + (lineRect.height / 2);

    if (typeof scrollParent.scrollTo === 'function') {
        scrollParent.scrollTo({
            top: Math.max(0, targetScroll),
            behavior: 'smooth'
        });
    } else if (typeof targetLine.scrollIntoView === 'function') {
        targetLine.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

let lastPosMs = 0;

/**
 * Update active lyric line based on current playback position in milliseconds.
 * Unified unit: Milliseconds (ms) to match parsed LRC timeMs and currentOffsetMs.
 * @param {number} posMs - Playback position in milliseconds.
 */
function updateLyricsPosition(posMs) {
    try {
        if (typeof posMs === 'number') {
            lastPosMs = posMs;
        }
        if (parsedLyrics.length === 0) return;

        const effectivePos = lastPosMs + currentOffsetMs;

        let newIndex = -1;
        for (let i = 0; i < parsedLyrics.length; i++) {
            if (effectivePos >= parsedLyrics[i].timeMs) {
                newIndex = i;
            } else {
                break;
            }
        }

        if (newIndex !== currentLineIndex && newIndex !== -1) {
            getContainers().forEach(c => {
                const lines = c.querySelectorAll('.lyric-line');
                let targetLine = null;
                lines.forEach((line, idx) => {
                    if (idx === newIndex) {
                        line.classList.add('active');
                        targetLine = line;
                    } else {
                        line.classList.remove('active');
                    }
                });

                if (targetLine) {
                    scrollToElement(targetLine, c);
                }
            });
            currentLineIndex = newIndex;
        }
    } catch(e) {
        console.error("Lyrics updateLyricsPosition Error:", e);
    }
}

// Initialization is handled by main.js



