// NeDotify - Main Entry Point
import { initPlayer, applySettings, playTrack } from './player.js?v=20260814_9';
import { initPages, showPage } from './pages.js?v=20260814_9';
import { initSearch } from './search.js?v=20260814_9';
import { loadHome } from './home.js?v=20260814_9';
import { initLibrary, loadLibrary, loadPlaylists, openPlaylistMenu, createPlaylist } from './library.js?v=20260814_9';
import { initSettings, applySettingsFromBackend, loadSettings } from './settings.js?v=20260814_9';
import { initParticles } from './particles.js?v=20260814_9';
import { initVisualizer } from './visualizer.js?v=20260814_9';
import { initEvents } from './events.js?v=20260814_9';
import { renderIcons, handleImageError, showTrackContextMenu, escapeHtml } from './utils.js?v=20260814_9';
import { initLyrics } from './lyrics.js?v=20260814_9';
import { initEqualizer } from './equalizer.js?v=20260814_9';
import { initQueue } from './queue.js?v=20260814_9';
import { initOnboarding } from './onboarding.js?v=20260814_9';
import { initContextMenu } from './contextmenu.js?v=20260814_9';
import { initHotkeys } from './hotkeys.js?v=20260814_9';
import { initEfficiency } from './efficiency.js?v=20260814_9';




// Global NeDotify namespace for cross-module communication
window.loadProfile = loadProfile;
window.NeDotify = {
    openPlaylistMenu: openPlaylistMenu,
    createPlaylist: createPlaylist,
    loadHome: loadHome,
    loadLibrary: loadLibrary,
    loadProfile: loadProfile,
    loadSettings: loadSettings,
    handleImageError: handleImageError,
    showTrackContextMenu: showTrackContextMenu,
    showPage: showPage,
    playTrack: playTrack,
    playNext: (track) => {
        if (window.pywebview?.api?.play_next) {
            window.pywebview.api.play_next(track);
        }
    },
    addToQueue: (track) => {
        if (window.pywebview?.api?.add_to_queue) {
            window.pywebview.api.add_to_queue(track);
        }
    },
    downloadTrack: (track) => {
        if (!track) return;
        if (window.pywebview?.api?.download_track) {
            window.pywebview.api.download_track(track);
        }
    },
    startTrackWave: (seedTrack) => {
        if (!seedTrack) return;
        const toastFn = (msg, type) => window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg, type } }));
        toastFn(`📻 Собираем волну по треку «${seedTrack.title || 'выбранному треку'}»...`, 'info');
        
        // Play the seed track first
        if (window.pywebview?.api?.play_track) {
            window.pywebview.api.play_track(seedTrack, [seedTrack], 0);
        }

        if (!window.pywebview?.api?.get_track_wave) return;

        const longWaitTimer = setTimeout(() => toastFn('⏳ Волна собирается дольше обычного...', 'info'), 8000);
        const handler = (e) => {
            clearTimeout(longWaitTimer);
            window.removeEventListener('nedotify:track_wave_ready', handler);
            const tracks = (e.detail && e.detail.tracks) || [];
            if (tracks.length > 0) {
                for (const t of tracks) {
                    if (window.pywebview?.api?.add_to_queue) {
                        window.pywebview.api.add_to_queue(t);
                    }
                }
                toastFn(`📻 В волну добавлено ${tracks.length} треков!`, 'success');
            } else {
                toastFn('Не удалось найти похожие треки для волны', 'warning');
            }
        };
        window.addEventListener('nedotify:track_wave_ready', handler);

        const seedId = seedTrack.id || seedTrack.source_id;
        try {
            window.pywebview.api.get_track_wave(seedTrack, 15, seedId ? [seedId] : []);
        } catch(e) {
            clearTimeout(longWaitTimer);
            window.removeEventListener('nedotify:track_wave_ready', handler);
            console.error('Error starting track wave:', e);
        }
    },
    toggleMiniPlayerMode: toggleMiniPlayerMode
};

export async function toggleMiniPlayerMode(targetState) {
    const isCurrentlyMini = document.body.classList.contains('mini-player-active');
    if (targetState === undefined) targetState = !isCurrentlyMini;

    if (targetState) {
        document.body.classList.add('mini-player-active');
        if (window.pywebview?.api?.toggle_mini_player) {
            try { await window.pywebview.api.toggle_mini_player(true); } catch(e) {}
        }
    } else {
        document.body.classList.remove('mini-player-active');
        if (window.pywebview?.api?.toggle_mini_player) {
            try { await window.pywebview.api.toggle_mini_player(false); } catch(e) {}
        }
    }
}
window.toggleMiniPlayerMode = toggleMiniPlayerMode;

