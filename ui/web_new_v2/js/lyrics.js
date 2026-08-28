// NeDotify - Lyrics Module (Kinetic Karaoke Engine)
import { getCurrentTrack, seekTo } from './player.js';
import { renderIcons } from './utils.js';

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

export function toggleTranslation() {
    isTranslationEnabled = !isTranslationEnabled;
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

export function initLyrics() {
    const btn = document.getElementById('pp-btn-lyrics');
    const closeBtn = document.getElementById('btn-close-lyrics') || document.getElementById('lyrics-close');
    const overlay = document.getElementById('lyrics-overlay');

    window.NeDotify = window.NeDotify || {};
    window.NeDotify.loadCurrentTrackLyrics = loadCurrentTrackLyrics;
    window.NeDotify.updateLyricsPosition = updateLyricsPosition;
    window.NeDotify.adjustLyricsOffset = adjustLyricsOffset;
    window.NeDotify.resetLyricsOffset = resetLyricsOffset;
    window.NeDotify.toggleTranslation = toggleTranslation;

    // Purge stale unbounded global offset from previous buggy sessions
    try { localStorage.removeItem('nedotify_lyrics_offset_current'); } catch(e) {}

    if (btn) {
        btn.addEventListener('click', () => {
            if (overlay) {
                isOverlayVisible = true;
                overlay.classList.add('active');
                loadCurrentTrackLyrics();
            }
        });
    }

    const pbPipBtn = document.getElementById('pb-btn-pip-lyrics');
    if (pbPipBtn) {
        pbPipBtn.addEventListener('click', () => {
            toggleMiniLyrics();
        });
    }

    initMiniLyricsWidget();

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

    if (btnMinus) btnMinus.addEventListener('click', () => adjustLyricsOffset(-500));
    if (btnReset) btnReset.addEventListener('click', () => resetLyricsOffset());
    if (btnPlus) btnPlus.addEventListener('click', () => adjustLyricsOffset(500));
    if (btnTrans) btnTrans.addEventListener('click', () => toggleTranslation());

    if (btnMinusPage) btnMinusPage.addEventListener('click', () => adjustLyricsOffset(-500));
    if (btnResetPage) btnResetPage.addEventListener('click', () => resetLyricsOffset());
    if (btnPlusPage) btnPlusPage.addEventListener('click', () => adjustLyricsOffset(500));
    if (btnTransPage) btnTransPage.addEventListener('click', () => toggleTranslation());

    // Listen to track/position events dispatched by events.js via custom events
    document.addEventListener('nedotify:track_changed', () => {
        loadCurrentTrackLyrics();
    });

    // Time synchronization: nedotify:position_changed provides position in milliseconds (posMs / pos).
    // Parsed LRC timestamps (parseLrc) are in milliseconds (timeMs).
    // Standardized to milliseconds for pixel-perfect kinetic lyrics synchronization.
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
        if (c._lastActiveLyric) {
            c._lastActiveLyric.classList.remove('active');
            c._lastActiveLyric = null;
        }
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

export function loadCurrentTrackLyrics() {
    const track = getCurrentTrack();
    const containers = getContainers();
    
    // Sync overlay title
    const titleEl = document.getElementById('lyrics-title');
    if (titleEl) {
        titleEl.textContent = track ? (track.title + (track.artist ? ' — ' + track.artist : '')) : 'Текст песни';
    }

    if (!track) {
        containers.forEach(c => c.innerHTML = '<div class="empty-state">Трек не выбран</div>');
        return;
    }

    const trackKey = track ? String(track.source_id || track.id || (track.title + ' ' + (track.artist || '')) || '') : '';

    // If lyrics are already loaded in memory for this exact track, render immediately without flashing
    if (trackKey && trackKey === lastLoadedTrackKey && lastLyricsData && (lastLyricsData.syncedLyrics || lastLyricsData.plainLyrics)) {
        renderLyrics(lastLyricsData);
        return;
    }

    lastLoadedTrackKey = trackKey;
    resetLyricsScroll();

    containers.forEach(c => c.innerHTML = '<div class="empty-state"><div class="spinner"></div>Ищем текст...</div>');
    parsedLyrics = [];
    currentLineIndex = -1;
    currentTranslationMap = {};
    currentRawLyricsText = "";
    currentOffsetMs = 0;

    // Bump generation — only the freshest request may render
    const loadGen = ++lyricsLoadGeneration;

    if (trackKey) {
        try {
            const saved = localStorage.getItem(`nedotify_lyrics_offset_${trackKey}`);
            if (saved !== null) {
                currentOffsetMs = parseInt(saved, 10) || 0;
            }
        } catch(e) {
            currentOffsetMs = 0;
        }
    }
    updateOffsetBadges();
    
    if (window.pywebview?.api) {
        const durMs = track.duration ? (track.duration > 10000 ? track.duration : Math.round(track.duration * 1000)) : 0;
        const p = window.pywebview.api.get_lyrics(track.title, track.artist, durMs, track.file_path);
        
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
        }
    }
}

function cleanPlainLyrics(plainText) {
    if (!plainText) return [];
    return plainText.split(/\r?\n/)
        .map(l => l.replace(/^\[.*?\]\s*/g, '').trim())
        .map(l => l.replace(/^\d*\s*Contributors/i, '').trim())
        .map(l => l.replace(/\d*\s*Embed$/i, '').trim())
        .filter(l => l.length > 0 && !l.startsWith('[ti:') && !l.startsWith('[ar:') && !l.startsWith('[al:') && !l.startsWith('[by:') && !l.startsWith('[la:'));
}

export function renderLyrics(data) {
    const containers = getContainers();
    if (!data) {
        lastLyricsData = null;
        containers.forEach(c => c.innerHTML = '<div class="empty-state">Текст песни не найден</div>');
        return;
    }

    const normalizedData = {
        syncedLyrics: data.syncedLyrics || data.synced_lyrics || (data.synced ? data.lyrics : null) || (typeof data === 'string' ? data : null),
        plainLyrics: data.plainLyrics || data.plain_lyrics || data.lyrics || (typeof data === 'string' ? data : null),
        instrumental: !!data.instrumental
    };

    lastLyricsData = normalizedData;
    resetLyricsScroll();
    updateOffsetBadges();

    if (!normalizedData.syncedLyrics && !normalizedData.plainLyrics) {
        containers.forEach(c => c.innerHTML = '<div class="empty-state">Текст песни не найден</div>');
        return;
    }

    currentRawLyricsText = normalizedData.syncedLyrics || normalizedData.plainLyrics || "";

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
                    origSpan.textContent = line.text;
                    el.appendChild(origSpan);

                    if (isTranslationEnabled && currentTranslationMap[line.text]) {
                        const subEl = document.createElement('div');
                        subEl.className = 'lyric-translation';
                        subEl.textContent = currentTranslationMap[line.text];
                        el.appendChild(subEl);
                    }

                    el.dataset.index = String(i);
                    el.addEventListener('click', (e) => {
                        e.stopPropagation();
                        seekTo(line.timeMs);
                        scrollToElement(el, c);
                    });
                    c.appendChild(el);
                });
            });
            // Update position immediately to highlight matching line
            updateLyricsPosition(lastPosMs);
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
        warnEl.innerHTML = '<i data-lucide="info" style="width:14px;height:14px"></i><span>Текст не синхронизирован с треком</span>';
        c.appendChild(warnEl);
        renderIcons(warnEl);

        lines.forEach(line => {
            const el = document.createElement('div');
            el.className = 'lyric-line lyric-plain';
            el.textContent = line;
            c.appendChild(el);
        });
    });
}

