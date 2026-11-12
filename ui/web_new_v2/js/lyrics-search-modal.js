// NeDotify - Lyrics Search & Selection Modal (Screenshot #2)
import { renderIcons, showToast, escapeHtml, formatTime } from './utils.js';
import { getCurrentTrack } from './player.js';

let modalInitialized = false;
let searchGeneration = 0;

export function openLyricsSearchModal(initialQuery = null) {
    const modal = document.getElementById('modal-lyrics-search');
    if (!modal) return;

    modal.classList.remove('hidden');
    renderIcons(modal);

    const input = document.getElementById('input-lyrics-search-query');
    const track = getCurrentTrack();

    let query = initialQuery;
    if (!query && track) {
        if (track.artist && track.title) {
            query = `${track.artist} - ${track.title}`;
        } else {
            query = track.title || '';
        }
    }

    if (input) {
        input.value = query || '';
        setTimeout(() => {
            input.focus();
            input.select();
        }, 80);
    }

    if (query && query.trim()) {
        executeLyricsSearch(query.trim());
    } else {
        const resultsList = document.getElementById('lyrics-search-results-list');
        if (resultsList) {
            resultsList.innerHTML = `
                <div class="empty-state" style="padding: 40px 0; text-align:center; color:var(--text-sec); font-size:13px;">
                    Введите поисковый запрос и нажмите «Найти»
                </div>
            `;
        }
    }
}

export function closeLyricsSearchModal() {
    searchGeneration++;
    const modal = document.getElementById('modal-lyrics-search');
    if (modal) {
        modal.classList.add('hidden');
    }
}

export function executeLyricsSearch(queryText) {
    const resultsList = document.getElementById('lyrics-search-results-list');
    if (!resultsList) return;

    const query = String(queryText || '').trim();
    if (!query) {
        showToast('Введите поисковый запрос', 'warning');
        return;
    }

    resultsList.innerHTML = `
        <div class="empty-state" style="padding: 45px 0; text-align:center;">
            <div class="spinner" style="margin: 0 auto 14px auto;"></div>
            <div style="color:var(--text-sec); font-size:13px;">Ищем варианты текста в LRCLIB, NetEase, Kugou, QQ Music...</div>
        </div>
    `;

    const track = getCurrentTrack();
    const durationSec = Number(track?.duration) || 0;
    const artist = track?.artist || '';
    const title = track?.title || '';

    if (!window.pywebview?.api?.search_lyrics) {
        resultsList.innerHTML = `
            <div class="empty-state" style="padding: 40px 0; text-align:center; color:var(--color-danger, #ef4444); font-size:13px;">
                Поисковый сервис недоступен
            </div>
        `;
        return;
    }

    const generation = ++searchGeneration;
    window.pywebview.api.search_lyrics(query, artist, title, durationSec)
        .then(res => {
            if (generation !== searchGeneration) return;
            if (!res?.success) throw new Error(res?.error || 'Поисковый сервис недоступен');
            if (!res.candidates?.length) {
                resultsList.innerHTML = `
                    <div class="empty-state" style="padding: 45px 0; text-align:center; color:var(--text-sec); font-size:13px;">
                        Ничего не найдено по запросу «${escapeHtml(query)}».<br>
                        Попробуйте изменить название или исполнителя.
                    </div>
                `;
                return;
            }

            renderSearchResults(res.candidates, resultsList);
        })
        .catch(err => {
            if (generation !== searchGeneration) return;
            console.error('Lyrics search failed:', err);
            resultsList.innerHTML = `
                <div class="empty-state" style="padding: 40px 0; text-align:center; color:var(--color-danger, #ef4444); font-size:13px;">
                    Ошибка при поиске текста: ${escapeHtml(err.message || String(err))}
                </div>
            `;
        });
}

function renderSearchResults(results, container) {
    container.innerHTML = '';

    const track = getCurrentTrack();

    results.forEach((item, idx) => {
        const itemEl = document.createElement('div');
        itemEl.className = 'lyrics-search-item';
        itemEl.dataset.index = String(idx);

        const title = item.trackName || track?.title || 'Без названия';
        const artist = item.artistName || track?.artist || 'Неизвестный исполнитель';
        const album = item.albumName || '';
        const durationSec = Number(item.durationSeconds) || 0;
        const durationStr = durationSec > 0 ? formatTime(durationSec) : '';
        const source = (item.source || 'lrclib').toUpperCase();
        const isSynced = Boolean(item.hasTiming);

        itemEl.innerHTML = `
            <div class="lsi-meta">
                <div class="lsi-title">${escapeHtml(title)}</div>
                <div class="lsi-sub">
                    <span>${escapeHtml(artist)}</span>
                    ${album ? `<span class="lsi-bullet">•</span><span>${escapeHtml(album)}</span>` : ''}
                    ${durationStr ? `<span class="lsi-bullet">•</span><span>${durationStr}</span>` : ''}
                </div>
            </div>
            <div class="lsi-tags">
                <span class="badge-source">${escapeHtml(source)}</span>
                ${isSynced 
                    ? `<span class="badge-synced"><i data-lucide="clock" style="width:11px;height:11px;"></i> С таймингом</span>`
                    : `<span class="badge-plain">Только текст</span>`
                }
            </div>
        `;

        itemEl.addEventListener('click', () => {
            selectCandidate(item, title, source);
        });

        container.appendChild(itemEl);
    });

    renderIcons(container);
}

function selectCandidate(candidate, title, source) {
    const track = getCurrentTrack();
    if (!track) {
        showToast('Трек не выбран', 'warning');
        return;
    }

    if (!window.pywebview?.api?.apply_lyrics_candidate) {
        showToast('API применения текста недоступно', 'error');
        return;
    }

    // Indicate selection
    showToast(`Применяем выбранный текст: ${title}...`, 'info');
    closeLyricsSearchModal();

    window.pywebview.api.apply_lyrics_candidate(candidate, track)
        .then(res => {
            if (res && res.success) {
                showToast(`Выбран текст: ${title} (${source})`, 'success');
                if (window.NeDotify?.reloadCurrentTrackLyrics) {
                    window.NeDotify.reloadCurrentTrackLyrics(true);
                }
            } else {
                showToast(res?.error || 'Не удалось применить текст', 'error');
            }
        })
        .catch(err => {
            console.error('Failed to apply lyrics candidate:', err);
            showToast(`Ошибка сохранения текста: ${err.message || err}`, 'error');
        });
}

export function initLyricsSearchModal() {
    if (modalInitialized) return;
    modalInitialized = true;

    const modal = document.getElementById('modal-lyrics-search');
    if (!modal) return;

    const closeBtn = document.getElementById('btn-close-lyrics-search');
    const input = document.getElementById('input-lyrics-search-query');
    const submitBtn = document.getElementById('btn-lyrics-search-submit');

    if (closeBtn) {
        closeBtn.addEventListener('click', () => closeLyricsSearchModal());
    }

    // Close on backdrop click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeLyricsSearchModal();
        }
    });

    // Close on Escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
            closeLyricsSearchModal();
        }
    });

    // Search submit
    if (submitBtn) {
        submitBtn.addEventListener('click', () => {
            if (input) executeLyricsSearch(input.value);
        });
    }

    if (input) {
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                executeLyricsSearch(input.value);
            }
        });
    }
}