// Instant restoration of Theme, Particles, Blur & Transparency on boot
(function restorePreferences() {
    try {
        const theme = JSON.parse(localStorage.getItem('nedotify_ui_theme') || '"dark"');
        document.documentElement.setAttribute('data-theme', theme);

        const particlesEnabled = JSON.parse(localStorage.getItem('nedotify_ui_particles_enabled') ?? 'true');
        const bg = document.getElementById('particles-bg');
        if (bg) bg.style.display = particlesEnabled ? 'block' : 'none';

        const glassBlur = JSON.parse(localStorage.getItem('nedotify_theme_glass_blur') ?? '20');
        document.documentElement.style.setProperty('--glass-blur', `${glassBlur}px`);

        const customPrimary = localStorage.getItem('nedotify_theme_custom_primary');
        if (customPrimary) {
            const parsed = JSON.parse(customPrimary);
            if (parsed) document.documentElement.style.setProperty('--primary', parsed);
        }

        const transEnabled = JSON.parse(localStorage.getItem('nedotify_theme_transparency_enabled') ?? 'true');
        const transLevel = JSON.parse(localStorage.getItem('nedotify_theme_transparency_level') ?? '80');
        const opacity = transEnabled ? (transLevel / 100) : 1.0;
        document.documentElement.style.setProperty('--app-bg-opacity', opacity);

        // Instant restoration of Optimization preferences (Presets, Blur, Glow, Limit State)
        const optPreset = JSON.parse(localStorage.getItem('nedotify_optimization_performance_preset') ?? '"high"');
        if (optPreset === 'medium') document.documentElement.classList.add('perf-medium');
        else if (optPreset === 'low') document.documentElement.classList.add('perf-low');

        const optLimit = JSON.parse(localStorage.getItem('nedotify_optimization_limit_state') ?? '"minimize"');
        document.documentElement.classList.add(`limit-state-${optLimit}`);

        const optBlur = JSON.parse(localStorage.getItem('nedotify_optimization_blur_quality') ?? '"hq"');
        const blurMap = { hq: { sm: '8px', md: '14px', lg: '18px', xl: '24px' },
                          mid: { sm: '4px', md: '8px', lg: '10px', xl: '12px' },
                          fast: { sm: '2px', md: '4px', lg: '6px', xl: '8px' },
                          off: { sm: '0px', md: '0px', lg: '0px', xl: '0px' } };
        const bVal = blurMap[optBlur] || blurMap.hq;
        document.documentElement.style.setProperty('--blur-sm', bVal.sm);
        document.documentElement.style.setProperty('--blur-md', bVal.md);
        document.documentElement.style.setProperty('--blur-lg', bVal.lg);
        document.documentElement.style.setProperty('--blur-xl', bVal.xl);

        const optGlow = JSON.parse(localStorage.getItem('nedotify_optimization_glow_quality') ?? '"full"');
        const glowMap = { full: { blur: '40px', opacity: '0.55' },
                          soft: { blur: '22px', opacity: '0.35' },
                          off: { blur: '0px', opacity: '0' } };
        const gVal = glowMap[optGlow] || glowMap.full;
        document.documentElement.style.setProperty('--player-glow-blur', gVal.blur);
        document.documentElement.style.setProperty('--player-glow-opacity', gVal.opacity);

        // Battery Saver Mode Detector & Auto Optimization with Smooth Transitions & Toasts
        function setupBatterySaver() {
            if ('getBattery' in navigator) {
                navigator.getBattery().then(battery => {
                    let firstRun = true;
                    const updateBatteryStatus = () => {
                        const isBatteryMode = !battery.charging;
                        const wasActive = document.documentElement.classList.contains('battery-saver-active');
                        
                        if (wasActive !== isBatteryMode || firstRun) {
                            // Enable CSS smooth transition class
                            document.documentElement.classList.add('battery-saver-transition');
                            document.documentElement.classList.toggle('battery-saver-active', isBatteryMode);
                            
                            // Emit global event for particles/visualizer FPS throttling
                            window.dispatchEvent(new CustomEvent('nedotify:battery_saver_changed', { detail: { isBatteryMode } }));

                            // Show toast notification when charging status changes
                            if (!firstRun) {
                                if (isBatteryMode) {
                                    window.dispatchEvent(new CustomEvent('nedotify:toast', {
                                        detail: { msg: '🔋 Переход на батарею: Включен энергосберегающий режим', type: 'info' }
                                    }));
                                } else {
                                    window.dispatchEvent(new CustomEvent('nedotify:toast', {
                                        detail: { msg: '⚡ Подключено к сети: Максимальная производительность', type: 'success' }
                                    }));
                                }
                            }
                            
                            // Remove transition helper after animation finishes (0.6s)
                            setTimeout(() => {
                                document.documentElement.classList.remove('battery-saver-transition');
                            }, 600);
                        }
                        firstRun = false;
                    };
                    updateBatteryStatus();
                    battery.addEventListener('chargingchange', updateBatteryStatus);
                }).catch(() => {});
            }
        }
        setupBatterySaver();

        // Instant background image restoration on boot
        const customBgRaw = localStorage.getItem('nedotify_theme_custom_bg_image');
        if (customBgRaw) {
            const bgUrl = JSON.parse(customBgRaw);
            if (bgUrl) {
                const blur = JSON.parse(localStorage.getItem('nedotify_theme_bg_blur') || '0');
                const dim = JSON.parse(localStorage.getItem('nedotify_theme_bg_dim') || '30');
                let bgLayer = document.getElementById('custom-bg-layer');
                let dimLayer = document.getElementById('custom-bg-dim-layer');
                if (!bgLayer) {
                    bgLayer = document.createElement('div');
                    bgLayer.id = 'custom-bg-layer';
                    bgLayer.style.cssText = 'position:fixed; top:0; left:0; width:100vw; height:100vh; z-index:-2; pointer-events:none; background-size:cover; background-position:center; transition: filter 0.3s ease;';
                    document.body.insertBefore(bgLayer, document.body.firstChild);
                }
                if (!dimLayer) {
                    dimLayer = document.createElement('div');
                    dimLayer.id = 'custom-bg-dim-layer';
                    dimLayer.style.cssText = 'position:fixed; top:0; left:0; width:100vw; height:100vh; z-index:-1; pointer-events:none; transition: background 0.3s ease;';
                    document.body.insertBefore(dimLayer, document.body.firstChild);
                }
                bgLayer.style.display = 'block';
                bgLayer.style.backgroundImage = `url("${bgUrl}")`;
                bgLayer.style.filter = `blur(${blur}px)`;
                dimLayer.style.display = 'block';
                dimLayer.style.background = `rgba(0, 0, 0, ${dim / 100})`;
            }
        }
    } catch(e) {}
})();

