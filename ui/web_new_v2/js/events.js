// NeDotify — Python Event Bridge
import { onTrackChanged, onStateChanged, applySettings, applyMuteState, getCurrentTrack, stopPlaybackForQueueEnd } from './player.js';
import { onSearchResults } from './search.js';
import { renderPopular, renderRecommendations, renderReleases, renderMixes, renderArtists, loadHome, clearFeedTimeout, renderAuthenticHome, isCurrentHomeEvent, renderHomeRetry } from './home.js';
import { loadLibrary, loadDownloaded, loadPlaylists } from './library.js';
import { applySettingsFromBackend, onStorageInfo, setYandexWarning } from './settings.js';
import { showToast, renderIcons, escapeHtml } from './utils.js';

let isNextTrackChange = false;
let lastAudioErrorAt = 0;

// O-5: track the visible page so hidden sections are not re-rendered on burst events
let currentPageId = 'home';
window.addEventListener('nedotify:page_changed', (e) => { currentPageId = e.detail; });

function isPageVisible(pageId) {
    const el = document.getElementById('view-' + pageId);
    return !!(el && el.classList.contains('active'));
}

// O-5: debounce (300ms) library refresh bursts (e.g. batch downloads) into a single re-render
let libraryRefreshTimer = null;

// P1-8: order-independent bridge-event registry.
// The backend calls window.onPythonEvent(name, payload) (see core/api.py::_emit),
// so any module that decorates that global only works if it happens to run after
// whoever installed it — reordering imports or a failed init silently dropped the
// listeners. Everything now registers here instead, and the dispatcher below is
// installed at module evaluation, before any init() can race it.
const pythonEventHandlers = [];

/**
 * Subscribe to Python bridge events. Returns an unsubscribe function.
 * @param {(eventName: string, data: any) => void} fn
 * @returns {() => void}
 */
export function addPythonEventHandler(fn) {
    if (typeof fn !== 'function') return () => {};
    pythonEventHandlers.push(fn);
    return () => {
        const idx = pythonEventHandlers.indexOf(fn);
        if (idx !== -1) pythonEventHandlers.splice(idx, 1);
    };
}

// Installed by initEvents(); null before that so the registry stays usable even
// if initEvents() throws or is never reached.
let coreEventHandler = null;
let eventsReady = false;
let deferReplay = false;
const pendingEvents = [];
export function deferPythonEvents() { deferReplay = true; }

export function flushPythonEvents() {
    eventsReady = true;
    for (const [name, payload] of pendingEvents.splice(0)) dispatchPythonEvent(name, payload);
}

function dispatchPythonEvent(eventName, data) {
    if (!eventsReady) {
        if (pendingEvents.length >= 1024) pendingEvents.shift();
        pendingEvents.push([eventName, data]);
        return;
    }
    if (coreEventHandler) {
        try {
            coreEventHandler(eventName, data);
        } catch (err) {
            console.error('Core Python event handler failed:', err);
        }
    }
    for (const fn of pythonEventHandlers.slice()) {
        try {
            fn(eventName, data);
        } catch (err) {
            console.error('Python event subscriber failed:', err);
        }
    }
}

// Stable reference: re-assigning it is a no-op, and every subscriber survives
// regardless of when it registered.
window.onPythonEvent = dispatchPythonEvent;

