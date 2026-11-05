import { initWindowResize } from './window-resize.js';
import { initFeatureControls, handleFeatureEvent } from './feature-controls.js';
import { initProfileComparison } from './profile-comparison.js';
import { initHomeShell } from './home-shell.js';
import { initTrackWave, startTrackWave } from './track-wave.js';
// NeDotify - Main Entry Point
import { initPlayer, applySettings, playTrack, getAtmosphereAudioSource } from './player.js';
import { initPages, showPage } from './pages.js';
import { initSearch, searchArtistProfile } from './search.js';
import { loadHome } from './home.js';
import { initLibrary, loadLibrary, loadPlaylists, openPlaylistMenu, createPlaylist } from './library.js';
import { initSettings, applySettingsFromBackend, loadSettings } from './settings.js';
import { initAtmosphere, destroyAtmosphere, setAtmosphereAudioProvider } from './atmosphere-engine.js';
import { initVisualizer, destroyVisualizer } from './visualizer.js';
import { initEvents, addPythonEventHandler, flushPythonEvents, deferPythonEvents } from './events.js';
import { renderIcons, handleImageError, showTrackContextMenu, escapeHtml, checkLocalStorageQuota, showToast, initBatchActionBar } from './utils.js';
// Late-screen fetches overlap; initialization remains ordered before event replay.
import { initOnboarding } from './onboarding.js';
import { initSetupReadiness } from './setup-panel.js';
import { initContextMenu } from './contextmenu.js';
import { initHotkeys } from './hotkeys.js';
import { initEfficiency, initBlurObserver } from './efficiency.js';

function isBridgeReady() {
    return Boolean(window.pywebview?.api && typeof window.pywebview.api.get_settings === 'function');
}
window.addEventListener('pagehide', destroyVisualizer, { once: true });
setAtmosphereAudioProvider(getAtmosphereAudioSource);
window.addEventListener('pagehide', destroyAtmosphere, { once: true });

// Bridge gate: resolves as soon as window.pywebview.api methods exist. Cold WebView2
// starts can take ~16s to inject the bridge; callers await this instead of
// exiting early, so the UI comes alive by itself on the FIRST load.
let bridgeWaiter = null;
window.awaitBridge = function awaitBridge() {
    if (isBridgeReady()) {
        if (!window.PROXY_PORT && window.pywebview.api.get_proxy_info) {
            window.pywebview.api.get_proxy_info().then(info => {
                if (info && info.port) {
                    window.PROXY_PORT = info.port;
                    window.PROXY_TOKEN = info.token || '';
                }
            }).catch(() => {});
        }
        return Promise.resolve();
    }
    if (bridgeWaiter) return bridgeWaiter;
    bridgeWaiter = new Promise((resolve, reject) => {
        let resolved = false;
        let pollTimer;
        const timeout = setTimeout(() => {
            resolved = true;
            clearTimeout(pollTimer);
            window.removeEventListener('pywebviewready', complete);
            bridgeWaiter = null;
            reject(new Error('Bridge initialization timed out'));
        }, 45000);
        const complete = () => {
            if (!isBridgeReady()) return;
            if (resolved) return;
            resolved = true;
            clearTimeout(timeout);
            clearTimeout(pollTimer);
            window.removeEventListener('pywebviewready', complete);
            if (!window.PROXY_PORT && window.pywebview.api?.get_proxy_info) {
                window.pywebview.api.get_proxy_info().then(info => {
                    if (info && info.port) {
                        window.PROXY_PORT = info.port;
                        window.PROXY_TOKEN = info.token || '';
                    }
                }).catch(() => {});
            }
            resolve();
        };

        window.addEventListener('pywebviewready', complete, { once: true });
        const check = () => {
            if (isBridgeReady()) {
                complete();
                return;
            }
            if (!resolved) {
                pollTimer = setTimeout(check, 100);
            }
        };
        check();
    });
    return bridgeWaiter;
};