// Wait for PyWebView to be ready
window.addEventListener('pywebviewready', () => {
    console.log('PyWebView Ready!');
    init();
});

// Fallback: if pywebviewready doesn't fire (standalone dev mode)
setTimeout(() => {
    if (!window._nedotifyInitialized) init();
}, 2000);

async function init() {
    if (window._nedotifyInitialized) return;
    window._nedotifyInitialized = true;
    try {
        // Fetch settings from backend early
        if (window.pywebview && window.pywebview.api) {
            try {
                const settings = await window.pywebview.api.get_settings();
                if (settings) {
                    window.settings = settings;
                    applySettings(settings);
                    applySettingsFromBackend(settings);
                }

            } catch (e) {
                console.error('Error fetching settings early:', e);
            }
        }

        // Init Onboarding next (blocks UI if first launch)
        if (typeof initOnboarding === 'function') {
            initOnboarding();
        }



        initContextMenu();
        initHotkeys();
        initEfficiency();

        // Window controls (frameless) - Initialize first to ensure app can always be closed
        document.getElementById('btn-mini-player')?.addEventListener('click', () => {
            toggleMiniPlayerMode();
        });
        document.getElementById('btn-minimize')?.addEventListener('click', () => {
            if (window.pywebview?.api) window.pywebview.api.minimize_window();
        });
        document.getElementById('btn-maximize')?.addEventListener('click', () => {
            if (window.pywebview?.api?.maximize) window.pywebview.api.maximize();
        });
        document.getElementById('btn-close')?.addEventListener('click', () => {
            if (window.pywebview?.api) window.pywebview.api.close_window();
        });

        const safeInit = async (name, fn) => {
            try {
                await fn();
                console.log(`[Init] ${name} loaded`);
            } catch (err) {
                console.error(`[Init] ${name} failed to load:`, err);
            }
        };

        // Initialize all modules safely
        await safeInit('Icons', () => new Promise((resolve) => {
            const runIcons = () => {
                try { renderIcons(); } catch (err) { console.error('renderIcons failed:', err); }
                resolve();
            };
            // Defer icon rendering past the first paint (requestIdleCallback when available)
            if (window.requestIdleCallback) {
                window.requestIdleCallback(runIcons, { timeout: 300 });
            } else {
                setTimeout(runIcons, 50);
            }
        }));
        await safeInit('Events', () => initEvents());
        await safeInit('Pages', () => initPages());
        await safeInit('Player', () => initPlayer());
        await safeInit('Search', () => initSearch());
        await safeInit('Library', () => initLibrary());
        await safeInit('Settings', () => initSettings());
        await safeInit('Particles', () => initParticles());
        await safeInit('Visualizer', () => initVisualizer());
        await safeInit('Lyrics', () => initLyrics());
        await safeInit('Equalizer', () => initEqualizer());
        await safeInit('Queue', () => initQueue());
        
        // Sync lyrics overlay title with current track
        try {
            const _lyricsTrackSync = (eventName, data) => {
                if (eventName === 'track_changed' && data) {
                    const titleEl = document.getElementById('lyrics-title');
                    if (titleEl && data.title) {
                        titleEl.textContent = data.title + (data.artist ? ' — ' + data.artist : '');
                    }
                }
            };
            function _handleNetworkEvent(eventName, data) {
                if (eventName === 'network_status') {
                    const banner = document.getElementById('network-banner');
                    const bannerText = document.getElementById('network-banner-text');
                    if (!banner) return;
                    
                    banner.className = 'network-banner';
                    if (data.online) {
                        banner.classList.add('hidden');
                    } else if (data.status === 'degraded') {
                        banner.classList.add('degraded');
                        bannerText.textContent = 'Нестабильное подключение (возможны задержки)';
                    } else {
                        bannerText.textContent = 'Нет подключения к сети. Локальный режим.';
                    }
                } else if (eventName === 'proxy_status') {
                    const banner = document.getElementById('network-banner');
                    const bannerText = document.getElementById('network-banner-text');
                    if (!banner) return;
                    
                    if (data.proxy === 'reconnecting') {
                        banner.className = 'network-banner reconnecting';
                        bannerText.textContent = `Переподключение к потоку... (Попытка ${data.attempt} из ${data.max_attempts})`;
                    } else if (data.proxy === 'failed') {
                        banner.className = 'network-banner';
                        bannerText.textContent = 'Не удалось восстановить поток. Перезапустите трек.';
                    } else if (data.proxy === 'connected') {
                        banner.classList.add('hidden');
                    }
                }
            }

            const _origOnPythonEvent = window.onPythonEvent;
            window.onPythonEvent = function(eventName, data) {
                if (_origOnPythonEvent) _origOnPythonEvent(eventName, data);
                _lyricsTrackSync(eventName, data);
                _handleNetworkEvent(eventName, data);
            };
        } catch (err) {
            console.error('Lyrics sync setup failed:', err);
        }

        // Show home page
        try {
            showPage('home');
        } catch (err) {
            console.error('Failed to show home page:', err);
        }

        // Remove skeleton splash once the UI is interactive
        try {
            const splash = document.getElementById('app-splash');
            if (splash) {
                splash.classList.add('hidden');
                setTimeout(() => splash.remove(), 400);
            }
        } catch (err) {
            console.error('Failed to remove splash:', err);
        }
        window.dispatchEvent(new CustomEvent('nedotify:app_ready'));

        // Settings already fetched early in init()

        // Horizontal wheel scroll for feed containers
        document.addEventListener('wheel', (e) => {
            const target = e.target.closest('.feed-scroll');
            if (target && e.deltaY !== 0) {
                e.preventDefault();
                target.scrollLeft += e.deltaY;
            }
        }, { passive: false });

        setupProfileAndGreeting();

        console.log('NeDotify initialized successfully');
    } catch (e) {
        console.error("Init Error:", e);
        const tc = document.getElementById('toast-container');
        if (tc) tc.innerHTML = `<div style="background:red;padding:10px;color:white;z-index:9999;">Critical Init Error: ${escapeHtml(e.message)}</div>`;
    }
}

