// NeDotify вЂ” Python Event Bridge
import { onTrackChanged, onStateChanged, onPositionChanged, applySettings } from './player.js?v=19';
import { onSearchResults } from './search.js?v=19';
import { renderPopular, renderRecommendations, renderReleases, renderMixes, renderArtists, loadHome, clearFeedTimeout, renderAuthenticHome } from './home.js?v=19';
import { loadLibrary, loadFavorites, loadDownloaded, loadPlaylists } from './library.js?v=19';
import { applySettingsFromBackend, onStorageInfo, setYandexWarning } from './settings.js?v=19';
import { showToast, renderIcons } from './utils.js?v=19';

let isNextTrackChange = false;

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
                onStateChanged(data);
                break;

            case 'position_changed':
                onPositionChanged(data.pos, data.duration);
                document.dispatchEvent(new CustomEvent('nedotify:position_changed', { detail: data }));
                break;

            case 'search_results':
                onSearchResults(data);
                window.dispatchEvent(new CustomEvent('app:search_results', { detail: data }));
                break;
                
            case 'authentic_home_ready':
                if (data && data.sections) {
                    renderAuthenticHome(data.sections);
                }
                break;
                
            case 'smart_home_ready':
                if (data && data.sections) {
                    const greetingEl = document.getElementById('home-greeting');
                    if (greetingEl && data.greeting) {
                        greetingEl.textContent = data.greeting;
                    }
                    renderAuthenticHome(data.sections);
                }
                break;
                
            case 'yt_playlist_ready':
                if (data && data.tracks && data.tracks.length > 0) {
                    if (window.pywebview && window.pywebview.api && window.pywebview.api.play_track) {
                        window.pywebview.api.play_track(data.tracks[0], data.tracks);
                    }
                } else {
                    showToast('Не удалось загрузить треки микса', 'error');
                }
                break;
                
            case 'authentic_home_error':
                const authContainer = document.getElementById('home-authentic-feed');
                if (authContainer) {
                    authContainer.innerHTML = `<div style="padding:20px; text-align:center; color:var(--text-sec);">Ошибка загрузки: ${data.error}</div>`;
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
            case 'playlists_updated':
                loadLibrary();
                loadPlaylists();
                loadHome(isNextTrackChange);
                isNextTrackChange = false;
                break;

            case 'mini_player_toggled':
                document.body.classList.toggle('mini-player-active', !!data?.is_mini);
                break;

            case 'track_downloaded':
                loadDownloaded();
                loadPlaylists();
                document.dispatchEvent(new CustomEvent('nedotify:track_downloaded', { detail: data }));
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

            case 'yandex_auth_error':
                setYandexWarning(!!data);
                if (data) {
                    showToast('Ошибка авторизации Яндекс Музыка. Ограничение 30 сек.', 'error');
                }
                break;

            case 'yandex_device_auth_code': {
                const statusEl = document.getElementById('yandex-device-status');
                if (statusEl && data) {
                    statusEl.style.display = 'block';
                    statusEl.innerHTML = `Откройте <a href="#" onclick="if(window.pywebview){window.pywebview.api.open_url('${data.url}')}" style="color:var(--primary);text-decoration:underline;cursor:pointer">${data.url}</a> и введите код: <b style="color:var(--primary);font-size:14px;letter-spacing:1px">${data.user_code}</b>`;
                }
                break;
            }

            case 'yandex_device_auth_result': {
                const statusEl2 = document.getElementById('yandex-device-status');
                const btn = document.getElementById('btn-yandex-auth');
                if (data && data.success) {
                    if (statusEl2) {
                        statusEl2.innerHTML = '✅ Токен получен! Яндекс Музыка подключена.';
                        statusEl2.style.color = 'var(--primary)';
                    }
                    const tokenInput = document.getElementById('input-yandex-token');
                    if (tokenInput) tokenInput.value = data.token;
                    setYandexWarning(false);
                    showToast('Яндекс Музыка авторизована! Полный доступ к трекам.', 'success');
                } else if (data && data.error) {
                    if (statusEl2) {
                        statusEl2.innerHTML = 'вќЊ ' + data.error;
                        statusEl2.style.color = 'var(--error)';
                    }
                    showToast(data.error, 'error');
                }
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = '🔑 Получить токен';
                }
                break;
            }

            default:
                console.log('Unknown event:', eventName);
        }
    };
}