// Global NeDotify namespace for cross-module communication
// loadProfile is an async-loading wrapper: profile.js is off the startup module
// graph, and loadProfile is itself async, so every caller that awaits (or
// ignores) its promise behaves exactly as before - only the first call pays
// the module fetch.
const loadProfile = () => import('./profile.js').then(m => m.loadProfile());
window.loadProfile = loadProfile;
window.searchArtistProfile = searchArtistProfile;
window.NeDotify = {
    ...window.NeDotify,
    openPlaylistMenu: openPlaylistMenu,
    createPlaylist: createPlaylist,
    loadHome: loadHome,
    loadLibrary: loadLibrary,
    loadProfile: loadProfile,
    loadSettings: loadSettings,
    handleImageError: handleImageError,
    showTrackContextMenu: showTrackContextMenu,
    showPage: showPage,
    searchArtistProfile: searchArtistProfile,
    playTrack: playTrack,
    playNext: async (track) => {
        if (window.pywebview?.api?.play_next) {
            try { await window.pywebview.api.play_next(track); }
            catch { showToast('Не удалось добавить трек следующим', 'error'); }
        }
    },
    addToQueue: async (track) => {
        if (window.pywebview?.api?.add_to_queue) {
            try { await window.pywebview.api.add_to_queue(track); }
            catch { showToast('Не удалось добавить трек в очередь', 'error'); }
        }
    },
    downloadTrack: async (track) => {
        if (!track) return;
        if (window.pywebview?.api?.download_track) {
            try { await window.pywebview.api.download_track(track); }
            catch { showToast('Не удалось начать скачивание', 'error'); }
        }
    },
    startTrackWave: startTrackWave,
    toggleMiniPlayerMode: toggleMiniPlayerMode
};

let miniPlayerRequestCounter = 0;
function applyMiniPlayerLayout(enabled) {
    const changed = document.body.classList.contains('mini-player-active') !== Boolean(enabled);
    document.body.classList.toggle('mini-player-active', Boolean(enabled));
    if (changed) document.body.animate?.([
        { opacity: .35, transform: enabled ? 'scale(.94)' : 'scale(1.035)' },
        { opacity: 1, transform: 'scale(1)' }
    ], { duration: 320, easing: 'cubic-bezier(.22,1,.36,1)' });
}


let latestMiniPlayerRequestId = null;
const pendingMiniPlayerToggles = new Map();

window.addEventListener('nedotify:mini_player_toggled', event => {
    const data = event.detail || {};
    const requestId = data.request_id;
    if (requestId && pendingMiniPlayerToggles.has(requestId)) {
        const pending = pendingMiniPlayerToggles.get(requestId);
        pendingMiniPlayerToggles.delete(requestId);
        clearTimeout(pending.timer);
        if (requestId !== latestMiniPlayerRequestId) {
            pending.resolve(document.body.classList.contains('mini-player-active'));
            return;
        }
        if (data.success === false) {
            applyMiniPlayerLayout( pending.previous);
            pending.resolve(pending.previous);
        } else {
            applyMiniPlayerLayout( Boolean(data.is_mini));
            pending.resolve(Boolean(data.is_mini));
        }
        return;
    }
    // Native window visibility changes can originate outside the JS toggle path.
    if (!requestId && data.success !== false && typeof data.is_mini === 'boolean') {
        applyMiniPlayerLayout( data.is_mini);
    }
});