// ─── Profile Page ───
async function loadProfile() {
    try {
        const { createTrackElement, renderIcons, formatListeningTimeShort } = await import('./utils.js?v=20260813');
        const { getCurrentTrack } = await import('./player.js?v=20260813');

        // Refresh nickname and avatar
        const nicknameInput = document.getElementById('profile-name-input');
        if (nicknameInput && window.settings?.personalization?.nickname) {
            nicknameInput.value = window.settings.personalization.nickname;
        }

        const avatarImg = document.getElementById('profile-avatar-img');
        const avatarIcon = document.getElementById('profile-avatar-icon');
        const currentAvatar = window.settings?.personalization?.avatar_path || window.settings?.app?.avatar_path;
        if (avatarImg && avatarIcon && currentAvatar) {
            const clean = currentAvatar.replace(/\\/g, '/');
            avatarImg.src = clean.startsWith('file://') ? encodeURI(clean) : `file:///${encodeURI(clean.replace(/^\//, ''))}`;
            avatarImg.style.display = 'block';
            avatarIcon.style.display = 'none';
        }

        if (!window.pywebview?.api?.get_profile_stats) return;

        const data = await window.pywebview.api.get_profile_stats();
        if (!data) return;

        const el = (id, text) => {
            const e = document.getElementById(id);
            if (e) e.textContent = text;
        };

        el('profile-stat-tracks', data.total_tracks || 0);
        el('profile-stat-time', formatListeningTimeShort ? formatListeningTimeShort(data.total_listening_time_ms || 0) : '0 ч');
        el('profile-stat-favorites', data.favorite_count || 0);

        // Pinned track
        const pinnedTrack = window.settings?.personalization?.pinned_track || window.settings?.app?.pinned_track;
        const pinnedSection = document.getElementById('profile-pinned-section');
        const pinnedTrackList = document.getElementById('profile-pinned-track');
        if (pinnedSection && pinnedTrackList) {
            if (pinnedTrack) {
                pinnedSection.style.display = 'block';
                pinnedTrackList.innerHTML = '';
                pinnedTrackList.appendChild(createTrackElement(pinnedTrack, 0, [pinnedTrack], getCurrentTrack()));
                if (typeof renderIcons === 'function') renderIcons();
            } else {
                pinnedSection.style.display = 'none';
            }
        }

        // Most played
        if (data.most_played && data.most_played.length > 0) {
            const container = document.getElementById('profile-top-tracks');
            if (container) {
                container.innerHTML = '';
                data.most_played.forEach((track, i) => {
                    container.appendChild(createTrackElement(track, i, data.most_played, getCurrentTrack()));
                });
                if (typeof renderIcons === 'function') renderIcons();
            }
        }

        // Recent
        if (data.recently_played && data.recently_played.length > 0) {
            const container = document.getElementById('profile-recent');
            if (container) {
                container.innerHTML = '';
                data.recently_played.slice(0, 10).forEach((track, i) => {
                    container.appendChild(createTrackElement(track, i, data.recently_played, getCurrentTrack()));
                });
                if (typeof renderIcons === 'function') renderIcons();
            }
        }
    } catch (e) {
        console.error('Error loading profile:', e);
    }
}