export function initEvents() {
    window.onPythonEvent = dispatchPythonEvent;
    coreEventHandler = function(eventName, data) {
        // Media URLs and auth fields can contain credentials; never log payloads.
        console.debug('Python Event:', eventName);

        switch (eventName) {
            case 'setup_status':
            case 'setup_progress':
                document.dispatchEvent(new CustomEvent('nedotify:' + eventName, {detail: data}));
                break;
            case 'download_queue_updated':
            case 'download_progress':
                break;



            case 'operation_error':
                document.dispatchEvent(new CustomEvent('nedotify:operation_error', { detail: data }));
                break;
            case 'window_visibility': {
                const hidden = data?.hidden === true;
                const root = document.documentElement;
                if (root.classList.contains('window-hidden') === hidden) break;
                root.classList.toggle('window-hidden', hidden);
                document.dispatchEvent(new CustomEvent('nedotify:window_visibility_changed', { detail: { hidden } }));
                break;
            }
            case 'track_changed':
                isNextTrackChange = true;
                onTrackChanged(data);
                document.dispatchEvent(new CustomEvent('nedotify:track_changed', { detail: data }));
                break;

            case 'state_changed': {
                // Normalize payload which could be string or { state: "..." }
                const state = (typeof data === 'object' && data !== null && 'state' in data) ? data.state : data;
                onStateChanged(state);
                break;
            }

            case 'search_results':
                onSearchResults(data);
                window.dispatchEvent(new CustomEvent('app:search_results', { detail: data }));
                break;
            case 'search_completed':
                onSearchResults({ ...data, source: '__completion__', type: data?.type || null });
                window.dispatchEvent(new CustomEvent('app:search_completed', { detail: data }));
                break;
                
            case 'authentic_home_ready':
                if (data && data.sections) {
                    renderAuthenticHome(data.sections);
                }
                break;
                
            // BUG-U3-007: мёртвый case 'yt_playlist_ready' удалён — событие не
            // эмитится бэкендом. Импорт плейлистов завершается emission
            // 'playlists_updated' (core/api.py::import_external_playlist) и
            // обрабатывается группой library_updated/playlists_updated ниже.

            case 'authentic_home_error': {
                const authContainer = document.getElementById('home-authentic-feed');
                if (authContainer) {
                    authContainer.innerHTML = `<div style="padding:20px; text-align:center; color:var(--text-sec);">Ошибка: ${escapeHtml(data.error)}</div>`;
                }
                break;
            }

            case 'popular_results':
                if (!isCurrentHomeEvent('home-popular', data)) break;
                clearFeedTimeout('home-popular');
                if (data?.error) { renderHomeRetry('home-popular'); break; }
                if (data) {
                    const tracks = Array.isArray(data) ? data : (data.tracks || []);
                    renderPopular(tracks);
                }
                break;

            case 'feed_ready':
            case 'recommendations_ready': {
                if (!isCurrentHomeEvent('home-recommended', data)) break;
                clearFeedTimeout('home-recommended');
                if (data?.error) { renderHomeRetry('home-recommended'); break; }
                const tracks = Array.isArray(data) ? data : (data?.tracks || []);
                renderRecommendations(tracks);
                break;
            }

            case 'artists_ready':
                if (!isCurrentHomeEvent('home-artists', data)) break;
                clearFeedTimeout('home-artists');
                if (data?.error) { renderHomeRetry('home-artists'); break; }
                if (data) {
                    const artists = Array.isArray(data) ? data : (data.artists || []);
                    renderArtists(artists);
                }
                break;

            case 'artists_avatars_ready':
                window.dispatchEvent(new CustomEvent('app:artists_avatars_ready', { detail: data }));
                break;

            case 'releases_ready':
                if (!isCurrentHomeEvent('home-releases', data)) break;
                clearFeedTimeout('home-releases');
                if (data?.error) { renderHomeRetry('home-releases'); break; }
                if (data) {
                    const tracks = Array.isArray(data) ? data : (data.tracks || []);
                    renderReleases(tracks);
                }
                break;

            case 'mixes_ready':
                if (!isCurrentHomeEvent('home-mixes', data)) break;
                clearFeedTimeout('home-mixes');
                if (data?.error) { renderHomeRetry('home-mixes'); break; }
                if (data) {
                    const items = Array.isArray(data) ? data : (data.tracks || data.mixes || []);
                    renderMixes(items);
                }
                break;
                
            // BUG-U3-003: мёртвый case 'mood_playlists_ready' удалён — событие не
            // эмитится бэкендом (фича «Под настроение» снята; секция
            // section-home-mood удалена из index.html и home.js).

            case 'favorites_updated':
                document.dispatchEvent(new CustomEvent('nedotify:favorites_updated', { detail: data }));
                window.dispatchEvent(new CustomEvent('nedotify:favorites_updated', { detail: data }));
            case 'library_updated':
            case 'playlists_updated':
            case 'playlist_changed':
                // O-5: debounce burst events — a single refresh 300ms after the last one
                if (libraryRefreshTimer) clearTimeout(libraryRefreshTimer);
                libraryRefreshTimer = setTimeout(() => {
                    libraryRefreshTimer = null;
                    // Collage caches must refetch after any playlist mutation
                    window.dispatchEvent(new CustomEvent('nedotify:playlists_changed'));
                    const nextTrackChange = isNextTrackChange;
                    isNextTrackChange = false;
                    if (isPageVisible('library')) {
                        loadLibrary();
                        loadPlaylists();
                        if (window.refreshActiveLibraryView) window.refreshActiveLibraryView();
                    }
                    // O-5: only re-render the section the user can actually see
                    if (isPageVisible('home')) loadHome(nextTrackChange);
                }, 300);
                break;

            case 'mini_player_toggled':
                window.dispatchEvent(new CustomEvent('nedotify:mini_player_toggled', { detail: data }));
                break;

            case 'scan_progress':
                window.dispatchEvent(new CustomEvent('nedotify:scan_progress', { detail: data }));
                break;

            case 'scan_complete':
                window.dispatchEvent(new CustomEvent('nedotify:scan_complete', { detail: data }));
                break;

            case 'listening_history_cleared':
                if (data?.success === true && typeof data.listening_session === 'string') {
                    const track = getCurrentTrack();
                    if (track && typeof track === 'object') track.listening_session = data.listening_session;
                }
                window.dispatchEvent(new CustomEvent('nedotify:listening_history_cleared', { detail: data }));
                break;

            case 'history_updated':
                document.dispatchEvent(new CustomEvent('nedotify:history_updated', { detail: data }));
                window.dispatchEvent(new CustomEvent('nedotify:history_updated', { detail: data }));
                if (isPageVisible('library') && window.refreshActiveLibraryView) {
                    window.refreshActiveLibraryView();
                }
                break;

            case 'batch_download_started':
                document.dispatchEvent(new CustomEvent('nedotify:batch_download_started', { detail: data }));
                break;

            case 'batch_download_progress':
                document.dispatchEvent(new CustomEvent('nedotify:batch_download_progress', { detail: data }));
                break;

            case 'batch_download_finished':
                document.dispatchEvent(new CustomEvent('nedotify:batch_download_finished', { detail: data }));
                break;

            case 'batch_download_cancelled':
                document.dispatchEvent(new CustomEvent('nedotify:batch_download_cancelled', { detail: data }));
                break;

            case 'download_complete':
                document.dispatchEvent(new CustomEvent('nedotify:track_downloaded', { detail: data }));
                break;

            case 'download_failed': {
                const dlErr = (data?.error || data?.message || 'Неизвестная ошибка').toString();

                document.dispatchEvent(new CustomEvent('nedotify:operation_error', { detail: { ...data, method: 'download_track' } }));
                document.dispatchEvent(new CustomEvent('nedotify:track_download_failed', { detail: data }));
                break;
            }

            case 'queue_updated':
                // Will be handled by queue.js listening to pywebview event directly, or we can dispatch
                document.dispatchEvent(new CustomEvent('nedotify:queue_updated', { detail: data }));
                break;

            case 'shuffle_changed': {
                const shuffleOn = !!data?.state;
                const btnShufflePP = document.getElementById('pp-btn-shuffle');
                if (btnShufflePP) btnShufflePP.classList.toggle('active', shuffleOn);
                const btnShufflePB = document.getElementById('pb-btn-shuffle');
                if (btnShufflePB) btnShufflePB.classList.toggle('active', shuffleOn);
                break;
            }

            case 'repeat_changed': {
                const repeatMode = data?.state ?? 'off';
                const repeatOn = repeatMode !== 'off';
                const ppRepeat = document.getElementById('pp-btn-repeat');
                if (ppRepeat) {
                    ppRepeat.classList.toggle('active', repeatOn);
                    syncRepeatIcon(ppRepeat, repeatMode);
                }
                const pbRepeat = document.getElementById('pb-btn-repeat');
                if (pbRepeat) {
                    pbRepeat.classList.toggle('active', repeatOn);
                    syncRepeatIcon(pbRepeat, repeatMode);
                }
                break;
            }

            case 'storage_info':
            case 'storage_updated':
                onStorageInfo(data);
                break;

            case 'error': {
                console.error('Backend Error:', data);
                const cleanErr = (data || 'Неизвестная ошибка').toString().replace(/\x1b\[[0-9;]*m/g, '');
                if (Date.now() - lastAudioErrorAt > 300) showToast('Не удалось выполнить действие. Подробности сохранены в журнале.', 'error');
                onStateChanged('stopped');
                break;
            }

            // The bridge promise rejection is the UI error channel. This event
            // is diagnostic only; surfacing it here would duplicate the
            // caller's contextual status, toast, or operation error panel.
            case 'api_error': {
                const apiMethod = (data && data.method) ? String(data.method) : '';
                const errorCode = (data && data.code) ? String(data.code) : 'unknown';
                console.error('Bridge API Error:', apiMethod, errorCode);
                break;
            }

            case 'lyrics_ready':
                document.dispatchEvent(new CustomEvent('nedotify:lyrics_ready', { detail: data }));
                break;

            case 'album_details_ready':
                document.dispatchEvent(new CustomEvent('nedotify:album_details_ready', { detail: data }));
                break;

            case 'artist_candidates_ready':
                document.dispatchEvent(new CustomEvent('nedotify:artist_candidates_ready', { detail: data }));
                break;

            case 'artist_profile_ready':
                document.dispatchEvent(new CustomEvent('nedotify:artist_profile_ready', { detail: data }));
                window.dispatchEvent(new CustomEvent('app:artist_profile_ready', { detail: data }));
                break;

            case 'artist_profile_error':
                document.dispatchEvent(new CustomEvent('nedotify:artist_profile_error', { detail: data }));
                window.dispatchEvent(new CustomEvent('app:artist_profile_error', { detail: data }));
                break;

            case 'track_wave_ready':
                window.dispatchEvent(new CustomEvent('nedotify:track_wave_ready', { detail: data }));
                break;


            case 'zapret_update_checked':
                window.dispatchEvent(new CustomEvent('nedotify:zapret_update_checked', { detail: data }));
                break;

            // Zapret lifecycle events (late crash BUG-025, non-stoppable exit
            // BUG-009, network loss BUG-036, download phases BUG-038, autostart
            // failure BUG-033). Routing only: toasts, toggle re-syncs and the
            // status text live in the settings-panel subscriber.
            case 'zapret_crashed':
            case 'zapret_network_issue':
            case 'zapret_still_running':
            case 'zapret_autostart_failed':
            case 'zapret_download_started':
            case 'zapret_download_finished':
            case 'zapret_download_failed':
                window.dispatchEvent(new CustomEvent('nedotify:' + eventName, { detail: data }));
                break;

            case 'yandex_device_auth_code':
                document.dispatchEvent(new CustomEvent('nedotify:yandex_device_auth_code', { detail: data }));
                break;

            case 'yandex_device_auth_result':
                document.dispatchEvent(new CustomEvent('nedotify:yandex_device_auth_result', { detail: data }));
                break;

            case 'audio_error': {
                lastAudioErrorAt = Date.now();
                const cleanAudioErr = (data?.message || '').toString().replace(/\x1b\[[0-9;]*m/g, '');

                document.dispatchEvent(new CustomEvent('nedotify:operation_error', { detail: { ...data, source: 'audio' } }));
                window._pendingResolveKey = null;
                onStateChanged('stopped');
                break;
            }

            case 'theme_changed':
                window.dispatchEvent(new CustomEvent('nedotify:theme_changed', { detail: data }));
                break;

            case 'mute_changed':
                applyMuteState(!!data?.muted);
                break;

            case 'queue_ended':
                // Backend reached the end of the queue: release the audio and the
                // UI state instead of leaving a stale "playing" look on a stream
                // that is still running (pressing "next" on the last track).
                stopPlaybackForQueueEnd();
                onStateChanged('stopped');
                document.dispatchEvent(new CustomEvent('nedotify:queue_ended', { detail: data }));
                break;

            case 'track_updated': {
                // Metadata-only refresh of the currently playing track (title/artist/cover).
                // Does not touch playback: onTrackChanged would restart the stream.
                const cur = getCurrentTrack();
                const curKey = cur ? (cur.id ?? cur.source_id) : undefined;
                if (data && curKey != null && String(curKey) === String(data.id ?? data.source_id)) {
                    Object.assign(cur, data, { stream_url: cur.stream_url, file_path: cur.file_path });
                    document.dispatchEvent(new CustomEvent('nedotify:track_changed', { detail: cur }));
                }
                document.dispatchEvent(new CustomEvent('nedotify:track_updated', { detail: data }));
                window.dispatchEvent(new CustomEvent('nedotify:track_updated', { detail: data }));
                if (isPageVisible('library') && window.refreshActiveLibraryView) {
                    window.refreshActiveLibraryView();
                }
                break;
            }

            // ================= FUTURE EVENTS / DEPRECATED =================
            // NOTE: yandex_device_auth_* are handled above; do not duplicate
            // them here - JS switch silently shadows the first handler.
            // BUG-U3-010: 'proxy_status' — живое событие (эмитят core/proxy.py
            // при смене статуса прокси). Обрабатывается подписчиком в main.js
            // (баннер состояния прокси), здесь — тихий пропуск, чтобы не
            // попадать в default-лог 'Unknown event'.
            // BUG-U3-008: мёртвый case 'smart_home_ready' удалён — событие не
            // эмитится; живой путь — 'authentic_home_ready' (обработан выше).
            case 'proxy_status':
                break;

            case 'yandex_auth_error':
                setYandexWarning(data?.invalid === true);
                if (data?.invalid === true) showToast('Авторизация Яндекс Музыки истекла. Подключите аккаунт заново в настройках.', 'warning');
                break;

            case 'yandex_subscription_status':
                showToast(data?.has_plus === true ? 'Подписка Яндекс Плюс активна' : 'Подписка Яндекс Плюс не найдена', 'info');
                break;

            default:
                console.log('Unknown event:', eventName);
        }
    };
    if (!deferReplay) flushPythonEvents();
}

// BUG-U3-008/U3-010: механизм logFutureEvent удалён вместе с последними
// записями FUTURE/DEPRECATED (smart_home_ready, proxy_status) — блок опустел,
// а «deprecated»-маркер на живом proxy_status дезинформировал сопровождающих.

// Mirrors player.js updateRepeatIcon so backend repeat_changed syncs both bars.
function syncRepeatIcon(btn, mode) {
    if (!btn) return;
    if (mode === 'one') {
        btn.innerHTML = '<i data-lucide="repeat-1" style="width:16px;height:16px"></i>';
    } else {
        btn.innerHTML = '<i data-lucide="repeat" style="width:16px;height:16px"></i>';
    }
    renderIcons();
}



