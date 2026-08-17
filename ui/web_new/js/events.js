// NeDotify — Python Event Bridge
import { onTrackChanged, onStateChanged, onPositionChanged, applySettings } from './player.js?v=20260817_2';
import { onSearchResults } from './search.js?v=20260817_2';
import { renderPopular, renderRecommendations, renderReleases, renderMixes, renderArtists, loadHome, clearFeedTimeout, renderAuthenticHome } from './home.js?v=20260817_2';
import { loadLibrary, loadDownloaded, loadPlaylists } from './library.js?v=20260817_2';
import { applySettingsFromBackend, onStorageInfo, setYandexWarning } from './settings.js?v=20260817_2';
import { showToast, renderIcons, escapeHtml } from './utils.js?v=20260817_2';

let isNextTrackChange = false;

// O-5: track the visible page so hidden sections are not re-rendered on burst events
let currentPageId = 'home';
window.addEventListener('nedotify:page_changed', (e) => { currentPageId = e.detail; });

function isPageVisible(pageId) {
    const el = document.getElementById('view-' + pageId);
    return !!(el && el.classList.contains('active'));
}

// O-5: debounce (300ms) library refresh bursts (e.g. batch downloads) into a single re-render
let libraryRefreshTimer = null;

export function initEvents() {
    window.onPythonEvent = function(eventName, data) {
        console.log('Python Event:', eventName, data);

        switch (eventName) {
            case 'track_changed':
                isNextTrackChange = true;
                onTrackChanged(data);
                document.dispatchEvent(new CustomEvent('nedotify:track_changed', { detail: data }));
                break;

            case 'state_changed':
                // Normalize payload which could be string or { state: "..." }
                const state = (typeof data === 'object' && data !== null && 'state' in data) ? data.state : data;
                onStateChanged(state);
                break;

            case 'position_changed':
                // Pos and duration should be normalized to milliseconds for onPositionChanged
                let posMs = data.position_ms !== undefined ? data.position_ms : (data.pos !== undefined ? Math.round(data.pos * 1000) : 0);
                let durationMs = data.duration_ms !== undefined ? data.duration_ms : (data.duration !== undefined ? Math.round(data.duration * 1000) : 0);
                onPositionChanged(posMs, durationMs);
                document.dispatchEvent(new CustomEvent('nedotify:position_changed', { detail: { pos: posMs / 1000, duration: durationMs / 1000, posMs, durationMs } }));
                break;

            case 'search_results':
            case 'search_completed':
                onSearchResults(data);
                window.dispatchEvent(new CustomEvent('app:search_results', { detail: data }));
                break;
                
            case 'authentic_home_ready':
                if (data && data.sections) {
                    renderAuthenticHome(data.sections);
                }
                break;
                
            case 'yt_playlist_ready':
                if (data && data.tracks && data.tracks.length > 0) {
                    if (window.pywebview && window.pywebview.api && window.pywebview.api.play_track) {
                        window.pywebview.api.play_track(data.tracks[0], data.tracks);
                    }
                } else {
                    showToast('Не удалось получить треки', 'error');
                }
                break;
                
            case 'authentic_home_error':
                const authContainer = document.getElementById('home-authentic-feed');
                if (authContainer) {
                    authContainer.innerHTML = `<div style="padding:20px; text-align:center; color:var(--text-sec);">Ошибка: ${escapeHtml(data.error)}</div>`;
                }
                break;

            case 'popular_results':
                clearFeedTimeout('home-popular');
                if (data) {
                    const tracks = Array.isArray(data) ? data : (data.tracks || []);
                    renderPopular(tracks);
                }
                break;

            case 'feed_ready':
            case 'recommendations_ready':
                clearFeedTimeout('home-recommended');
                if (data) {
                    const tracks = Array.isArray(data) ? data : (data.tracks || []);
                    if (tracks.length > 0) renderRecommendations(tracks);
                }
                break;

            case 'artists_ready':
                clearFeedTimeout('home-artists');
                if (data) {
                    const artists = Array.isArray(data) ? data : (data.artists || []);
                    renderArtists(artists);
                }
                break;

            case 'releases_ready':
                clearFeedTimeout('home-releases');
                if (data) {
                    const tracks = Array.isArray(data) ? data : (data.tracks || []);
                    renderReleases(tracks);
                }
                break;

            case 'mixes_ready':
                clearFeedTimeout('home-mixes');
                if (data) {
                    const items = Array.isArray(data) ? data : (data.tracks || data.mixes || []);
                    renderMixes(items);
                }
                break;
                
            case 'mood_playlists_ready':
                window.dispatchEvent(new CustomEvent('app:mood_playlists_ready', { detail: data }));
                break;

            case 'library_updated':
            case 'favorites_updated':
            case 'playlists_updated':
            case 'playlist_changed':
                // O-5: debounce burst events — a single refresh 300ms after the last one
                if (libraryRefreshTimer) clearTimeout(libraryRefreshTimer);
                libraryRefreshTimer = setTimeout(() => {
                    libraryRefreshTimer = null;
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
                if (data?.is_mini) {
                    document.body.classList.add('mini-player-active');
                } else {
                    document.body.classList.remove('mini-player-active');
                }
                window.dispatchEvent(new CustomEvent('nedotify:mini_player_toggled', { detail: data }));
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
            case 'track_downloaded':
                loadDownloaded();
                loadPlaylists();
                if (window.refreshActiveLibraryView) window.refreshActiveLibraryView();
                document.dispatchEvent(new CustomEvent('nedotify:track_downloaded', { detail: data }));
                break;

            case 'queue_updated':
                // Will be handled by queue.js listening to pywebview event directly, or we can dispatch
                document.dispatchEvent(new CustomEvent('nedotify:queue_updated', { detail: data }));
                break;

            case 'shuffle_changed':
                const btnShuffle = document.getElementById('pp-btn-shuffle');
                if (btnShuffle) btnShuffle.classList.toggle('active', !!data?.state);
                break;

            case 'repeat_changed':
                const ppRepeat = document.getElementById('pp-btn-repeat');
                if (ppRepeat) ppRepeat.classList.toggle('active', data?.state !== 'off');
                break;

            case 'setting_changed':
                // data = { key, value, category }
                break;

            case 'storage_info':
            case 'storage_info_updated':
                onStorageInfo(data);
                break;

            case 'error':
                console.error('Backend Error:', data);
                const cleanErr = (data || 'Неизвестная ошибка').toString().replace(/\x1b\[[0-9;]*m/g, '');
                showToast('Ошибка: ' + cleanErr, 'error');
                onStateChanged('stopped');
                break;

            case 'lyrics_ready':
                document.dispatchEvent(new CustomEvent('nedotify:lyrics_ready', { detail: data }));
                break;

            case 'track_wave_ready':
                window.dispatchEvent(new CustomEvent('nedotify:track_wave_ready', { detail: data }));
                break;

            case 'yandex_device_auth_code':
                document.dispatchEvent(new CustomEvent('nedotify:yandex_device_auth_code', { detail: data }));
                break;

            case 'yandex_device_auth_result':
                document.dispatchEvent(new CustomEvent('nedotify:yandex_device_auth_result', { detail: data }));
                break;

            case 'audio_error':
                const cleanAudioErr = (data?.message || '').toString().replace(/\x1b\[[0-9;]*m/g, '');
                showToast('Ошибка воспроизведения: ' + cleanAudioErr, 'error');
                window._pendingResolveKey = null;
                onStateChanged('stopped');
                break;

            case 'theme_changed':
                window.dispatchEvent(new CustomEvent('nedotify:theme_changed', { detail: data }));
                break;

            // ================= FUTURE EVENTS / DEPRECATED =================
            case 'proxy_status':
            case 'smart_home_ready':
            case 'yandex_auth_error':
            case 'yandex_device_auth_code':
            case 'yandex_device_auth_result':
                logFutureEvent(eventName, data);
                break;

            default:
                console.log('Unknown event:', eventName);
        }
    };
}

const loggedFutureEvents = new Set();
function logFutureEvent(eventName, data) {
    if (!loggedFutureEvents.has(eventName)) {
        console.info(`[NeDotify] Future/deprecated event ignored: ${eventName}`, data || '');
        loggedFutureEvents.add(eventName);
    }
}