function setupProfileAndGreeting() {
    // 1. Setup Dynamic Greeting
    const updateGreeting = () => {
        const greetingEl = document.getElementById('home-greeting');
        if (!greetingEl) return;
        const hour = new Date().getHours();
        let greetingText = 'Доброе утро';
        if (hour >= 12 && hour < 18) {
            greetingText = 'Добрый день';
        } else if (hour >= 18 && hour < 23) {
            greetingText = 'Добрый вечер';
        } else if (hour >= 23 || hour < 5) {
            greetingText = 'Доброй ночи';
        }
        const nickname = (window.settings?.personalization?.nickname) || 'Пользователь NeDotify';
        greetingEl.textContent = `${greetingText}, ${nickname}`;
    };
    updateGreeting();
    // Update every 5 minutes in case time changes
    setInterval(updateGreeting, 5 * 60 * 1000);

    // Override the greeting when smart_home_ready replaces it
    const origHomeReady = window.onPythonEvent;
    window.onPythonEvent = function(eventName, data) {
        if (origHomeReady) origHomeReady(eventName, data);
        if (eventName === 'smart_home_ready' || eventName === 'authentic_home_ready') {
            updateGreeting(); // force it to our dynamic one instead of what backend says
        }
    };

    // 2. Setup Profile UI
    const nicknameInput = document.getElementById('profile-name-input');
    const saveNicknameBtn = document.getElementById('btn-save-nickname');
    const avatarBtn = document.getElementById('btn-change-avatar');
    const avatarImg = document.getElementById('profile-avatar-img');
    const avatarIcon = document.getElementById('profile-avatar-icon');
    const dateJoined = document.getElementById('profile-date-joined');
    const createLocalPlaylistBtn = document.getElementById('btn-create-local-playlist');

    // Populate initial values
    if (nicknameInput) {
        nicknameInput.value = window.settings?.personalization?.nickname || 'Пользователь NeDotify';
        
        nicknameInput.addEventListener('input', () => {
            saveNicknameBtn.style.display = 'inline-flex';
        });

        saveNicknameBtn.addEventListener('click', async () => {
            const newName = nicknameInput.value.trim() || 'Пользователь NeDotify';
            if (window.pywebview?.api) {
                await window.pywebview.api.save_setting('nickname', newName, 'personalization');
                if (!window.settings.personalization) window.settings.personalization = {};
                window.settings.personalization.nickname = newName;
                saveNicknameBtn.style.display = 'none';
                updateGreeting();
                if (typeof showToast === 'function') showToast('Имя сохранено', 'success');
            }
        });
    }

    function formatFileUrl(path) {
        if (!path) return '';
        const clean = path.replace(/\\/g, '/');
        if (clean.startsWith('file://')) return encodeURI(clean);
        return `file:///${encodeURI(clean.replace(/^\//, ''))}`;
    }

    if (avatarImg && avatarIcon) {
        const currentAvatar = window.settings?.personalization?.avatar_path || window.settings?.app?.avatar_path;
        if (currentAvatar) {
            avatarImg.src = formatFileUrl(currentAvatar);
            avatarImg.style.display = 'block';
            avatarIcon.style.display = 'none';
        }
    }

    if (avatarBtn) {
        avatarBtn.addEventListener('click', async () => {
            if (window.pywebview?.api) {
                const newAvatar = await window.pywebview.api.select_avatar();
                if (newAvatar) {
                    if (!window.settings.personalization) window.settings.personalization = {};
                    window.settings.personalization.avatar_path = newAvatar;
                    if (avatarImg && avatarIcon) {
                        avatarImg.src = formatFileUrl(newAvatar);
                        avatarImg.style.display = 'block';
                        avatarIcon.style.display = 'none';
                    }
                    if (typeof showToast === 'function') showToast('Аватарка обновлена', 'success');
                }
            }
        });
    }

    if (dateJoined) {
        const firstLaunch = window.settings?.general?.first_launch_done;
        // Since we don't have the exact date in DB right now, we can just display a static text or current date 
        // if we add registration_date to settings
        let regDate = window.settings?.personalization?.registration_date;
        if (!regDate) {
            regDate = new Date().toLocaleDateString();
            if (window.pywebview?.api) {
                window.pywebview.api.save_setting('registration_date', regDate, 'personalization');
                if (!window.settings.personalization) window.settings.personalization = {};
                window.settings.personalization.registration_date = regDate;
            }
        }
        dateJoined.textContent = `В NeDotify с ${regDate}`;
    }

    // 3. Local Playlist Creation
    if (createLocalPlaylistBtn) {
        createLocalPlaylistBtn.addEventListener('click', async () => {
            if (window.pywebview?.api) {
                createLocalPlaylistBtn.disabled = true;
                const origText = createLocalPlaylistBtn.innerHTML;
                createLocalPlaylistBtn.innerHTML = 'Создание...';
                
                try {
                    await window.pywebview.api.create_local_playlist("Локальные");
                    loadPlaylists();
                } catch(err) {
                    console.error(err);
                } finally {
                    createLocalPlaylistBtn.disabled = false;
                    createLocalPlaylistBtn.innerHTML = origText;
                    if (typeof renderIcons === 'function') renderIcons();
                }
            }
        });
    }
}

function formatListeningTimeShort(ms) {
    if (!ms || ms <= 0) return '0 ч';
    const hours = Math.floor(ms / (1000 * 3600));
    if (hours > 0) return `${hours} ч`;
    const minutes = Math.floor(ms / (1000 * 60));
    return `${minutes} мин`;
}