export async function toggleMiniPlayerMode(targetState) {
    const isCurrentlyMini = document.body.classList.contains('mini-player-active');
    if (targetState === undefined) targetState = !isCurrentlyMini;
    if (window.pywebview?.api?.toggle_mini_player) {
        const requestId = `mini-toggle-${Date.now()}-${++miniPlayerRequestCounter}`;
        // Superseded native requests may never emit an event. Release their
        // waiters now and prevent a late timeout from rolling back newer state.
        for (const [oldId, oldPending] of pendingMiniPlayerToggles) {
            pendingMiniPlayerToggles.delete(oldId);
            clearTimeout(oldPending.timer);
            oldPending.resolve(document.body.classList.contains('mini-player-active'));
        }
        latestMiniPlayerRequestId = requestId;
        let resolveEvent;
        const eventResult = new Promise(resolve => { resolveEvent = resolve; });
        const pending = { previous: isCurrentlyMini, resolve: resolveEvent, timer: null };
        pendingMiniPlayerToggles.set(requestId, pending);
        try {
            const res = await window.pywebview.api.toggle_mini_player(targetState, requestId);
            if (res?.pending === true) {
                // A very fast native operation may emit its completion before
                // the bridge promise resolves. In that case the event handler
                // has already removed this request and resolved eventResult.
                if (!pendingMiniPlayerToggles.has(requestId)) return await eventResult;
                pending.timer = setTimeout(() => {
                    if (!pendingMiniPlayerToggles.delete(requestId)) return;
                    const current = document.body.classList.contains('mini-player-active');
                    if (latestMiniPlayerRequestId === requestId) {
                        applyMiniPlayerLayout( isCurrentlyMini);
                        window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Не удалось переключить мини-плеер', type: 'error' } }));
                    }
                    resolveEvent(latestMiniPlayerRequestId === requestId ? isCurrentlyMini : current);
                }, 15000);
                return await eventResult;
            }
            pendingMiniPlayerToggles.delete(requestId);
            if (requestId !== latestMiniPlayerRequestId) return document.body.classList.contains('mini-player-active');
            const backendOk = res !== false && res?.success !== false;
            const confirmedState = typeof res?.is_mini === 'boolean' ? res.is_mini : Boolean(targetState);
            if (!backendOk) throw new Error('Mini player transition failed');
            applyMiniPlayerLayout( confirmedState);
            return confirmedState;
        } catch (e) {
            pendingMiniPlayerToggles.delete(requestId);
            clearTimeout(pending.timer);
            if (requestId === latestMiniPlayerRequestId) {
                applyMiniPlayerLayout( isCurrentlyMini);
                window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Не удалось переключить мини-плеер', type: 'error' } }));
            }
            return isCurrentlyMini;
        }
    }
    // No bridge in the static preview: keep the local layout toggle available.
    applyMiniPlayerLayout( targetState);
    return targetState;
}
window.toggleMiniPlayerMode = toggleMiniPlayerMode;

