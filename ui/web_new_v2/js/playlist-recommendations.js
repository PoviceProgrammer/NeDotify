import { addPythonEventHandler } from './events.js';
import { escapeHtml, getCoverUrl, coverImgHtml, renderIcons, showToast, showTrackContextMenu } from './utils.js';

let collection = null;
let section = null;
let sequence = 0;
let requestTimer = null;
let initialized = false;

function contentKey(track) {
    const normalize = value => String(value || '').normalize('NFKC').toLocaleLowerCase().trim().replace(/\s+/g, ' ');
    return `${normalize(track?.artist)}\u0000${normalize(track?.title)}`;
}

function trackKeys(track) {
    const keys = [contentKey(track)];
    if (track?.id != null) keys.push(`id:${track.id}`);
    if (track?.source_id != null) keys.push(`source:${track.source || ''}:${track.source_id}`);
    return keys;
}

function clearRequest() {
    if (requestTimer !== null) clearTimeout(requestTimer);
    requestTimer = null;
}

function current(target, requestId = target?.requestId) {
    return target === collection && requestId === target?.requestId;
}

function ensureSection() {
    const parent = document.getElementById('lib-active-tracks')?.parentElement;
    if (!parent) return null;
    if (!section || !section.isConnected) {
        section = document.createElement('section');
        section.id = 'lib-playlist-recommendations';
        section.className = 'playlist-recommendations';
        section.setAttribute('aria-labelledby', 'playlist-recommendations-title');
        parent.appendChild(section);
    }
    return section;
}

function renderState(target, status, message = '') {
    if (!current(target) || !ensureSection()) return;
    section.hidden = false;
    section.dataset.state = status;
    section.setAttribute('aria-busy', String(status === 'loading'));
    const subtitle = target.type === 'favorites' ? 'Новая музыка на основе ваших любимых треков' : 'Новая музыка на основе этого плейлиста';
    section.innerHTML = `<header class="playlist-recommendations-heading"><div><span class="playlist-recommendations-kicker"><i data-lucide="sparkles" aria-hidden="true"></i>Продолжите коллекцию</span><h2 id="playlist-recommendations-title">Подойдёт ${target.type === 'favorites' ? 'вашим любимым' : 'этому плейлисту'}</h2><p>${subtitle}</p></div><button type="button" class="playlist-recommendations-refresh" aria-label="Обновить рекомендации" ${status === 'loading' ? 'disabled' : ''}><i data-lucide="refresh-cw" aria-hidden="true"></i><span>Обновить</span></button></header><div class="playlist-recommendations-body" ${status !== 'ready' ? 'role="status"' : ''}></div>`;
    section.querySelector('.playlist-recommendations-refresh').onclick = () => requestRecommendations(target);
    const body = section.querySelector('.playlist-recommendations-body');
    if (status === 'ready') {
        target.suggestions.forEach(track => body.appendChild(createSuggestion(target, track)));
    } else {
        const icon = status === 'loading' ? 'loader-2' : status === 'error' ? 'cloud-off' : 'list-music';
        body.innerHTML = `<div class="playlist-recommendations-state"><i data-lucide="${icon}" ${status === 'loading' ? 'class="spin-icon"' : ''} aria-hidden="true"></i><p>${escapeHtml(message)}</p></div>`;
    }
    renderIcons(section);
}