export function parseLrc(lrcText) {
    if (!lrcText || typeof lrcText !== 'string') return [];
    const lines = lrcText.split(/\r?\n/);
    const result = [];
    const timeReg = /\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]/g;
    
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
                const timeMs = (min * 60 * 1000) + (sec * 1000) + ms;
                result.push({ timeMs, text: text || '♪' });
            });
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
    if (parentRect.height === 0) return; // Hidden container

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

/**
 * Update active lyric line based on current playback position in milliseconds.
 * Unified unit: Milliseconds (ms) to match parsed LRC timeMs and currentOffsetMs.
 * @param {number} posMs - Playback position in milliseconds.
 */
export function updateLyricsPosition(posMs) {
    try {
        if (typeof posMs === 'number' && !isNaN(posMs)) {
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

        if (newIndex !== currentLineIndex) {
            getContainers().forEach(c => {
                if (c._lastActiveLyric) {
                    c._lastActiveLyric.classList.remove('active');
                } else {
                    const prev = c.querySelector('.lyric-line.active');
                    if (prev) prev.classList.remove('active');
                }

                if (newIndex !== -1) {
                    const targetLine = c.querySelector(`.lyric-line[data-index="${newIndex}"]`);
                    if (targetLine) {
                        targetLine.classList.add('active');
                        c._lastActiveLyric = targetLine;
                        scrollToElement(targetLine, c);
                    } else {
                        c._lastActiveLyric = null;
                    }
                } else {
                    c._lastActiveLyric = null;
                }
            });
            currentLineIndex = newIndex;

            // Dispatch event for Floating Mini-Karaoke Widget
            window.dispatchEvent(new CustomEvent('lyrics:line-changed', {
                detail: {
                    index: newIndex,
                    currentLine: parsedLyrics[newIndex]?.text || '',
                    nextLine: parsedLyrics[newIndex + 1]?.text || '',
                    translation: currentTranslationMap[parsedLyrics[newIndex]?.text] || ''
                }
            }));
        }
    } catch(e) {
        console.error("Lyrics updateLyricsPosition Error:", e);
    }
}

// ==========================================================================
// FEATURE 1: Floating Mini-Karaoke Widget Implementation
// ==========================================================================

let isPipWidgetActive = false;

/**
 * Инициализация логики перетаскивания и привязки событий мини-виджета караоке.
 */
export function initMiniLyricsWidget() {
    const widget = document.getElementById('mini-lyrics-widget');
    const closeBtn = document.getElementById('pip-lyrics-close');
    const header = widget?.querySelector('.pip-lyrics-header');
    if (!widget || !header) return;

    // Закрытие виджета
    closeBtn?.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleMiniLyrics(false);
    });

    // ── Drag & Drop с контролем границ окна (Boundary Guard) ──
    let isDragging = false;
    let startMouseX = 0, startMouseY = 0;
    let startWidgetX = 0, startWidgetY = 0;

    header.addEventListener('mousedown', (e) => {
        if (e.target.closest('#pip-lyrics-close')) return;
        isDragging = true;
        widget.classList.add('dragging');

        const rect = widget.getBoundingClientRect();
        startMouseX = e.clientX;
        startMouseY = e.clientY;
        startWidgetX = rect.left;
        startWidgetY = rect.top;

        // Фиксация в абсолютных координатах от левого верхнего угла
        widget.style.right = 'auto';
        widget.style.bottom = 'auto';
        widget.style.left = `${startWidgetX}px`;
        widget.style.top = `${startWidgetY}px`;

        const onMouseMove = (moveEvt) => {
            if (!isDragging) return;
            const deltaX = moveEvt.clientX - startMouseX;
            const deltaY = moveEvt.clientY - startMouseY;

            let nextX = startWidgetX + deltaX;
            let nextY = startWidgetY + deltaY;

            // Защита от вылета за пределы экрана и наложения на плеер-бар
            const minX = 12;
            const maxX = window.innerWidth - widget.offsetWidth - 12;
            const minY = 36; // Ниже оконного Title Bar
            const maxY = window.innerHeight - widget.offsetHeight - (84 + 16); // Выше нижнего плеера

            nextX = Math.max(minX, Math.min(nextX, maxX));
            nextY = Math.max(minY, Math.min(nextY, maxY));

            widget.style.left = `${nextX}px`;
            widget.style.top = `${nextY}px`;
        };

        const onMouseUp = () => {
            isDragging = false;
            widget.classList.remove('dragging');
            window.removeEventListener('mousemove', onMouseMove);
            window.removeEventListener('mouseup', onMouseUp);

            // Сохранение предпочтительного положения
            try {
                localStorage.setItem('nedotify_pip_lyrics_pos', JSON.stringify({
                    x: widget.style.left,
                    y: widget.style.top
                }));
            } catch (err) {}
        };

        window.addEventListener('mousemove', onMouseMove);
        window.addEventListener('mouseup', onMouseUp);
    });

    // Восстановление последней сохраненной позиции
    try {
        const savedPos = JSON.parse(localStorage.getItem('nedotify_pip_lyrics_pos') || '{}');
        if (savedPos.x && savedPos.y) {
            widget.style.right = 'auto';
            widget.style.bottom = 'auto';
            widget.style.left = savedPos.x;
            widget.style.top = savedPos.y;
        }
    } catch (e) {}

    // Слушатель синхронизации строк (диспатчится из updateLyricsPosition)
    window.addEventListener('lyrics:line-changed', (e) => {
        const { currentLine, nextLine, translation } = e.detail || {};
        const curEl = document.getElementById('pip-lyric-current');
        const nextEl = document.getElementById('pip-lyric-next');
        const transEl = document.getElementById('pip-lyric-translation');

        if (curEl) curEl.textContent = currentLine || '♪ ♪ ♪';
        if (nextEl) nextEl.textContent = nextLine || '';

        if (transEl) {
            if (translation) {
                transEl.textContent = translation;
                transEl.style.display = 'block';
            } else {
                transEl.style.display = 'none';
            }
        }
    });
}

/**
 * Переключатель видимости плавающего караоке
 */
export function toggleMiniLyrics(forceState) {
    const widget = document.getElementById('mini-lyrics-widget');
    if (!widget) return;
    isPipWidgetActive = forceState !== undefined ? forceState : widget.classList.contains('hidden');
    widget.classList.toggle('hidden', !isPipWidgetActive);
}

// Экспорт в глобальный неймспейс NeDotify
window.NeDotify = window.NeDotify || {};
window.NeDotify.toggleMiniLyrics = toggleMiniLyrics;