// Instant restoration of Theme, Blur & Transparency on boot
(function restorePreferences() {
    try {
        const theme = JSON.parse(localStorage.getItem('nedotify_ui_theme') || '"dark"');
        document.documentElement.setAttribute('data-theme', theme);

        const glassBlur = JSON.parse(localStorage.getItem('nedotify_theme_glass_blur') ?? '20');
        document.documentElement.style.setProperty('--glass-blur', `${glassBlur}px`);

        const customPrimary = localStorage.getItem('nedotify_theme_color_primary') || localStorage.getItem('nedotify_theme_custom_primary');
        if (customPrimary && JSON.parse(localStorage.getItem('nedotify_theme_custom_palette_enabled') || 'false') === true) {
            const parsed = JSON.parse(customPrimary);
            if (parsed) document.documentElement.style.setProperty('--primary', parsed);
        }

        const transEnabled = JSON.parse(localStorage.getItem('nedotify_theme_transparency_enabled') ?? 'false');
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
                    const lowBatteryThreshold = 0.2;
                    const updateBatteryStatus = () => {
                        // Running on battery alone is not battery saver mode. Keep
                        // glass and other normal effects available until charge is low.
                        const isBatteryMode = battery.charging === false &&
                            Number.isFinite(battery.level) && battery.level <= lowBatteryThreshold;
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
                    battery.addEventListener('levelchange', updateBatteryStatus);
                }).catch(() => {});
            }
        }
        setupBatterySaver();

        // Instant background image restoration on boot
        const customBgRaw = localStorage.getItem('nedotify_theme_custom_bg_image');
        if (customBgRaw) {
            let bgUrl = customBgRaw;
            try {
                if (typeof customBgRaw === 'string' && (customBgRaw.startsWith('"') || customBgRaw.startsWith('{'))) {
                    bgUrl = JSON.parse(customBgRaw);
                }
            } catch(e) {}
            bgUrl = window.NeDotifyAssets?.resolveBackground(bgUrl) ?? bgUrl;
            const safeBg = typeof bgUrl === 'string' && /^(https?:|file:|data:image\/|assets\/|[a-zA-Z]:[\\/]|\/)/i.test(bgUrl.trim());
            if (safeBg) {
                const blurRaw = Number(JSON.parse(localStorage.getItem('nedotify_theme_bg_blur') || '0'));
                const dimRaw = Number(JSON.parse(localStorage.getItem('nedotify_theme_bg_dim') || '30'));
                const blur = Number.isFinite(blurRaw) ? Math.min(Math.max(blurRaw, 0), 100) : 0;
                const dim = Number.isFinite(dimRaw) ? Math.min(Math.max(dimRaw, 0), 100) : 30;
                document.documentElement.classList.add('has-custom-bg');
                document.body.classList.add('has-custom-bg');
                document.documentElement.classList.remove('resource-bg-disabled');
                let bgLayer = document.getElementById('custom-bg-layer');
                let dimLayer = document.getElementById('custom-bg-dim-layer');
                if (!bgLayer) {
                    bgLayer = document.createElement('div');
                    bgLayer.id = 'custom-bg-layer';
                    document.body.insertBefore(bgLayer, document.body.firstChild);
                }
                if (!dimLayer) {
                    dimLayer = document.createElement('div');
                    dimLayer.id = 'custom-bg-dim-layer';
                    document.body.insertBefore(dimLayer, document.body.firstChild);
                }
                bgLayer.style.display = 'block';
                bgLayer.style.backgroundImage = `url(${JSON.stringify(bgUrl)})`;
                bgLayer.style.filter = `blur(${blur}px)`;
                bgLayer.style.transform = `scale(${blur > 0 ? 1.06 : 1})`;
                dimLayer.style.display = 'block';
                dimLayer.style.backgroundColor = `rgba(0, 0, 0, ${dim / 100})`;
            }
        }
    } catch(e) {}
})();

// Wait for the pywebview bridge (can take ~16s on a cold WebView2 start).
// Await the bridge via both immediate check, polling, and pywebviewready event.
function startAppInit() {
    if (window.awaitBridge) {
        window.awaitBridge().then(() => init()).catch(() => init());
    } else if (isBridgeReady()) {
        init();
    }
}

if (isBridgeReady()) {
    startAppInit();
} else {
    window.addEventListener('pywebviewready', () => startAppInit(), { once: true });
}

// Fallback safety timeout: ensure init() runs even if bridge event was dropped
setTimeout(() => {
    if (!window._nedotifyInitialized) {
        console.warn('Fallback init trigger after 4s timeout');
        init();
    }
}, 4000);

// Bridge-dead last resort: count page loads that happened without a bridge
// (the backend watchdog silently reloads twice), and only then show the error
// overlay — after 45s of bridge absence on the 3rd load (initial + 2 reloads).
if (!isBridgeReady()) {
    try {
        const strikes = parseInt(sessionStorage.getItem('nedotify_bridge_strikes') || '0', 10) + 1;
        sessionStorage.setItem('nedotify_bridge_strikes', String(strikes));
    } catch {}
}
setTimeout(() => {
    if (isBridgeReady()) return;
    let strikes = 3;
    try { strikes = parseInt(sessionStorage.getItem('nedotify_bridge_strikes') || '0', 10); } catch {}
    if (strikes >= 3) {
        try { sessionStorage.removeItem('nedotify_bridge_strikes'); } catch {}
        showBridgeError();
    }
}, 45000);