function createSuggestion(target, track) {
    const row = document.createElement('article');
    row.className = 'playlist-recommendation';
    const title = track.title || 'Без названия';
    const artist = track.artist || 'Неизвестный исполнитель';
    const cover = coverImgHtml({src: getCoverUrl(track), coverUrl: track.cover_url, sourceId: track.source_id, source: track.source, alt: ''});
    row.innerHTML = `<button type="button" class="playlist-recommendation-play" aria-label="Послушать: ${escapeHtml(title)}"><span class="playlist-recommendation-artwork">${cover || '<i data-lucide="music-2" aria-hidden="true"></i>'}<span class="playlist-recommendation-play-icon"><i data-lucide="play" aria-hidden="true"></i></span></span></button><div class="playlist-recommendation-copy"><strong title="${escapeHtml(title)}">${escapeHtml(title)}</strong><span title="${escapeHtml(artist)}">${escapeHtml(artist)}</span>${track.recommendation_reason ? `<p class="playlist-recommendation-reason">${escapeHtml(track.recommendation_reason)}</p>` : ''}</div><button type="button" class="playlist-recommendation-add" aria-label="${target.type === 'favorites' ? 'Добавить в любимые' : 'Добавить в плейлист'}: ${escapeHtml(title)}"><i data-lucide="plus" aria-hidden="true"></i><span>Добавить</span></button><button type="button" class="playlist-recommendation-menu" aria-label="Действия: ${escapeHtml(title)}"><i data-lucide="more-horizontal" aria-hidden="true"></i></button>`;
    row.querySelector('.playlist-recommendation-play').onclick = async () => {
        try {
            const result = await window.pywebview.api.play_track(track, [track], 0);
            if (result?.success === false) throw new Error('Playback rejected');
        } catch { showToast('Не удалось воспроизвести трек', 'error'); }
    };
    row.querySelector('.playlist-recommendation-menu').onclick = event => showTrackContextMenu(track, event, target.suggestions, target.suggestions.indexOf(track));
    row.querySelector('.playlist-recommendation-add').onclick = async event => {
        const button = event.currentTarget;
        if (button.disabled || !current(target)) return;
        button.disabled = true;
        try {
            const api = window.pywebview.api;
            // Recheck favorites before toggling: a result can have been liked
            // from another surface since this recommendation was displayed.
            if (target.type === 'favorites') {
                const favorites = await api.get_favorites();
                if (!Array.isArray(favorites)) throw new Error('Favorites unavailable');
                const keys = new Set(favorites.flatMap(trackKeys));
                if (!trackKeys(track).some(key => keys.has(key))) {
                    const result = await api.toggle_favorite(track);
                    if (!result?.success || !result.is_favorite) throw new Error('Favorite rejected');
                }
            } else {
                const result = await api.add_to_playlist(target.id, track);
                if (result === false || result == null || result?.success === false) throw new Error('Playlist rejected');
            }
            if (!current(target)) return;
            trackKeys(track).forEach(key => target.excluded.add(key));
            target.suggestions = target.suggestions.filter(item => !trackKeys(item).some(key => target.excluded.has(key)));
            if (target.suggestions.length) renderState(target, 'ready');
            else renderState(target, 'empty', 'Все предложенные треки добавлены. Обновите подборку, чтобы найти ещё.');
            showToast(target.type === 'favorites' ? 'Добавлено в любимые' : 'Добавлено в плейлист', 'success');
        } catch {
            if (current(target)) { button.disabled = false; showToast('Не удалось добавить трек. Попробуйте ещё раз', 'error'); }
        }
    };
    return row;
}

async function requestRecommendations(target) {
    if (target !== collection) return;
    clearRequest();
    target.requestId = `playlist-${++sequence}`;
    const requestId = target.requestId;
    target.suggestions = [];
    if (!target.excluded.size) {
        renderState(target, 'empty', 'Добавьте несколько треков — подберём музыку в духе вашей коллекции.');
        return;
    }
    renderState(target, 'loading', 'Подбираем музыку…');
    requestTimer = setTimeout(() => {
        if (!current(target, requestId)) return;
        target.requestId = null;
        clearRequest();
        renderState(target, 'error', 'Подборка не загрузилась. Проверьте подключение и нажмите «Обновить».');
    }, 25000);
    try {
        if (window.awaitBridge) await window.awaitBridge();
        if (!current(target, requestId)) return;
        const api = window.pywebview?.api;
        if (!api?.get_playlist_recommendations) throw new Error('Recommendations unavailable');
        const result = await api.get_playlist_recommendations(target.id, 10, requestId);
        if (!current(target, requestId)) return;
        if (result?.success === false || result?.error) throw new Error('Recommendations rejected');
    } catch {
        if (!current(target, requestId)) return;
        clearRequest();
        target.requestId = null;
        renderState(target, 'error', 'Не удалось подобрать музыку. Попробуйте обновить подборку.');
    }
}

export function initPlaylistRecommendations() {
    if (initialized) return;
    initialized = true;
    addPythonEventHandler((eventName, data) => {
        const target = collection;
        if (eventName !== 'playlist_recommendations_ready' || !target || !target.requestId ||
            data?.request_id !== target.requestId || String(data.playlist_id) !== String(target.id)) return;
        clearRequest();
        target.requestId = null;
        if (data.error) { renderState(target, 'error', 'Не удалось подобрать музыку. Попробуйте обновить подборку.'); return; }
        const seen = new Set(target.excluded);
        target.suggestions = (Array.isArray(data.tracks) ? data.tracks : []).filter(track => {
            if (!track || typeof track !== 'object' || !track.title) return false;
            const keys = trackKeys(track);
            if (keys.some(key => seen.has(key))) return false;
            keys.forEach(key => seen.add(key));
            return true;
        }).slice(0, 10);
        if (target.suggestions.length) renderState(target, 'ready');
        else renderState(target, 'empty', 'Пока нет новых подходящих треков. Попробуйте позже или добавьте музыку в коллекцию.');
    });
    for (const event of ['nedotify:recommendation_feedback_changed', 'nedotify:recommendation_mode_changed']) {
        window.addEventListener(event, () => { if (collection) requestRecommendations(collection); });
    }
}

export function hidePlaylistRecommendations() {
    clearRequest();
    collection = null;
    if (section) section.hidden = true;
}

export function showPlaylistRecommendations(type, playlist, tracks) {
    hidePlaylistRecommendations();
    if (type !== 'favorites' && (type !== 'playlist' || playlist?.id == null || playlist?.is_system || playlist?.name === 'Скачанное')) return;
    initPlaylistRecommendations();
    collection = {id: type === 'favorites' ? 'favorites' : playlist.id, type, requestId: null, suggestions: [], excluded: new Set((tracks || []).flatMap(trackKeys))};
    requestRecommendations(collection);
}