async function init() {
    if (window._nedotifyInitialized) return;
    window._nedotifyInitialized = true;
    try {
        // 1. Immediately apply cached settings from localStorage (0ms latency, unblocks first render)
        try {
            const cachedRaw = localStorage.getItem('nedotify_cached_settings');
            if (cachedRaw) {
                const cachedSettings = getCacheableSettings(JSON.parse(cachedRaw));
                try { localStorage.setItem('nedotify_cached_settings', JSON.stringify(cachedSettings)); } catch {}
                window.settings = cachedSettings;
                applySettings(cachedSettings);
                applySettingsFromBackend(cachedSettings);
            }
        } catch (e) {
            console.debug('Failed to apply cached settings:', e);
        }

        // 2. Fetch fresh settings asynchronously in background without blocking UI initialization
        if (window.pywebview?.api?.get_settings) {
            window.nedotifySettingsReady = window.pywebview.api.get_settings().then((freshSettings) => {
                if (freshSettings) {
                    const cacheableSettings = getCacheableSettings(freshSettings);
                    try { localStorage.setItem('nedotify_cached_settings', JSON.stringify(cacheableSettings)); } catch {}
                    window.settings = freshSettings;
                    applySettings(freshSettings);
                    applySettingsFromBackend(freshSettings);
                }
            }).catch((err) => {
                console.error('Async get_settings error:', err);
            });
        }

        Promise.resolve(window.nedotifySettingsReady).then(() => initSetupReadiness()).catch(() => {});
        // Init Onboarding next (blocks UI if first launch)
        if (typeof initOnboarding === 'function') {
            try { initOnboarding(); } catch(e) { console.error('initOnboarding error:', e); }
        }

        try { initContextMenu(); } catch(e) { console.error('initContextMenu error:', e); }
        try { initHotkeys(); } catch(e) { console.error('initHotkeys error:', e); }
        try { initEfficiency(); } catch(e) { console.error('initEfficiency error:', e); }
        try { initBlurObserver(); } catch(e) { console.error('initBlurObserver error:', e); }

        // M-9: debug.js was orphaned — load it on demand via ?debug=1 (never in normal UI)
        try {
            if (new URLSearchParams(location.search).has('debug')) {
                const dbgScript = document.createElement('script');
                dbgScript.src = 'js/debug.js';
                document.head.appendChild(dbgScript);
            }
        } catch (e) {}

        // Window controls (frameless) - Initialize first to ensure app can always be closed
        initWindowResize();
        document.getElementById('btn-mini-player')?.addEventListener('click', () => {
            toggleMiniPlayerMode();
        });
        document.getElementById('btn-minimize')?.addEventListener('click', () => {
            if (window.pywebview?.api) window.pywebview.api.minimize_window();
        });
        document.getElementById('btn-maximize')?.addEventListener('click', () => {
            if (window.pywebview?.api?.maximize) window.pywebview.api.maximize();
        });
        // Snap Layouts (Windows 11): tell the backend where the maximise button
        // is, so WM_NCHITTEST can answer HTMAXBUTTON over it and Windows shows
        // the layout flyout on hover. Re-sent on resize because the rect moves.
        let snapBridgeRetries = 0;
        let snapRetryTimer = 0;
        const reportSnapButton = async () => {
            const btn = document.getElementById('btn-maximize');
            if (!btn || !window.pywebview?.api?.set_snap_button_rect) return;
            const r = btn.getBoundingClientRect();
            try {
                const result = await window.pywebview.api.set_snap_button_rect(r.left, r.top, r.width, r.height);
                if (result?.success) {
                    clearTimeout(snapRetryTimer);
                    return;
                }
            } catch (e) {}
            // Native HWND setup can finish after the JS bridge is ready.
            // Bound retries so non-Windows/dev previews do not poll forever.
            if (snapBridgeRetries++ < 12) {
                clearTimeout(snapRetryTimer);
                snapRetryTimer = setTimeout(reportSnapButton, 500);
            }
        };
        let snapReportFrame = 0;
        const scheduleSnapButton = () => {
            cancelAnimationFrame(snapReportFrame);
            snapReportFrame = requestAnimationFrame(reportSnapButton);
        };
        window.addEventListener('resize', scheduleSnapButton);
        window.addEventListener('pywebviewready', scheduleSnapButton);
        if (typeof ResizeObserver === 'function') {
            const snapObserver = new ResizeObserver(scheduleSnapButton);
            const button = document.getElementById('btn-maximize');
            if (button) snapObserver.observe(button);
        }
        reportSnapButton();
        setTimeout(reportSnapButton, 600);
        setTimeout(reportSnapButton, 2000);
        document.getElementById('btn-close')?.addEventListener('click', async () => {
            if (window.pywebview?.api) {
                window.pywebview.api.close_window();
                return;
            }
            try {
                const res = await fetch('/__aura_close', { method: 'POST' });
                if (!res.ok) window.close();
            } catch (e) {
                window.close();
            }
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
        // Start after the icon idle callback: fetching before it can starve that
        // callback and delay every interactive handler. Fulfilled wrappers
        // attach rejection handlers immediately; safeInit still isolates failures.
        const lateModules = Object.fromEntries(['lyrics', 'equalizer', 'queue'].map(name =>
            [name, import(`./${name}.js`).then(module => ({ module }), error => ({ error }))]));
        const initLateModule = async (name, initName) => {
            const result = await lateModules[name];
            if (result.error) throw result.error;
            return result.module[initName]();
        };

        // Initialize all modules safely after the first idle icon pass.
        deferPythonEvents();
        await safeInit('Events', () => initEvents());
        await safeInit('Track wave', () => initTrackWave(addPythonEventHandler));
        await safeInit('Pages', () => initPages());
        // M-2: warn early if localStorage is near the ~5MB quota
        try { checkLocalStorageQuota(); } catch (e) {}
        await safeInit('Player', () => initPlayer());
        await safeInit('Search', () => initSearch());
        await safeInit('Library', () => initLibrary());
        await safeInit('Home shell', () => initHomeShell());
        await safeInit('Settings', () => initSettings());
        await safeInit('Feature controls', () => initFeatureControls());
        addPythonEventHandler(handleFeatureEvent);
        initProfileComparison();
        await safeInit('Atmosphere', () => initAtmosphere());
        await safeInit('Visualizer', () => initVisualizer());
        await safeInit('Lyrics', () => initLateModule('lyrics', 'initLyrics'));
        await safeInit('Equalizer', () => initLateModule('equalizer', 'initEqualizer'));
        await safeInit('Queue', () => initLateModule('queue', 'initQueue'));
        flushPythonEvents();
        await safeInit('Restored session', async () => {
            await window.awaitBridge();
            if (window.pywebview.api.ui_ready) await window.pywebview.api.ui_ready(
                window.__nedotifyRendererId ||= globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`);
        });
        await safeInit('BatchActionBar', () => initBatchActionBar());
        
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
            // BUG-U3-006: мёртвая ветка network_status удалена — событие не эмитится
            // бэкендом (grep по core/, services/ = 0). Живой путь баннера —
            // proxy_status (core/proxy.py); сетевые проблемы
            // видны через proxy-баннер и панель operation-error.
            function _handleNetworkEvent(eventName, data) {
                if (eventName === 'proxy_status') {
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

            // P1-8: subscribe instead of decorating window.onPythonEvent. The registry in
            // events.js lives for the whole page lifetime, so these two run whether
            // or not initEvents() has already been reached.
            addPythonEventHandler((eventName, data) => {
                _lyricsTrackSync(eventName, data);
                _handleNetworkEvent(eventName, data);
            });
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
                setTimeout(() => { try { splash.remove(); } catch(e) {} }, 400);
            }
        } catch (err) {
            console.error('Failed to remove splash:', err);
        }
        window.dispatchEvent(new CustomEvent('nedotify:app_ready'));

        // Settings already fetched early in init()

        // Horizontal wheel scroll for feed containers (only when element has horizontal scroll and not vertical)
        document.addEventListener('wheel', (e) => {
            const target = e.target.closest('.feed-scroll, .artist-albums-carousel, .feed-row, .carousel-track');
            if (target && e.deltaY !== 0) {
                const hasHorizontalScroll = target.scrollWidth > target.clientWidth;
                const hasVerticalScroll = target.scrollHeight > target.clientHeight;
                if (hasHorizontalScroll && !hasVerticalScroll) {
                    e.preventDefault();
                    target.scrollLeft += e.deltaY;
                }
            }
        }, { passive: false });

        setupProfileAndGreeting();

        console.log('NeDotify initialized successfully');
    } catch (e) {
        console.error("Init Error:", e);
        try {
            const splash = document.getElementById('app-splash');
            if (splash) {
                splash.classList.add('hidden');
                setTimeout(() => { try { splash.remove(); } catch(e2) {} }, 400);
            }
        } catch(se) {}
        const tc = document.getElementById('toast-container');
        if (tc) tc.innerHTML = `<div style="background:red;padding:10px;color:white;z-index:9999;">Critical Init Error: ${escapeHtml(e.message)}</div>`;
    }
}

function getCacheableSettings(settings) {
    const cacheable = settings && typeof settings === 'object' ? {...settings} : {};
    delete cacheable.auth;
    if (cacheable.services && typeof cacheable.services === 'object') {
        cacheable.services = {...cacheable.services};
        for (const key of ['lastfm_api_key', 'lastfm_api_secret']) delete cacheable.services[key];
    }
    return cacheable;
}

// ─── Profile Page ───
// Module URLs carry no query string: ES module identity is keyed by full URL, so a
// version mismatch between two importers would instantiate the module twice and split
// its state. Freshness is guaranteed by the no-store Cache-Control hook in main.py.

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

    // BUG-U3-008: легаси-имя smart_home_ready удалено — событие не эмитится,
    // живой путь — authentic_home_ready. Перезапускаем динамическое приветствие
    // после прихода ленты, чтобы бэкенд-заголовок не перебил локальный.
    addPythonEventHandler((eventName) => {
        if (eventName === 'authentic_home_ready') {
            updateGreeting(); // force it to our dynamic one instead of what backend says
        }
    });

    window.addEventListener('nedotify:profile_updated',updateGreeting);
    // profile.js loads on demand (see the loadProfile wrapper above); its
    // handlers only matter once the profile view is opened by the user.
    import('./profile.js').then(m => m.initProfile()).catch(err => console.error('initProfile failed:', err));
}

function showBridgeError() {
    const existing = document.getElementById('bridge-error-overlay');
    if (existing) return;
    const overlay = document.createElement('div');
    overlay.id = 'bridge-error-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:99999;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;background:rgba(10,10,15,0.96);color:#e5e7eb;font-family:Inter,sans-serif;text-align:center;padding:24px;';
    overlay.innerHTML = `
        <div style="font-size:15px;line-height:1.6;max-width:420px;">
            Связь с приложением не установлена (мост pywebview не инициализировался).
            <br>Нажмите «Перезагрузить», чтобы попробовать снова.
        </div>
        <div style="display:flex;gap:12px;">
            <button id="bridge-error-reload" style="background:#a855f7;color:#fff;border:none;border-radius:8px;padding:10px 22px;cursor:pointer;font-size:14px;">Перезагрузить</button>
            <button id="bridge-error-close" style="background:#27272a;color:#e5e7eb;border:none;border-radius:8px;padding:10px 22px;cursor:pointer;font-size:14px;">Закрыть</button>
        </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('#bridge-error-reload').addEventListener('click', () => {
        try { location.reload(); } catch (e) {}
    });
    overlay.querySelector('#bridge-error-close').addEventListener('click', async () => {
        try {
            const res = await fetch('/__aura_close', { method: 'POST' });
            if (!res.ok) window.close();
        } catch (e) {
            window.close();
        }
    });
}



