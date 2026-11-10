// Settings panel controls and catalogues, loaded after the interactive shell.
import { renderIcons, escapeHtml, compressBackgroundImage, showToast, openModalFocusTrap, closeModalFocusTrap } from './utils.js';
import { initAtmosphereSettings } from './atmosphere-settings.js';
import { initDiscordSettings } from './discord-settings.js';
import { setVisualizerFps, setVisualizerEnabled } from './visualizer.js';
import { DEFAULT_KEYBINDS, activeKeybinds, setListeningKeybind, getListeningKeybindId } from './hotkeys.js';
import { evaluateEfficiencyState } from './efficiency.js';
import { setUiFps, applyAudioSettings } from './player.js';
import { initSettingsView, initAdditionalSettings, themePreviewPath, syncThemeSelection, syncCustomColorFields } from './settings-view.js';
import { applyBorderRadius } from './settings.js';
import { enableBlurPerformance } from './settings.js';
import { reopenOnboarding } from './onboarding.js';
import { openSetupPanel } from './setup-panel.js';
import { PRESET_THEMES, activateCustomPalette, applyAuraOrbs, applyCompactQueueBtn, applyCustomBg, applyFontSize, applyGlassBlur, applyIconPack, applyMpCoverShape, applyMpPos, applyMpProgress, applyMpShape, applyNextTrackPreview, applyPlayerStyle, applyProgressColor, applyProgressTransparency, applyQueuePosition, applyQueueViewMode, applyResourceToggle, applyShowQueue, applySliderType, applyThemeMode, applyTitleAlignment, applyTransparency, enableMacosGlass, getLocalSetting, getSavedCustomThemes, initKeybinds, normalizeProgressColor, normalizeProgressStyle, onStorageInfo, renderFontCards, renderSavedCustomThemes, renderThemeGrid, resetCustomPalette, restoreCustomPalette, saveSetting, savedSetting, setElText, setupEfficiencyPanel, setupOptimizationPanel, setupSlider, setupToggle, syncAuraOrbsState, syncPlayerSettingsUI, syncSwitch } from './settings.js';

export function initPrivacySettings() {
    for (const [key, values] of [['mode', ['auto', 'word', 'line']], ['animations', ['standard', 'reduced', 'off']]]) {
        const input = document.getElementById(`lyrics-${key}`);
        input?.addEventListener('change', async () => {
            if (!values.includes(input.value)) return;
            if (await saveSetting(key, input.value, 'lyrics')) {
                window.dispatchEvent(new CustomEvent('nedotify:lyrics_settings_changed', {detail: window.settings.lyrics}));
            }
        });
    }
    const lyricsToggle = document.getElementById('toggle-lyrics-enabled');
    if (lyricsToggle) lyricsToggle.addEventListener('click', async () => {
        const enabled = !lyricsToggle.classList.contains('on');
        if (await saveSetting('enabled', enabled, 'lyrics')) syncSwitch(lyricsToggle, enabled);
    });
    const lastfmToggle = document.getElementById('toggle-lastfm-enabled');
    if (lastfmToggle) lastfmToggle.addEventListener('click', async () => {
        const enabled = !lastfmToggle.classList.contains('on');
        if (await saveSetting('lastfm_enabled', enabled, 'services')) syncSwitch(lastfmToggle, enabled);
    });

    const inputLastfmUsername = document.getElementById('input-lastfm-username');
    if (inputLastfmUsername) {
        inputLastfmUsername.addEventListener('change', async (e) => {
            const username = String(e.target.value || '').trim();
            const saved = await saveSetting('lastfm_username', username, 'auth');
            if (saved) e.target.value = username;
        });
    }
    const inputLastfmApiKey = document.getElementById('input-lastfm-api-key');
    if (inputLastfmApiKey) {
        inputLastfmApiKey.addEventListener('change', async (e) => {
            const apiKey = String(e.target.value || '').trim();
            if (!apiKey) return;
            const saved = await saveSetting('lastfm_api_key', apiKey, 'services');
            if (saved) {
                e.target.value = '';
                e.target.placeholder = 'Ключ сохранён (введите новый, чтобы заменить)';
            }
        });
    }
}

export function initSettings() {
    document.getElementById('setup-open-panel')?.addEventListener('click', () => openSetupPanel());
    document.getElementById('settings-reopen-onboarding')?.addEventListener('click', reopenOnboarding);
    initPrivacySettings();
    initAtmosphereSettings({save:saveSetting});
    initDiscordSettings({save:saveSetting});
    setupEfficiencyPanel();
    initAdditionalSettings({save:saveSetting, read:savedSetting, applyRadius:applyBorderRadius});
    initSettingsSearchFilter();

    // Settings panel navigation
    document.querySelectorAll('.settings-nav-btn[data-panel]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const panelName = btn.dataset.panel;
            if (!panelName) return;

            const change = () => {
            document.querySelectorAll('.settings-nav-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            document.querySelectorAll('.settings-panel').forEach(p => {
                p.classList.remove('active');
                p.style.display = 'none';
            });

            const target = document.getElementById('settings-' + panelName);
            if (target) {
                target.classList.add('active');
                target.style.display = 'block';
            }
            document.querySelector('#view-settings .settings-panels').scrollTop = 0;

            };
            if (window.NeDotifyMotion) window.NeDotifyMotion.swap(document.querySelector('#view-settings .settings-panels'), change); else change();

            if (panelName === 'icons') setupIconsPanel();
            if (panelName === 'workshop') setupWorkshopPanel();
            if (panelName === 'optimization') {
                setupEfficiencyPanel();
                setupOptimizationPanel();
            }
            if (panelName === 'zapret') setupZapretPanel();

            try {
                // Scoped to the settings view: this fires on every panel switch,
                // and a full-document pass would re-walk every icon in the app
                // (sidebar, player bar) just to render one panel's content.
                const settingsRoot = document.getElementById('view-settings');
                if (window.lucide) {
                    window.lucide.createIcons(settingsRoot
                        ? { nameAttr: 'data-lucide', attrs: {}, root: settingsRoot }
                        : undefined);
                }
            } catch(err) {}
        });
    });

    // Render theme grid & setup appearance handlers
    renderThemeGrid();
    setupAppearancePanel();
    setupPlayerSettingsPanel();
    setupBackgroundPanel();
    initSettingsView({resetPalette:resetCustomPalette,backgrounds:WORKSHOP_ITEMS.filter(item=>['ws_dark_forest','ws_aurora','ws_2','ws_nebula'].includes(item.id)),themeBackgrounds:PRESET_THEMES.filter(item=>themePreviewPath(item.id)).map(item=>({title:item.name,url:window.NeDotifyAssets?.themeBackgroundPath(item.id),preview:themePreviewPath(item.id)})),chooseBackground:item=>{
        saveSetting('custom_bg_image',item.url,'theme');saveSetting('resource_bg',true,'optimization');applyResourceToggle('bg',true);
        applyCustomBg(item.url,Number(document.getElementById('slider-bg-blur').value),Number(document.getElementById('slider-bg-dim').value));
    }});
    document.getElementById('appearance-current-background').onclick=()=>document.getElementById('appearance-background-options').click();
    restoreCustomPalette(window.settings?.theme);
    renderSavedCustomThemes();
    window.NeDotifyAppearance?.refresh();
    setupWorkshopPanel();
    setupIconsPanel();

    // Optimization panel
    setupOptimizationPanel();

    // Zapret panel
    setupZapretPanel();

    // Toggles
    setupToggle('toggle-crossfade', 'crossfade_enabled', 'audio');
    setupToggle('toggle-gapless', 'gapless_playback', 'audio');
    setupToggle('toggle-normalization', 'volume_normalization', 'audio');
    setupToggle('toggle-autoplay', 'autoplay', 'audio');
    // NOTE: #toggle-visualizer is owned by visualizer.js (single source of truth).
    // settings.js must NOT bind a second click handler here — it only persists
    // via saveSetting() when told to, and syncs state through setVisualizerEnabled().

    setupSlider('slider-crossfade-sec', 'crossfade_duration_sec', 'audio', (v) => {
        setElText('label-crossfade-sec', `${v} сек`);
    });

    // Shared visual controls
    setupSlider('slider-glass-blur', 'glass_blur', 'theme', (v) => {
        applyGlassBlur(v);
        window.NeDotifyAppearance?.refresh();
    }, () => document.documentElement.dataset.uiStyle === 'macos' ? {key:'macos_blur',category:'interface'} : {key:'glass_blur',category:'theme'}, async value => {
        if (value > 0) enableBlurPerformance();
        const quality = savedSetting('optimization', 'blur_quality', 'hq');
        await Promise.all([
            saveSetting('resource_blur', value > 0, 'optimization'),
            saveSetting('blur_quality', value > 0 ? quality === 'off' ? 'hq' : quality : 'off', 'optimization'),
        ]);
    });

    // BUG-U3-005: мёртвый биндинг select-font-family удалён — элемента с таким
    // id нет в разметке (статичной и динамической). Выбор шрифта живёт в
    // карточках font-cards-grid / nedotify-picker-fonts (другой поток
    // сохранения); см. settings.js applySettingsFromBackend.

    // Window Transparency Bindings
    const toggleTrans = document.getElementById('toggle-transparency');
    const sliderTrans = document.getElementById('slider-transparency-level');
    if (toggleTrans && sliderTrans) {
        setupToggle('toggle-transparency', 'transparency_enabled', 'theme', isOn => {
            sliderTrans.disabled = !isOn;
            applyTransparency(sliderTrans.value, isOn);
            // Blend UI surfaces over the wallpaper inside an input-safe HWND.
            showToast(isOn
                ? 'Полупрозрачность интерфейса включена'
                : 'Полупрозрачность выключена', 'info');
        });
    }
    setupSlider('slider-transparency-level', 'transparency_level', 'theme', (v) => {
        setElText('label-transparency-level', `${v}%`);
        applyTransparency(v, document.getElementById('toggle-transparency')?.classList.contains('on'));
    });

    // Storage
    const clearStorageBtn = document.getElementById('btn-clear-storage');
    if (clearStorageBtn) {
        clearStorageBtn.addEventListener('click', async () => {
            if (!window.confirm('Очистить кэш обложек, потоков и временных файлов? Скачанная музыка останется.')) return;
            clearStorageBtn.disabled = true;
            try {
                if (!window.pywebview?.api?.clear_storage_cache) throw new Error('Bridge unavailable');
                const res = await window.pywebview.api.clear_storage_cache();
                if (res && res.success) {
                    showToast('Кэш успешно очищен!', 'success');
                    if (res.details) onStorageInfo(res.details);
                } else {
                    showToast('Ошибка очистки кэша', 'error');
                }
            } catch {
                showToast('Не удалось очистить кэш. Повторите действие.', 'error');
            } finally { clearStorageBtn.disabled = false; }
        });
    }

    // Import an entire local music folder through the native folder picker.
    const importFolderBtn = document.getElementById('btn-import-music-folder');
    const importFolderStatus = document.getElementById('music-folder-import-status');
    const importFolderProgress = document.getElementById('music-folder-import-progress');
    let folderImportActive = false;
    let folderImportFinished = false;
    if (importFolderBtn) {
        const onProgress = event => {
            if (!folderImportActive) return;
            const current = Math.max(0, Number(event.detail?.current) || 0);
            const total = Math.max(0, Number(event.detail?.total) || 0);
            if (importFolderProgress) {
                importFolderProgress.hidden = total <= 0;
                importFolderProgress.max = Math.max(1, total);
                importFolderProgress.value = Math.min(current, total || current);
            }
            if (importFolderStatus) importFolderStatus.textContent = total > 0 ? `Сканирование файлов: ${current} из ${total}` : `Найдено файлов: ${current}`;
        };
        const onComplete = event => {
            if (!folderImportActive) return;
            folderImportActive = false;
            folderImportFinished = true;
            importFolderBtn.disabled = false;
            if (importFolderProgress) importFolderProgress.hidden = true;
            const count = Math.max(0, Number(event.detail?.count) || 0);
            if (importFolderStatus) importFolderStatus.textContent = `Импорт завершён: добавлено ${count} треков`;
            showToast(count ? `Добавлено треков: ${count}` : 'В папке не найдено новых треков', count ? 'success' : 'info');
            window.refreshActiveLibraryView?.();
            window.dispatchEvent(new CustomEvent('nedotify:library_import_complete', { detail: { count } }));
        };
        window.addEventListener('nedotify:scan_progress', onProgress);
        window.addEventListener('nedotify:scan_complete', onComplete);
        importFolderBtn.addEventListener('click', async () => {
            if (folderImportActive) return;
            folderImportActive = true;
            folderImportFinished = false;
            importFolderBtn.disabled = true;
            if (importFolderStatus) importFolderStatus.textContent = 'Выберите папку…';
            try {
                if (!window.pywebview?.api?.import_music_folder) throw new Error('Folder import is unavailable');
                const result = await window.pywebview.api.import_music_folder();
                if (result?.cancelled) {
                    folderImportActive = false;
                    if (importFolderStatus) importFolderStatus.textContent = '';
                    return;
                }
                if (result?.success && !result?.pending) {
                    folderImportActive = false;
                    const count = Math.max(0, Number(result.count) || 0);
                    if (importFolderStatus) importFolderStatus.textContent = `Импорт завершён: добавлено ${count} треков`;
                    showToast(`Добавлено треков: ${count}`, count ? 'success' : 'info');
                    window.refreshActiveLibraryView?.();
                } else if (result?.pending) {
                    if (!folderImportFinished) {
                        if (importFolderStatus) importFolderStatus.textContent = result.path ? `Сканирование: ${result.path}` : 'Сканирование папки…';
                        if (importFolderProgress) { importFolderProgress.hidden = false; importFolderProgress.value = 0; }
                    }
                } else {
                    throw new Error(result?.error || 'Folder import failed');
                }
            } catch (error) {
                folderImportActive = false;
                if (importFolderStatus) importFolderStatus.textContent = 'Не удалось импортировать папку';
                showToast('Не удалось импортировать папку с музыкой', 'error');
            } finally {
                if (!folderImportActive) importFolderBtn.disabled = false;
            }
        });
    }

    // Listening history is a separate, explicitly confirmed destructive action.
    const clearListeningHistoryBtn = document.getElementById('btn-clear-listening-history');
    if (clearListeningHistoryBtn) {
        clearListeningHistoryBtn.addEventListener('click', async () => {
            if (!window.confirm('Удалить историю прослушивания и данные рекомендаций? Это действие нельзя отменить.')) return;
            clearListeningHistoryBtn.disabled = true;
            try {
                if (!window.pywebview?.api?.clear_listening_history) throw new Error('History clearing is unavailable');
                let result = await window.pywebview.api.clear_listening_history(false);
                if (result?.confirmation_required) result = await window.pywebview.api.clear_listening_history(true);
                if (!result?.success) throw new Error(result?.error || 'History clearing failed');
                showToast('История прослушивания очищена', 'success');
                window.refreshActiveLibraryView?.();
            } catch {
                showToast('Не удалось очистить историю прослушивания', 'error');
            } finally { clearListeningHistoryBtn.disabled = false; }
        });
    }

    const selectAutoDlQuota = document.getElementById('select-auto-download-quota');
    if (selectAutoDlQuota) {
        selectAutoDlQuota.value = String(savedSetting('storage', 'auto_download_favorites_quota_gb', 20));
        selectAutoDlQuota.addEventListener('change', async (e) => {
            const val = parseInt(e.target.value);
            if (Number.isNaN(val)) return;
            if (await saveSetting('auto_download_favorites_quota_gb', val, 'storage')) {
                showToast(val === 0 ? 'Лимит автозагрузки снят' : `Лимит автозагрузки: ${val} ГБ`, 'info');
            }
        });
    }

    const selectCacheQuota = document.getElementById('select-cache-quota');
    if (selectCacheQuota) {
        const savedQuota = savedSetting('storage', 'cache_quota_gb', 5);
        selectCacheQuota.value = String(savedQuota);

        selectCacheQuota.addEventListener('change', async (e) => {
            const val = parseInt(e.target.value);
            const previous = savedSetting('storage', 'cache_quota_gb', 5);
            selectCacheQuota.disabled = true;
            try {
                const res = await window.pywebview?.api?.set_cache_quota?.(val);
                if (!res?.success) throw new Error('Cache quota failed');
                window.settings.storage ||= {};
                window.settings.storage.cache_quota_gb = val;
                window.settings.storage.cache_size_mb = val * 1024;
                try { localStorage.setItem('nedotify_storage_cache_quota_gb', JSON.stringify(val)); } catch {}
                showToast(val === 0 ? 'Лимит кэша отключён' : `Лимит кэша установлен на ${val} ГБ`, 'info');
                if (res.details) onStorageInfo(res.details);
            } catch {
                selectCacheQuota.value = String(previous);
                showToast('Ошибка установки лимита кэша', 'error');
            } finally { selectCacheQuota.disabled = false; }
        });
    }

    // Duplicate Scanner Binding
    const scanDuplicatesBtn = document.getElementById('btn-scan-duplicates');
    const duplicatesContainer = document.getElementById('duplicates-results-container');
    if (scanDuplicatesBtn && duplicatesContainer) {
        scanDuplicatesBtn.addEventListener('click', async () => {
            scanDuplicatesBtn.disabled = true;
            duplicatesContainer.innerHTML = '<div style="font-size:12px; color:var(--text-sec); display:flex; align-items:center; gap:8px;"><div class="spinner" style="width:14px;height:14px;"></div> Сканирование медиатеки на дубликаты...</div>';
            if (window.pywebview?.api?.find_duplicate_tracks) {
                try {
                    const groups = await window.pywebview.api.find_duplicate_tracks();
                    renderDuplicateGroups(groups, duplicatesContainer);
                    const n = Array.isArray(groups) ? groups.length : 0;
                    window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: n === 0 ? 'Дубликатов не найдено' : `Найдено групп дубликатов: ${n}`, type: n === 0 ? 'success' : 'info' } }));
                } catch (e) {
                    duplicatesContainer.innerHTML = '<div style="font-size:12px; color:var(--text-sec);">Ошибка сканирования</div>';
                    window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Ошибка сканирования дубликатов', type: 'error' } }));
                }
            } else {
                duplicatesContainer.innerHTML = '<div style="font-size:12px; color:var(--text-sec);">Сканирование недоступно</div>';
            }
            scanDuplicatesBtn.disabled = false;
        });
    }
    // Setup font size slider
    setupSlider('slider-font-size', 'font_size', 'theme', (val) => {
        applyFontSize(val);
    }, () => document.documentElement.dataset.uiStyle === 'macos' ? {key:'macos_font_size',category:'interface'} : {key:'font_size',category:'theme'});

    applyFontSize(savedSetting('theme', 'font_size', 14));
    applyGlassBlur(savedSetting('theme', 'glass_blur', 15));

    // Custom theme random button lives in setupAppearancePanel() (single source).
    // (Removed duplicate minimal listener that overwrote only --primary/--accent
    //  and double-fired alongside the full-palette generator.)

    // Playlist Import
    const btnImport = document.getElementById('btn-import-playlist');
    const inputImportUrl = document.getElementById('input-import-playlist-url');
    const inputImportName = document.getElementById('input-import-playlist-name');
    const statusImport = document.getElementById('import-playlist-status');

    if (btnImport && inputImportUrl) {
        btnImport.addEventListener('click', async () => {
            const url = inputImportUrl.value.trim();
            const name = inputImportName ? inputImportName.value.trim() : '';
            if (!url) {
                window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Введите ссылку на плейлист', type: 'warning' } }));
                return;
            }
            if (statusImport) {
                statusImport.style.display = 'block';
                statusImport.textContent = '⏳ Анализ и получение треков плейлиста...';
            }
            btnImport.disabled = true;

            try {
                if (window.pywebview?.api?.import_external_playlist) {
                    const res = await window.pywebview.api.import_external_playlist(url, name);
                    if (res && res.success) {
                        const plName = res.playlist_name || res.name || 'Импортированный';
                        const count = res.imported_count ?? res.count ?? 0;
                        window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: `Импортирован плейлист "${plName}" (${count} треков)`, type: 'success' } }));
                        inputImportUrl.value = '';
                        if (inputImportName) inputImportName.value = '';
                    } else {
                        window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: res?.error || 'Не удалось импортировать плейлист', type: 'error' } }));
                    }
                } else showToast('Импорт недоступен: нет подключения к приложению', 'error');
            } catch (e) {
                window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Ошибка при импорте плейлиста', type: 'error' } }));
            } finally {
                btnImport.disabled = false;
                if (statusImport) statusImport.style.display = 'none';
            }
        });
    }

    // Auth inputs/select bindings
    const selectBrowserCookies = document.getElementById('select-browser-cookies');
    if (selectBrowserCookies) {
        selectBrowserCookies.addEventListener('change', (e) => {
            saveSetting('browser_cookies', e.target.value, 'auth');
        });
    }
    const inputCookiesPath = document.getElementById('input-cookies-path');
    if (inputCookiesPath) {
        inputCookiesPath.addEventListener('change', (e) => {
            saveSetting('cookies_file_path', e.target.value, 'auth');
        });
    }
    const inputProxyUrl = document.getElementById('input-proxy-url');
    if (inputProxyUrl) {
        inputProxyUrl.addEventListener('change', (e) => {
            saveSetting('proxy_url', e.target.value, 'auth');
        });
    }



    const selectRegion = document.getElementById('select-region');
    if (selectRegion) {
        selectRegion.closest('.setting-row')?.remove();
    }

    // YouTube Music OAuth 2.0 stub safeguard (in development)
    const inputOauthClientId = document.getElementById('input-oauth-client-id');
    if (inputOauthClientId) {
        inputOauthClientId.disabled = true;
        inputOauthClientId.title = 'В разработке';
    }
    const inputOauthClientSecret = document.getElementById('input-oauth-client-secret');
    if (inputOauthClientSecret) {
        inputOauthClientSecret.disabled = true;
        inputOauthClientSecret.title = 'В разработке';
    }
    const btnYtmusicOauth = document.getElementById('btn-ytmusic-oauth');
    if (btnYtmusicOauth) {
        btnYtmusicOauth.disabled = true;
        btnYtmusicOauth.title = 'В разработке (YouTube Music OAuth пока недоступен)';
        btnYtmusicOauth.addEventListener('click', (e) => {
            e.preventDefault();
            showToast('YouTube Music OAuth находится в разработке', 'info');
        });
    }

    initKeybinds();
}

function setupAppearancePanel() {
    // 1. Theme Mode Switcher (Dark, Light, System)
    document.querySelectorAll('.theme-mode-btn[data-mode]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.theme-mode-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const mode = btn.dataset.mode;
            saveSetting('theme_mode', mode, 'theme');
            resetCustomPalette(false);
            applyThemeMode(mode);
            saveSetting('theme',document.documentElement.dataset.theme,'theme');
            syncThemeSelection();
        });
    });

    // 2. Custom Theme Color Pickers
    const colorPickers = [
        { id: 'picker-color-primary', prop: '--primary', hasRgb: true },
        { id: 'picker-color-accent', prop: '--accent', hasRgb: true },
        { id: 'picker-color-bg', prop: '--bg-main' },
        { id: 'picker-color-text', prop: '--text-main' },
        { id: 'picker-color-card', prop: '--bg-card' },
        { id: 'picker-color-border', prop: '--border' },
        { id: 'picker-color-dim', prop: '--text-dim' },
        { id: 'picker-color-focus', prop: '--focus' }
    ];

    colorPickers.forEach(item => {
        const el = document.getElementById(item.id);
        if (el) {
            el.addEventListener('input', (e) => {
                const val = e.target.value;
                document.documentElement.style.setProperty(item.prop, val);
                if (item.hasRgb) {
                    const c = val.replace('#', '');
                    const r = parseInt(c.substring(0, 2), 16) || 0;
                    const g = parseInt(c.substring(2, 4), 16) || 0;
                    const b = parseInt(c.substring(4, 6), 16) || 0;
                    document.documentElement.style.setProperty(`${item.prop}-rgb`, `${r}, ${g}, ${b}`);
                }
            });
            el.addEventListener('change', (e) => {
                activateCustomPalette();
                const val = e.target.value;
                saveSetting(item.id.replace('picker-color-', 'color_'), val, 'theme');
                if(item.id==='picker-color-primary')saveSetting('custom_primary',val,'theme');
                if(item.id==='picker-color-accent')saveSetting('custom_accent',val,'theme');
            });
        }
    });

    // Random Theme Palette Generator (single listener: full palette + save)
    const btnRandom = document.getElementById('btn-random-theme');
    if (btnRandom && !btnRandom._boundRandomTheme) {
        btnRandom._boundRandomTheme = true;
        btnRandom.addEventListener('click', () => {
            activateCustomPalette();
            const rHex = () => '#' + Math.floor(Math.random() * 16777215).toString(16).padStart(6, '0');
            colorPickers.forEach(item => {
                const el = document.getElementById(item.id);
                const val = rHex();
                if (el) el.value = val;
                document.documentElement.style.setProperty(item.prop, val);
                if (item.hasRgb) {
                    const c = val.replace('#', '');
                    const r = parseInt(c.substring(0, 2), 16) || 0;
                    const g = parseInt(c.substring(2, 4), 16) || 0;
                    const b = parseInt(c.substring(4, 6), 16) || 0;
                    document.documentElement.style.setProperty(`${item.prop}-rgb`, `${r}, ${g}, ${b}`);
                }
                saveSetting(item.id.replace('picker-color-', 'color_'), val, 'theme');
            });
            const primaryEl = document.getElementById('picker-color-primary');
            const accentEl = document.getElementById('picker-color-accent');
            if (primaryEl) saveSetting('custom_primary', primaryEl.value, 'theme');
            if (accentEl) saveSetting('custom_accent', accentEl.value, 'theme');
            syncCustomColorFields();
            window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Палитра случайно сгенерирована!', type: 'info' } }));
        });
    }

    // Save Custom Theme
    const btnSaveCustom = document.getElementById('btn-save-custom-theme');
    const inputThemeName = document.getElementById('input-custom-theme-name');
    if (btnSaveCustom) {
        btnSaveCustom.addEventListener('click', () => {
            const name = inputThemeName?.value.trim() || 'Моя тема';
            const palette = {};
            colorPickers.forEach(item => {
                const el = document.getElementById(item.id);
                if (el) palette[item.prop] = el.value;
            });
            const saved = getSavedCustomThemes();
            saved.push({ name, palette, date: Date.now() });
            try {localStorage.setItem('nedotify_custom_themes', JSON.stringify(saved));} catch {}
            saveSetting('custom_themes',saved,'theme');
            renderSavedCustomThemes();
            window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: `Тема "${name}" успешно сохранена!`, type: 'success' } }));
        });
    }

    // 3. Font Category Switcher Buttons
    document.querySelectorAll('.font-cat-btn[data-cat]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.font-cat-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            renderFontCards(btn.dataset.cat);
        });
    });

    // 4. Export Font Button
    const btnExportFont = document.getElementById('btn-export-font');
    if (btnExportFont) {
        btnExportFont.addEventListener('click', async () => {
            const fontVal = getComputedStyle(document.documentElement).getPropertyValue('--font-family').trim();
            const fontSize = getComputedStyle(document.documentElement).fontSize;
            const configStr = `font-family: ${fontVal}; font-size: ${fontSize};`;
            try {
                if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
                await navigator.clipboard.writeText(configStr);
                showToast('Конфигурация шрифта скопирована в буфер', 'success');
            } catch {
                showToast('Не удалось скопировать конфигурацию шрифта', 'error');
            }
        });
    }
    const systemMode=window.matchMedia('(prefers-color-scheme: dark)');
    systemMode.addEventListener('change',()=>{
        if(savedSetting('theme','theme_mode','dark')!=='system')return;
        applyThemeMode('system');saveSetting('theme',document.documentElement.dataset.theme,'theme');syncThemeSelection();
    });
}

let _zapretListenersAttached = false;
let selectedMode = 'youtube_discord';
let savedCustomArgs = '';
let savedBinaryPath = '';
let zapretStatusRevision = 0;
let zapretCheckSequence = 0;
let activeZapretCheckId = null;
let zapretCheckTimeout = null;
// BUG-021: an in-flight toggle must survive leaving and re-entering the panel.
let zapretApplyInFlight = false;
// BUG-052: one busy flag locks toggle + mode select + update button together.
let zapretPanelBusy = false;
// BUG-051: safety timer for the (legitimately slow) update call.
let zapretUpdateTimeout = null;
// BUG-006/054: bounded re-reads while the backend answers with a placeholder.
let zapretStatusRefreshTimer = null;
let zapretStatusRefreshAttempts = 0;
// BUG-050 priority rule: while a check/update operation owns the status line,
// background status refreshes must not overwrite its text.
let zapretCheckHold = false;
let zapretUpdateHold = false;
// E2 (BUG-020 race): the completion event of the ACTIVE check can arrive
// while a busy answer is still in flight (the bridge promise resolves after
// window.onPythonEvent already delivered the result). The event's rid does
// not match the waiting one yet, so it used to be dropped and the UI waited
// 30 s for an event that had already fired. Dropped completions are cached
// here (bounded) until a busy answer adopts their rid.
const zapretCompletedChecks = new Map();
// The backend emits zapret_network_issue once per True->False transition; the
// window only guards against event replays on the UI side.
let zapretNetworkIssueAt = 0;

const ZAPRET_STATUS_RETRY_DELAY_MS = 2000;
const ZAPRET_STATUS_RETRY_MAX_ATTEMPTS = 3;
const ZAPRET_CHECK_TIMEOUT_MS = 30000;
const ZAPRET_UPDATE_TIMEOUT_MS = 120000;
// BUG-055: the modes that ship as static <option>s in index.html. Anything
// else in status.mode is a legacy/DB value and needs a placeholder option.
const ZAPRET_PRESET_MODES = new Set(['youtube_discord', 'standard', 'aggressive', 'multisplit', 'tcp_udp']);

function _toBool(v) {
    if (typeof v === 'boolean') return v;
    if (typeof v === 'string') return v.trim().toLowerCase() === 'true' || v === '1';
    return !!v;
}

function _zapretStatusIsStub(status) {
    // BUG-006: the backend placeholder ("Определение статуса...") and the
    // degraded rebuild ("Ошибка определения статуса", BUG-041) must never
    // reach the toggle. A payload without a message AND without the basic
    // fields counts as a stub too. The api-level error shape
    // (get_zapret_status catch: {running:false, error:...} without a message)
    // is NOT a state read either — trusting its running=false would flip the
    // toggle off while the process may well be alive.
    if (!status || typeof status !== 'object') return true;
    const msg = typeof status.message === 'string' ? status.message : '';
    if (msg === 'Определение статуса...' || msg === 'Ошибка определения статуса') return true;
    if (!msg && status.error) return true;
    return !msg && !('running' in status);
}

function setupZapretPanel() {
    const toggleZapret = document.getElementById('toggle-zapret-enabled');
    const toggleAutoStart = document.getElementById('toggle-zapret-autostart');
    const chkAutoStart = document.getElementById('zapret-auto-start');
    const selectZapretMode = document.getElementById('select-zapret-mode');
    const modeTrigger = document.getElementById('zapret-mode-trigger');
    const modeMenu = document.getElementById('zapret-mode-menu');
    function closeModeMenu() {
        if (!modeMenu || !modeTrigger) return;
        modeMenu.hidden = true;
        modeTrigger.setAttribute('aria-expanded', 'false');
    }
    function syncModePicker() {
        if (!modeTrigger || !modeMenu || !selectZapretMode) return;
        const options = Array.from(selectZapretMode.options);
        modeTrigger.textContent = options.find(o => o.value === selectZapretMode.value)?.textContent || 'Выберите режим';
        modeMenu.replaceChildren();
        options.forEach(option => {
            const button = document.createElement('button');
            button.type = 'button';
            button.setAttribute('role', 'option');
            button.setAttribute('aria-selected', String(option.value === selectZapretMode.value));
            button.textContent = option.textContent;
            button.addEventListener('click', () => {
                if (selectZapretMode.disabled) return;
                selectZapretMode.value = option.value;
                selectZapretMode.dispatchEvent(new Event('change', {bubbles:true}));
                syncModePicker();
                closeModeMenu();
                modeTrigger.focus();
            });
            modeMenu.appendChild(button);
        });
    }
    if (modeTrigger && modeMenu && !modeTrigger._pickerReady) {
        modeTrigger._pickerReady = true;
        modeTrigger.addEventListener('click', () => {
            if (modeTrigger.disabled) return;
            const opening = modeMenu.hidden;
            syncModePicker();
            modeMenu.hidden = !opening;
            modeTrigger.setAttribute('aria-expanded', String(opening));
            if (opening) modeMenu.querySelector('[aria-selected="true"]')?.focus();
        });
        modeMenu.addEventListener('keydown', event => {
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                closeModeMenu();
                modeTrigger.focus();
                return;
            }
            const items = Array.from(modeMenu.querySelectorAll('button'));
            const index = items.indexOf(document.activeElement);
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault();
                items[(index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
            }
        });
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape' && !modeMenu.hidden) { event.preventDefault(); closeModeMenu(); modeTrigger.focus(); }
        });
        document.addEventListener('click', event => {
            if (!modeTrigger.parentElement.contains(event.target)) closeModeMenu();
        });
    }
    syncModePicker();
    const toggleAutoUpdate = document.getElementById('toggle-zapret-autoupdate');
    const btnUpdateZapret = document.getElementById('btn-update-zapret');
    const btnCheckZapretUpdate = document.getElementById('btn-check-zapret-update');
    const versionBadge = document.getElementById('zapret-version-badge');
    const updateStatus = document.getElementById('zapret-update-status');

    function setSwitchState(btn, isOn) {
        if (!btn) return;
        btn.classList.toggle('on', Boolean(isOn));
        // BUG-056: switch semantics must track the visual state everywhere the
        // .on class changes.
        btn.setAttribute('aria-checked', String(Boolean(isOn)));
    }

    function setAutoStartState(isOn) {
        const flag = Boolean(isOn);
        setSwitchState(toggleAutoStart, flag);
        if (chkAutoStart) chkAutoStart.checked = flag;
    }

    function setZapretPanelBusy(busy) {
        // BUG-052: toggle, mode select and the update button form one critical
        // section — a second toggle would spawn a second UAC flow, an update
        // would swap winws.exe under a starting process. The check button
        // stays usable: it is async, correlation-safe, and busy is explicitly
        // handled in its own branch.
        zapretPanelBusy = Boolean(busy);
        if (toggleZapret) toggleZapret.disabled = zapretPanelBusy;
        if (selectZapretMode) selectZapretMode.disabled = zapretPanelBusy;
        if (modeTrigger) { modeTrigger.disabled = zapretPanelBusy; if (zapretPanelBusy) closeModeMenu(); }
        if (btnUpdateZapret) {
            btnUpdateZapret.disabled = zapretPanelBusy;
            btnUpdateZapret.style.opacity = zapretPanelBusy ? '0.6' : '1';
        }
    }

    function statusMessageHold() {
        return zapretCheckHold || zapretUpdateHold;
    }

    function setStatusText(text) {
        if (updateStatus) updateStatus.textContent = text;
    }

    function ensureModeOption(mode) {
        // BUG-055: a stored mode without a matching <option> (custom modes
        // from older versions / DB edits) rendered an empty select. Inject a
        // placeholder that preserves the value; custom_args stay available in
        // savedCustomArgs and travel with the next toggle.
        if (!selectZapretMode || typeof document === 'undefined' || typeof document.createElement !== 'function') return;
        // A preset always has its static option from the markup — injecting it
        // again would stack duplicates when the reported mode alternates
        // (the old single-slot guard only remembered the last injected mode).
        if (ZAPRET_PRESET_MODES.has(mode)) return;
        const injected = selectZapretMode._zapretInjectedModes
            || (selectZapretMode._zapretInjectedModes = new Set());
        if (injected.has(mode)) return;
        injected.add(mode);
        const opt = document.createElement('option');
        opt.value = mode;
        opt.textContent = mode === 'custom' ? 'Свой режим (custom_args)' : 'Режим: ' + mode;
        selectZapretMode.appendChild(opt);
    }

    function pruneInjectedModeOptions(activeMode) {
        // BUG-055: once the backend reports a real mode again, drop the
        // placeholder option(s) injected earlier so repeated panel visits and
        // mode switches never accumulate entries. Only options this module
        // injected are candidates — static markup is never touched.
        if (!selectZapretMode) return;
        const injected = selectZapretMode._zapretInjectedModes;
        if (!injected || !injected.size) return;
        const kids = selectZapretMode.children;
        if (!kids || typeof kids.length !== 'number') return;
        for (let i = kids.length - 1; i >= 0; i--) {
            const opt = kids[i];
            if (!opt || !injected.has(opt.value) || opt.value === activeMode) continue;
            injected.delete(opt.value);
            if (Array.isArray(kids)) kids.splice(i, 1);
            else if (typeof selectZapretMode.removeChild === 'function') selectZapretMode.removeChild(opt);
        }
    }

    function applyZapretStatus(status) {
        if (!status || typeof status !== 'object') return;
        if (_zapretStatusIsStub(status)) {
            // BUG-006: the placeholder's running=false must never flip the
            // toggle; just say the status is still being determined.
            if (!statusMessageHold()) {
                setStatusText(status.error
                    ? 'Не удалось получить статус Zapret — повторяем попытку…'
                    : 'Определение статуса…');
            }
            return;
        }
        const isRunning = _toBool(status.running);
        setSwitchState(toggleZapret, isRunning);
        setAutoStartState(_toBool(status.auto_start));
        if (status.mode && selectZapretMode) {
            selectedMode = status.mode;
            if (selectZapretMode.value !== status.mode) ensureModeOption(status.mode);
            selectZapretMode.value = status.mode;
            pruneInjectedModeOptions(status.mode);
            syncModePicker();
        }
        if (versionBadge && status.version) versionBadge.textContent = status.version;
        savedCustomArgs = status.custom_args || '';
        savedBinaryPath = status.binary_path || '';
        if (toggleAutoUpdate && status.autoupdate !== undefined) {
            setSwitchState(toggleAutoUpdate, _toBool(status.autoupdate));
        }
        // BUG-050: surface the causal status message and the enabled/running
        // mismatch (and BUG-053's auto_start-without-enabled dead end).
        if (!statusMessageHold()) setStatusText(status.message || '');
        const warn = document.getElementById('zapret-state-warning');
        if (warn) {
            const enabled = _toBool(status.enabled);
            const autoStart = _toBool(status.auto_start);
            let warning = '';
            if (enabled && !isRunning) {
                warning = 'Службы Zapret включены в настройках, но процесс сейчас не запущен — включите тумблер вручную.';
            } else if (autoStart && !enabled) {
                warning = 'Автозапуск включён, но службы Zapret выключены — автозапуск не сработает.';
            }
            warn.style.display = warning ? 'block' : 'none';
            warn.textContent = warning;
        }
    }

    function clearZapretStatusRetryTimer() {
        if (zapretStatusRefreshTimer) {
            clearTimeout(zapretStatusRefreshTimer);
            zapretStatusRefreshTimer = null;
        }
    }

    function scheduleZapretStatusRetry() {
        // BUG-006/054: bounded re-read loop — stops after the first real
        // status or a few attempts; never a permanent interval.
        if (zapretStatusRefreshAttempts >= ZAPRET_STATUS_RETRY_MAX_ATTEMPTS) return;
        zapretStatusRefreshAttempts++;
        clearZapretStatusRetryTimer();
        zapretStatusRefreshTimer = setTimeout(() => {
            zapretStatusRefreshTimer = null;
            refreshZapretStatus();
        }, ZAPRET_STATUS_RETRY_DELAY_MS);
    }

    function refreshZapretStatus() {
        const revision = ++zapretStatusRevision;
        if (!window.pywebview?.api?.get_zapret_status) {
            // BUG-054: the panel can be set up before pywebview injects the
            // bridge (cold WebView2 start). Wait on the shared awaitBridge
            // gate when available; otherwise fall back to the bounded retry
            // loop above.
            if (typeof window.awaitBridge === 'function') {
                window.awaitBridge().then(() => {
                    if (revision === zapretStatusRevision) refreshZapretStatus();
                }).catch(() => {});
            } else {
                scheduleZapretStatusRetry();
            }
            return;
        }
        window.pywebview.api.get_zapret_status().then(status => {
            if (revision !== zapretStatusRevision) return; // superseded by a newer read
            if (zapretApplyInFlight) return;               // BUG-021: never clobber an in-flight toggle
            applyZapretStatus(status);
            if (status && !_zapretStatusIsStub(status)) {
                zapretStatusRefreshAttempts = 0;
                clearZapretStatusRetryTimer();
            } else {
                scheduleZapretStatusRetry();
            }
        }).catch(() => {
            // A transient bridge failure also deserves a bounded re-read.
            if (revision === zapretStatusRevision) scheduleZapretStatusRetry();
        });
    }

    async function applyZapret(enable) {
        const customArgs = savedCustomArgs || '';
        const binPath = savedBinaryPath || '';
        zapretStatusRevision++;      // supersede pending refresh applications
        zapretApplyInFlight = true;  // BUG-021
        setZapretPanelBusy(true);    // BUG-052
        if (enable) setStatusText('Включение Zapret. При первом включении подбор стратегий может занять несколько минут. Windows может запросить права администратора.');
        const cancelSelection = document.createElement('button');
        cancelSelection.type = 'button';
        cancelSelection.className = 'btn btn-secondary';
        cancelSelection.textContent = 'Отменить включение';
        cancelSelection.onclick = async () => {
            cancelSelection.disabled = true;
            setStatusText('Отмена подбора…');
            try {
                const result = await window.pywebview.api.toggle_zapret(false, selectedMode, customArgs, binPath);
                if (!result.success) showToast(result.message || result.error, 'warning');
            } catch { showToast('Не удалось отменить включение', 'error'); }
        };
        if (enable) updateStatus?.parentElement?.appendChild(cancelSelection);
        try {
            if (!window.pywebview?.api?.toggle_zapret) throw new Error('Bridge unavailable');
            const res = await window.pywebview.api.toggle_zapret(enable, selectedMode, customArgs, binPath);
            if (!res) throw new Error('No response');
            // The backend reports the FACT (is_running, BUG-009): trust it
            // over the optimistic class whenever it is present.
            if (Object.prototype.hasOwnProperty.call(res, 'running')) {
                setSwitchState(toggleZapret, _toBool(res.running));
            } else if (!res.success) {
                setSwitchState(toggleZapret, !enable);
            }
            if (!res.success) {
                showToast(res.message || res.error || 'Не удалось изменить состояние Zapret.', 'warning');
            } else if (enable) {
                showToast(res.message || 'Zapret (Обход DPI) успешно включен!', 'success');
            } else {
                showToast(res.message || 'Zapret остановлен', 'info');
            }
        } catch {
            setSwitchState(toggleZapret, !enable);
            showToast('Не удалось изменить состояние Zapret. Повторите действие.', 'error');
        } finally {
            cancelSelection.remove();
            zapretApplyInFlight = false;
            setZapretPanelBusy(false);
            // BUG-021: one authoritative status read once the apply settles,
            // so a UAC/download-delayed start still lands on the toggle.
            refreshZapretStatus();
        }
    }

    if (!_zapretListenersAttached) {
        _zapretListenersAttached = true;

        function finishZapretCheckWait(statusText) {
            activeZapretCheckId = null;
            zapretCheckHold = false;
            if (zapretCheckTimeout) {
                clearTimeout(zapretCheckTimeout);
                zapretCheckTimeout = null;
            }
            if (btnCheckZapretUpdate) btnCheckZapretUpdate.disabled = false;
            if (statusText) setStatusText(statusText);
        }

        function handleZapretCheckResult(result) {
            const hadTimeout = Boolean(zapretCheckTimeout);
            finishZapretCheckWait(null);
            // BUG-026: the payload carries current/latest versions (there is
            // no `version` field); drive the badge and the honest result text
            // from them, including the manual-update and unknown-version cases.
            // E2: while an update owns the status line (zapretUpdateHold) the
            // check result must not fight it for the text — the update's own
            // completion message lands last and stays.
            if (versionBadge) {
                if (result.latest_version) versionBadge.textContent = result.latest_version;
                else if (result.current_version) versionBadge.textContent = result.current_version;
            }
            if (zapretUpdateHold || zapretApplyInFlight) return;
            if (result.error) {
                setStatusText('Не удалось проверить обновления');
                showToast('Не удалось проверить обновления Zapret', 'error');
            } else if (result.version_unknown) {
                setStatusText('Не удалось определить последнюю доступную версию');
            } else if (result.manual_update_required) {
                setStatusText(result.latest_version
                    ? `Доступна версия Zapret ${result.latest_version} — обновите приложение NeDotify`
                    : 'Доступна новая версия Zapret — обновите приложение NeDotify');
            } else if (result.update_available) {
                setStatusText(result.current_version
                    ? `Установлена ${result.current_version} → доступна ${result.latest_version || '?'}. Нажмите «Обновить».`
                    : 'Доступна новая версия. Нажмите «Обновить».');
            } else if (result.latest_version || !hadTimeout) {
                setStatusText('Установлена последняя версия');
            }
        }

        function armZapretCheckTimeout(rid, busy) {
            if (zapretCheckTimeout) clearTimeout(zapretCheckTimeout);
            zapretCheckTimeout = setTimeout(() => {
                if (activeZapretCheckId !== rid) return;
                zapretCheckTimeout = null;
                finishZapretCheckWait(busy
                    ? 'Предыдущая проверка всё ещё выполняется — повторите позже.'
                    : 'Проверка заняла слишком много времени. Повторите попытку.');
            }, ZAPRET_CHECK_TIMEOUT_MS);
        }

        if (btnCheckZapretUpdate) {
            btnCheckZapretUpdate.addEventListener('click', async () => {
                const requestId = `zapret-check:${++zapretCheckSequence}`;
                activeZapretCheckId = requestId;
                zapretCheckHold = true;
                armZapretCheckTimeout(requestId, false);
                btnCheckZapretUpdate.disabled = true;
                setStatusText('Проверяем наличие обновлений…');
                try {
                    if (!window.pywebview?.api?.check_zapret_update) throw new Error('Bridge unavailable');
                    const result = await window.pywebview.api.check_zapret_update(requestId);
                    if (result && result.status === 'busy') {
                        // BUG-020: another check is already running. Correlate
                        // with the ACTIVE request id the backend reports and
                        // keep waiting for its completion event; never restart
                        // the timeout against a rid the event will never carry.
                        // E2: only the click that still owns the wait may adopt
                        // it — a late busy answer after the wait was finished
                        // must not resurrect it.
                        if (requestId !== activeZapretCheckId) return;
                        const activeRid = result.request_id ? String(result.request_id) : '';
                        if (!activeRid) {
                            finishZapretCheckWait('Проверка уже выполняется — дождитесь завершения');
                            showToast('Проверка обновлений уже выполняется', 'info');
                            return;
                        }
                        // E2: the active check may have completed while this
                        // busy answer was in flight — its event was cached, so
                        // the result lands now instead of after a dead 30 s.
                        const completed = zapretCompletedChecks.get(activeRid);
                        if (completed) {
                            zapretCompletedChecks.delete(activeRid);
                            activeZapretCheckId = activeRid;
                            handleZapretCheckResult(completed);
                            return;
                        }
                        activeZapretCheckId = activeRid;
                        armZapretCheckTimeout(activeRid, true);
                        setStatusText('Проверка уже выполняется…');
                        return;
                    }
                    if (requestId !== activeZapretCheckId) return;
                    if (result?.status !== 'pending' && result?.success === false) throw new Error(result.error || 'Check failed');
                } catch {
                    if (requestId === activeZapretCheckId) {
                        finishZapretCheckWait('Не удалось проверить обновления');
                        showToast('Не удалось проверить обновления Zapret', 'error');
                    }
                }
            });
        }
        window.addEventListener('nedotify:zapret_update_checked', event => {
            const result = event.detail || {};
            if (result.request_id !== activeZapretCheckId) {
                // E2: completion for a rid nobody waits on right now (e.g. the
                // busy adoption has not happened yet). Cache it briefly so the
                // busy branch can land it; bounded, stale entries are ignored.
                if (result && result.request_id) {
                    zapretCompletedChecks.set(String(result.request_id), result);
                    if (zapretCompletedChecks.size > 4) {
                        zapretCompletedChecks.delete(zapretCompletedChecks.keys().next().value);
                    }
                }
                return;
            }
            handleZapretCheckResult(result);
        });

        if (toggleAutoStart) {
            toggleAutoStart.addEventListener('click', () => {
                const isOn = !toggleAutoStart.classList.contains('on');
                setAutoStartState(isOn);
                saveSetting('auto_start', isOn, 'zapret');
                zapretStatusRevision++;
                showToast(isOn ? 'Автозапуск Zapret включен' : 'Автозапуск Zapret отключен', 'info');
            });
        }
        // BUG-057: the `change` handler on the hidden #zapret-auto-start
        // checkbox was dead code (display:none, never clicked programmatically)
        // — removed. The toggle button above is the single writer.

        if (selectZapretMode) {
            selectZapretMode.addEventListener('change', (e) => {
                selectedMode = e.target.value;
                // Persist immediately, regardless of the enable toggle state.
                saveSetting('mode', selectedMode, 'zapret');
                zapretStatusRevision++;
                if (toggleZapret && toggleZapret.classList.contains('on') && !zapretPanelBusy) {
                    applyZapret(true);
                }
            });
        }

        if (toggleAutoUpdate) {
            toggleAutoUpdate.addEventListener('click', () => {
                const isOn = !toggleAutoUpdate.classList.contains('on');
                setSwitchState(toggleAutoUpdate, isOn);
                saveSetting('autoupdate', isOn, 'zapret');
                zapretStatusRevision++;
            });
        }

        if (btnUpdateZapret) {
            btnUpdateZapret.addEventListener('click', async () => {
                if (zapretPanelBusy) return;
                setZapretPanelBusy(true);
                zapretUpdateHold = true;
                setStatusText('Проверка и загрузка актуальной версии...');
                zapretUpdateTimeout = setTimeout(() => {
                    // BUG-051: the update is legitimately slow (download +
                    // restart), but a hung bridge call must not lock the panel
                    // forever.
                    zapretUpdateTimeout = null;
                    zapretUpdateHold = false;
                    setZapretPanelBusy(false);
                    setStatusText('Обновление не завершилось вовремя — проверьте статус и повторите.');
                    showToast('Обновление Zapret не уложилось в отведённое время', 'warning');
                }, ZAPRET_UPDATE_TIMEOUT_MS);
                try {
                    if (!window.pywebview?.api?.update_zapret) throw new Error('Bridge unavailable');
                    const res = await window.pywebview.api.update_zapret(true);
                    if (res?.success) {
                        if (versionBadge && res.status?.version) versionBadge.textContent = res.status.version;
                        if (updateStatus && res.message) setStatusText(res.message);
                        showToast(res.message || 'Zapret успешно обновлен!', 'success');
                    } else {
                        if (updateStatus && res?.message) setStatusText(res.message);
                        showToast(res?.message || res?.error || 'Не удалось обновить Zapret', 'error');
                    }
                } catch (err) {
                    setStatusText(err && err.message === 'Bridge unavailable'
                        ? 'Мост недоступен — обновление невозможно'
                        : 'Ошибка сети при обновлении');
                    showToast('Не удалось обновить Zapret', 'error');
                } finally {
                    if (zapretUpdateTimeout) {
                        clearTimeout(zapretUpdateTimeout);
                        zapretUpdateTimeout = null;
                    }
                    zapretUpdateHold = false;
                    setZapretPanelBusy(false);
                    // The update may have swapped the binary: one status read.
                    refreshZapretStatus();
                }
            });
        }

        if (toggleZapret) {
            toggleZapret.addEventListener('click', () => {
                if (zapretPanelBusy) return; // BUG-052
                const isOn = !toggleZapret.classList.contains('on');
                setSwitchState(toggleZapret, isOn);
                applyZapret(isOn);
            });
        }

        // Zapret lifecycle events routed by events.js (A/C agents' backend).
        window.addEventListener('nedotify:zapret_crashed', event => {
            const data = event.detail || {};
            showToast(data.message || 'Процесс Zapret неожиданно завершился', 'error');
            refreshZapretStatus();
        });
        window.addEventListener('nedotify:zapret_network_issue', event => {
            const data = event.detail || {};
            const now = Date.now();
            if (now - zapretNetworkIssueAt < 30000) return; // once per transition
            zapretNetworkIssueAt = now;
            showToast(data.message || 'Zapret запущен, но подключение к интернету потеряно', 'warning');
        });
        window.addEventListener('nedotify:zapret_still_running', event => {
            const data = event.detail || {};
            showToast(data.message || 'Процесс Zapret остался запущен после выхода из приложения', 'warning');
        });
        window.addEventListener('nedotify:zapret_autostart_failed', event => {
            const data = event.detail || {};
            showToast(data.message || 'Не удалось автоматически запустить Zapret', 'warning');
            refreshZapretStatus();
        });
        window.addEventListener('nedotify:zapret_selection_progress', event => {
            setStatusText(event.detail?.message || 'Подбор стратегий…');
        });
        window.addEventListener('nedotify:zapret_download_started', event => {
            const data = event.detail || {};
            // E2: while a check/update owns the status line, phase text from a
            // concurrent background download must not overwrite it.
            if (!statusMessageHold()) setStatusText(data.message || 'Загрузка файлов Zapret…');
        });
        window.addEventListener('nedotify:zapret_download_finished', event => {
            const data = event.detail || {};
            if (!statusMessageHold()) setStatusText(data.message || 'Файлы Zapret успешно загружены');
            if (data.version && versionBadge) versionBadge.textContent = data.version;
            refreshZapretStatus();
        });
        window.addEventListener('nedotify:zapret_download_failed', event => {
            const data = event.detail || {};
            if (!statusMessageHold()) setStatusText(data.message || 'Не удалось загрузить файлы Zapret');
            showToast(data.message || 'Не удалось загрузить файлы Zapret', 'error');
            refreshZapretStatus();
        });
    }

    // Refresh Status (runs on every panel entry; BUG-006/054: stub answers and
    // a missing bridge re-read on a bounded loop instead of sticking).
    refreshZapretStatus();
}

function setupBackgroundPanel() {
    const btnUpload = document.getElementById('btn-upload-bg-image');
    const inputBgFile = document.getElementById('input-bg-file');
    const btnRemove = document.getElementById('btn-remove-bg-image');

    if (btnUpload && inputBgFile) {
        btnUpload.addEventListener('click', () => inputBgFile.click());
        inputBgFile.addEventListener('change', (e) => {
            const file = e.target.files && e.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onerror = () => showToast('Не удалось прочитать изображение', 'error');
                reader.onload = (event) => {
                    const dataUrl = event.target.result;
                    compressBackgroundImage(dataUrl, (compressed) => {
                        saveSetting('custom_bg_image', compressed, 'theme');
                        const blurVal = parseInt(document.getElementById('slider-bg-blur')?.value || 0);
                        const dimVal = parseInt(document.getElementById('slider-bg-dim')?.value || 30);
                        saveSetting('resource_bg', true, 'optimization');
                        const btnBg = document.querySelector('#opt-active-resources [data-resource="bg"]');
                        if (btnBg) btnBg.classList.add('active');
                        applyResourceToggle('bg', true);
                        applyCustomBg(compressed, blurVal, dimVal);
                    });
                };
                reader.readAsDataURL(file);
                inputBgFile.value = '';
            }
        });
    }

    if (btnRemove) {
        btnRemove.addEventListener('click', () => {
            saveSetting('custom_bg_image', '', 'theme');
            applyCustomBg(null);
        });
    }

    setupSlider('slider-bg-blur', 'bg_blur', 'theme', (v) => {
        const val = parseInt(v) || 0;
        setElText('label-bg-blur', `${val}px`);
        // bg-blur applies ONLY to #custom-bg-layer (via applyCustomBg filter).
        // Glass blur (--glass-blur / --blur-*) is owned exclusively by
        // #slider-glass-blur and must not be touched here.
        const bgUrl = getLocalSetting('nedotify_theme_custom_bg_image', '') || window.settings?.theme?.custom_bg_image;
        const dimVal = parseInt(document.getElementById('slider-bg-dim')?.value || 30);
        if (bgUrl) {
            applyCustomBg(bgUrl, val, dimVal);
        }
    });

    setupSlider('slider-bg-dim', 'bg_dim', 'theme', (v) => {
        const val = parseInt(v) || 0;
        setElText('label-bg-dim', `${val}%`);
        const bgUrl = getLocalSetting('nedotify_theme_custom_bg_image', '') || window.settings?.theme?.custom_bg_image;
        const blurVal = parseInt(document.getElementById('slider-bg-blur')?.value || 0);
        if (bgUrl) {
            applyCustomBg(bgUrl, blurVal, val);
        }
    });

    // Restore saved custom background image on setup
    const savedBg = savedSetting('theme', 'custom_bg_image', '');
    const savedBlur = Math.max(0, Math.min(16, Number(savedSetting('theme', 'bg_blur', 0)) || 0));
    const savedDim = savedSetting('theme', 'bg_dim', 30);

    const blurSlider = document.getElementById('slider-bg-blur');
    if (blurSlider) {
        blurSlider.value = savedBlur;
        setElText('label-bg-blur', `${savedBlur}px`);
    }
    const dimSlider = document.getElementById('slider-bg-dim');
    if (dimSlider) {
        dimSlider.value = savedDim;
        setElText('label-bg-dim', `${savedDim}%`);
    }

    if (savedBg) {
        applyCustomBg(savedBg, savedBlur, savedDim);
    }
}

function setupIconsPanel() {
    const grid = document.getElementById('icon-packs-grid');
    if (!grid) return;

    if (!grid.dataset.bound) {
        grid.dataset.bound = 'true';
        grid.querySelectorAll('.opt-card').forEach(card => {
            card.addEventListener('click', () => {
                const packId = card.dataset.id;
                saveSetting('icon_pack', packId, 'theme');
                applyIconPack(packId);
            });
        });
    }

    applyIconPack(savedSetting('theme', 'icon_pack', document.documentElement.getAttribute('data-icon-pack') || 'aura_neon'));
}

function setupPlayerSettingsPanel() {
    const setupCardGroup = (containerId, settingKey, onChange) => {
        const container = document.getElementById(containerId);
        if (!container) return;
        container.querySelectorAll('.opt-card').forEach(card => {
            card.addEventListener('click', () => {
                container.querySelectorAll('.opt-card').forEach(c => c.classList.remove('active'));
                card.classList.add('active');
                saveSetting(settingKey, card.dataset.val, 'player');
                if (onChange) onChange(card.dataset.val);
            });
        });
    };

    setupCardGroup('opt-title-align', 'title_align', applyTitleAlignment);
    setupCardGroup('opt-player-style', 'player_style', applyPlayerStyle);
    setupCardGroup('opt-slider-type', 'slider_type', applySliderType);
    setupCardGroup('opt-queue-pos', 'queue_pos', applyQueuePosition);
    setupCardGroup('opt-queue-view', 'queue_view', applyQueueViewMode);
    setupCardGroup('opt-mp-progress', 'mp_progress', applyMpProgress);
    setupCardGroup('opt-mp-cover-shape', 'mp_cover_shape', applyMpCoverShape);
    setupCardGroup('opt-mp-shape', 'mp_shape', applyMpShape);

    setupToggle('toggle-show-queue', 'show_queue', 'player', applyShowQueue);
    setupToggle('toggle-compact-queue-btn', 'compact_queue_btn', 'player', applyCompactQueueBtn);
    setupToggle('toggle-next-track-preview', 'next_track_preview', 'player', applyNextTrackPreview);
    setupToggle('toggle-player-prefetch', 'player_prefetch', 'player');
    setupToggle('toggle-auto-download-favorites', 'auto_download_favorites', 'storage',
        (val) => showToast(val ? 'Лайкнутые треки будут сохраняться автоматически' : 'Автосохранение лайков отключено', 'info'));
    setupToggle('toggle-aura-orbs', 'aura_orbs_enabled', 'player', applyAuraOrbs);

    const progressColor = document.getElementById('player-progress-color');
    progressColor?.addEventListener('input', event => applyProgressColor(event.target.value));
    progressColor?.addEventListener('change', event => {
        saveSetting('progress_color', applyProgressColor(event.target.value), 'player');
    });

    setupSlider('player-progress-transparency', 'progress_transparency', 'player', raw => {
        const value = applyProgressTransparency(raw);
        const output = document.getElementById('player-progress-transparency-value');
        if (output) output.value = `${value}%`;
    });

    // Mini-player position buttons
    const mpPosGroup = document.getElementById('mp-pos-btn-group') || document.getElementById('opt-mp-pos');
    if (mpPosGroup) {
        mpPosGroup.querySelectorAll('.opt-card-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                mpPosGroup.querySelectorAll('.opt-card-btn').forEach(b => {
                    b.classList.remove('active');
                    b.style.background = 'var(--bg-card)';
                    b.style.color = '';
                    b.style.borderColor = 'rgba(255,255,255,0.1)';
                });
                btn.classList.add('active');
                btn.style.background = 'var(--primary)';
                btn.style.color = '#fff';
                btn.style.borderColor = 'var(--primary)';

                const pos = btn.dataset.pos;
                saveSetting('mp_pos', pos, 'player');
                applyMpPos(pos);
            });
        });
    }

    // Restore saved settings, backend first (see savedSetting) so a cleared
    // localStorage cannot reset the Player tab back to its defaults.
    const saved = {
        align: savedSetting('player', 'title_align', 'left'),
        style: savedSetting('player', 'player_style', 'default'),
        slider: normalizeProgressStyle(savedSetting('player', 'slider_type', 'bars')),
        progressColor: normalizeProgressColor(savedSetting('player', 'progress_color', '#10d6a3')),
        progressTransparency: Math.min(80, Math.max(0, Number(savedSetting('player', 'progress_transparency', 18)) || 0)),
        showQueue: savedSetting('player', 'show_queue', true),
        queuePos: savedSetting('player', 'queue_pos', 'bottom'),
        compactQueue: savedSetting('player', 'compact_queue_btn', true),
        nextPreview: savedSetting('player', 'next_track_preview', true),
        prefetch: savedSetting('player', 'player_prefetch', true),
        auraOrbs: savedSetting('player', 'aura_orbs_enabled', true),
        queueView: savedSetting('player', 'queue_view', 'normal'),
        mpProg: savedSetting('player', 'mp_progress', 'line'),
        mpCover: savedSetting('player', 'mp_cover_shape', 'default'),
        mpShape: savedSetting('player', 'mp_shape', 'default'),
        mpPos: savedSetting('player', 'mp_pos', 'bottom-right'),
    };

    // Update active UI cards / toggle visuals from the saved state.
    syncPlayerSettingsUI();

    if (mpPosGroup) {
        mpPosGroup.querySelectorAll('.opt-card-btn').forEach(b => {
            const isActive = b.dataset.pos === saved.mpPos;
            b.classList.toggle('active', isActive);
            b.style.background = isActive ? 'var(--primary)' : 'var(--bg-card)';
            b.style.color = isActive ? '#fff' : '';
            b.style.borderColor = isActive ? 'var(--primary)' : 'rgba(255,255,255,0.1)';
        });
    }

    applyTitleAlignment(saved.align);
    applyPlayerStyle(saved.style);
    applySliderType(saved.slider);
    applyProgressColor(saved.progressColor);
    applyProgressTransparency(saved.progressTransparency);
    applyShowQueue(saved.showQueue);
    applyQueuePosition(saved.queuePos);
    applyCompactQueueBtn(saved.compactQueue);
    applyNextTrackPreview(saved.nextPreview);
    applyAuraOrbs(saved.auraOrbs);
    applyQueueViewMode(saved.queueView);
    applyMpProgress(saved.mpProg);
    applyMpCoverShape(saved.mpCover);
    applyMpShape(saved.mpShape);

    applyMpPos(saved.mpPos);
}

export const WORKSHOP_ITEMS = [
    {
        id: 'ws_nebula',
        title: 'Cosmic Abyss Nebula',
        author: 'Starlight',
        likes: 1240,
        downloads: 8540,
        tag: 'atmosphere',
        preview: 'https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1920&auto=format&fit=crop&q=80',
        badge: 'SPACE',
        date: 1785000000
    },
    {
        id: 'ws_aurora',
        title: 'Nordic Aurora Night',
        author: 'AuraNordic',
        likes: 980,
        downloads: 6420,
        tag: 'atmosphere',
        preview: 'https://images.unsplash.com/photo-1531366936337-7c912a4589a7?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1531366936337-7c912a4589a7?w=1920&auto=format&fit=crop&q=80',
        badge: 'AURORA',
        date: 1784999000
    },
    {
        id: 'ws_fluid_dark',
        title: 'Fluid Dark Glassmorphism',
        author: 'GlassLab',
        likes: 1510,
        downloads: 9830,
        tag: 'minimal',
        preview: 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=1920&auto=format&fit=crop&q=80',
        badge: 'GLASS',
        date: 1784998000
    },
    {
        id: 'ws_dark_forest',
        title: 'Emerald Dark Forest',
        author: 'Evergreen',
        likes: 1120,
        downloads: 7310,
        tag: 'atmosphere',
        preview: 'https://images.unsplash.com/photo-1448375240586-882707db888b?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1448375240586-882707db888b?w=1920&auto=format&fit=crop&q=80',
        badge: 'DARK',
        date: 1784997000
    },
    {
        id: 'ws_1',
        title: '11',
        author: 'wqwqwq',
        likes: 2,
        downloads: 7,
        tag: 'anime',
        preview: 'https://images.unsplash.com/photo-1578632767115-351597cf2477?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1578632767115-351597cf2477?w=1920&auto=format&fit=crop&q=80',
        badge: 'GIF',
        date: 1784970000
    },
    {
        id: 'ws_2',
        title: 'forest black',
        author: 'hijiel',
        likes: 16,
        downloads: 121,
        tag: 'atmosphere',
        preview: 'https://images.unsplash.com/photo-1511497584788-876761c1298b?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1511497584788-876761c1298b?w=1920&auto=format&fit=crop&q=80',
        badge: 'LIVE',
        date: 1784965000
    },
    {
        id: 'ws_3',
        title: 'Yuno Gasai',
        author: 'kurashhh',
        likes: 275,
        downloads: 2433,
        tag: 'anime',
        preview: 'https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?w=1920&auto=format&fit=crop&q=80',
        badge: 'POPULAR',
        date: 1784980000
    },
    {
        id: 'ws_4',
        title: 'She <3',
        author: 'NDD',
        likes: 26,
        downloads: 503,
        tag: 'minimal',
        preview: 'https://images.unsplash.com/photo-1534447677768-be436bb09401?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1534447677768-be436bb09401?w=1920&auto=format&fit=crop&q=80',
        badge: '4K',
        date: 1784950000
    },
    {
        id: 'ws_5',
        title: 'Stick your finger d...',
        author: 'kurashhh',
        likes: 571,
        downloads: 4533,
        tag: 'atmosphere',
        preview: 'https://images.unsplash.com/photo-1509114397022-ed747cca3f65?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1509114397022-ed747cca3f65?w=1920&auto=format&fit=crop&q=80',
        badge: 'HOT',
        date: 1784990000
    },
    {
        id: 'ws_6',
        title: 'windows old',
        author: 'alexG',
        likes: 61,
        downloads: 628,
        tag: 'retro',
        preview: 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=1920&auto=format&fit=crop&q=80',
        badge: 'RETRO',
        date: 1784940000
    },
    {
        id: 'ws_7',
        title: 'Cyberpunk Skyline',
        author: 'V_NightCity',
        likes: 412,
        downloads: 3105,
        tag: 'retro',
        preview: 'https://images.unsplash.com/photo-1542751371-adc38448a05e?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1542751371-adc38448a05e?w=1920&auto=format&fit=crop&q=80',
        badge: 'NEON',
        date: 1784930000
    },
    {
        id: 'ws_8',
        title: 'Lofi Cozy Room',
        author: 'ChilledCow',
        likes: 890,
        downloads: 6200,
        tag: 'anime',
        preview: 'https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=1920&auto=format&fit=crop&q=80',
        badge: 'LOFI',
        date: 1784995000
    },
    {
        id: 'ws_9',
        title: 'Cosmic Voyage',
        author: 'Starlight',
        likes: 189,
        downloads: 1420,
        tag: 'atmosphere',
        preview: 'https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1920&auto=format&fit=crop&q=80',
        badge: 'SPACE',
        date: 1784920000
    },
    {
        id: 'ws_10',
        title: 'Neon Waves 80s',
        author: 'SynthRider',
        likes: 310,
        downloads: 2150,
        tag: 'retro',
        preview: 'https://images.unsplash.com/photo-1508739773434-c26b3d09e071?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1508739773434-c26b3d09e071?w=1920&auto=format&fit=crop&q=80',
        badge: 'RETRO',
        date: 1784988000
    },
    {
        id: 'ws_11',
        title: 'Eldritch Moon',
        author: 'DarkSoul',
        likes: 540,
        downloads: 3900,
        tag: 'atmosphere',
        preview: 'https://images.unsplash.com/photo-1532767153582-b1a0e5145009?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1532767153582-b1a0e5145009?w=1920&auto=format&fit=crop&q=80',
        badge: 'DARK',
        date: 1784987000
    },
    {
        id: 'ws_12',
        title: 'Sakura Rain',
        author: 'Kawaiii',
        likes: 720,
        downloads: 5100,
        tag: 'anime',
        preview: 'https://images.unsplash.com/photo-1522383225653-ed111181a951?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1522383225653-ed111181a951?w=1920&auto=format&fit=crop&q=80',
        badge: 'GIF',
        date: 1784986000
    },
    {
        id: 'ws_13',
        title: 'Minecraft Sunset',
        author: 'BlockCraft',
        likes: 430,
        downloads: 2900,
        tag: 'games',
        preview: 'https://images.unsplash.com/photo-1627856013091-fed6e4e30025?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1627856013091-fed6e4e30025?w=1920&auto=format&fit=crop&q=80',
        badge: 'GAME',
        date: 1784985000
    },
    {
        id: 'ws_14',
        title: 'Goth Velvet',
        author: 'Vampress',
        likes: 195,
        downloads: 1120,
        tag: 'minimal',
        preview: 'https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=1920&auto=format&fit=crop&q=80',
        badge: 'ART',
        date: 1784984000
    },
    {
        id: 'ws_15',
        title: 'Pixel Cyberpunk Bar',
        author: 'PixelArtist',
        likes: 680,
        downloads: 4800,
        tag: 'games',
        preview: 'https://images.unsplash.com/photo-1550745165-9bc0b252726f?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1550745165-9bc0b252726f?w=1920&auto=format&fit=crop&q=80',
        badge: 'PIXEL',
        date: 1784983000
    },
    {
        id: 'ws_16',
        title: 'Chainsaw Man Denji',
        author: 'AnimeGuy',
        likes: 810,
        downloads: 6700,
        tag: 'anime',
        preview: 'https://images.unsplash.com/photo-1563089145-599997674d42?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1563089145-599997674d42?w=1920&auto=format&fit=crop&q=80',
        badge: 'HOT',
        date: 1784982000
    },
    {
        id: 'ws_17',
        title: 'Tokyo Rain Night',
        author: 'Kenji_99',
        likes: 490,
        downloads: 3400,
        tag: 'atmosphere',
        preview: 'https://images.unsplash.com/photo-1503899036084-c55cdd92da26?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1503899036084-c55cdd92da26?w=1920&auto=format&fit=crop&q=80',
        badge: '4K',
        date: 1784981000
    },
    {
        id: 'ws_18',
        title: 'Elden Ring Tree',
        author: 'Tarnished',
        likes: 620,
        downloads: 4200,
        tag: 'games',
        preview: 'https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=1920&auto=format&fit=crop&q=80',
        badge: 'LIVE',
        date: 1784979000
    },
    {
        id: 'ws_19',
        title: 'Synth Horizon',
        author: 'OutrunGlow',
        likes: 290,
        downloads: 1850,
        tag: 'retro',
        preview: 'https://images.unsplash.com/photo-1509114397022-ed747cca3f65?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1509114397022-ed747cca3f65?w=1920&auto=format&fit=crop&q=80',
        badge: 'NEON',
        date: 1784978000
    },
    {
        id: 'ws_20',
        title: 'Zero Two Motion',
        author: 'DarlingXx',
        likes: 950,
        downloads: 7300,
        tag: 'anime',
        preview: 'https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?w=1920&auto=format&fit=crop&q=80',
        badge: 'POPULAR',
        date: 1784977000
    },
    {
        id: 'ws_21',
        title: 'Northern Lights',
        author: 'AuroraHunter',
        likes: 380,
        downloads: 2500,
        tag: 'atmosphere',
        preview: 'https://images.unsplash.com/photo-1531366936337-7c912a4589a7?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1531366936337-7c912a4589a7?w=1920&auto=format&fit=crop&q=80',
        badge: '4K',
        date: 1784976000
    },
    {
        id: 'ws_22',
        title: 'Matrix Rain Code',
        author: 'Neo_Operator',
        likes: 410,
        downloads: 2980,
        tag: 'retro',
        preview: 'https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?w=1920&auto=format&fit=crop&q=80',
        badge: 'CODE',
        date: 1784975000
    },
    {
        id: 'ws_23',
        title: 'Gothic Cathedral Mist',
        author: 'DarkArchitect',
        likes: 275,
        downloads: 1940,
        tag: 'atmosphere',
        preview: 'https://images.unsplash.com/photo-1519681393784-d120267933ba?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1519681393784-d120267933ba?w=1920&auto=format&fit=crop&q=80',
        badge: 'DARK',
        date: 1784974000
    },
    {
        id: 'ws_24',
        title: 'Minimal Geometric Gold',
        author: 'LuxDesign',
        likes: 145,
        downloads: 980,
        tag: 'minimal',
        preview: 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=600&auto=format&fit=crop&q=80',
        url: 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=1920&auto=format&fit=crop&q=80',
        badge: 'LUX',
        date: 1784973000
    }
];

// Built-in artwork ships locally. Also resolve old saved Unsplash/proxy URLs.
WORKSHOP_ITEMS.forEach(item => {
    item.preview = window.NeDotifyAssets?.resolveBackground(item.preview) || item.preview;
    item.url = window.NeDotifyAssets?.resolveBackground(item.url) || item.url;
});

let refreshWorkshop = null;


export function setupWorkshopPanel() {
    const grid = document.getElementById('workshop-cards-grid');
    const searchInput = document.getElementById('workshop-search-input');
    const sortSelect = document.getElementById('workshop-sort-select');
    const tagsContainer = document.getElementById('workshop-tags-container');

    if (!grid) return;
    if (refreshWorkshop) { refreshWorkshop(); return; }

    let activeTag = 'all';
    let searchQuery = '';
    let sortMode = 'newest';

    const getLikedState = (id) => localStorage.getItem(`nedotify_ws_like_${id}`) === '1';

    const render = () => {
        let items = [...WORKSHOP_ITEMS];

        if (searchQuery) {
            const q = searchQuery.toLowerCase();
            items = items.filter(it => it.title.toLowerCase().includes(q) || it.author.toLowerCase().includes(q));
        }

        if (activeTag !== 'all') {
            items = items.filter(it => it.tag === activeTag);
        }

        if (sortMode === 'newest') {
            items.sort((a, b) => b.date - a.date);
        } else if (sortMode === 'popular') {
            items.sort((a, b) => b.likes - a.likes);
        } else if (sortMode === 'downloads') {
            items.sort((a, b) => b.downloads - a.downloads);
        }

        if (items.length === 0) {
            grid.innerHTML = '<div class="empty-state" style="grid-column: 1 / -1; padding: 40px; text-align: center; color: var(--text-sec)">Ничего не найдено</div>';
            return;
        }

        const storedBg = savedSetting('theme', 'custom_bg_image', '');
        const activeBgUrl = window.NeDotifyAssets?.resolveBackground(storedBg) || storedBg;

        grid.innerHTML = items.map(it => {
            const isApplied = activeBgUrl === it.url;
            const isLiked = getLikedState(it.id);
            const displayLikes = isLiked ? it.likes + 1 : it.likes;

            const safeId = escapeHtml(String(it.id ?? ''));
            const safePreview = escapeHtml(String(it.preview ?? ''));
            const safeTitle = escapeHtml(String(it.title ?? ''));
            const safeAuthor = escapeHtml(String(it.author ?? ''));
            const safeBadge = it.badge ? escapeHtml(String(it.badge)) : '';

            return `
                <div class="workshop-card ${isApplied ? 'applied' : ''}" data-id="${safeId}">
                    <div class="workshop-card-preview">
                        <img src="${safePreview}" class="workshop-card-media" alt="${safeTitle}" loading="lazy">
                        ${safeBadge ? `<div class="workshop-card-badge">${safeBadge}</div>` : ''}
                        <div class="workshop-card-overlay">
                            <button class="workshop-btn-apply" data-id="${safeId}">
                                <i data-lucide="${isApplied ? 'check' : 'image'}" style="width:16px;height:16px"></i>
                                <span>${isApplied ? 'Установлено' : 'Применить'}</span>
                            </button>
                        </div>
                    </div>
                    <div class="workshop-card-info">
                        <div>
                            <div class="workshop-card-title" title="${safeTitle}">${safeTitle}</div>
                            <div class="workshop-card-author">by ${safeAuthor}</div>
                        </div>
                        <div class="workshop-card-stats">
                            <div class="workshop-stat-item ${isLiked ? 'liked' : ''}" data-like-id="${safeId}">
                                <i data-lucide="heart" style="width:14px;height:14px;${isLiked ? 'fill:#ef4444' : ''}"></i>
                                <span>${displayLikes}</span>
                            </div>
                            <div class="workshop-stat-item">
                                <i data-lucide="download" style="width:14px;height:14px"></i>
                                <span>${it.downloads}</span>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        renderIcons(grid);

        grid.querySelectorAll('.workshop-btn-apply').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const item = WORKSHOP_ITEMS.find(it => it.id === btn.dataset.id);
                if (!item) return;

                const blurVal = document.getElementById('slider-bg-blur')?.value || 0;
                const dimVal = document.getElementById('slider-bg-dim')?.value || 20;
                saveSetting('custom_bg_image', item.url, 'theme');
                saveSetting('bg_blur', blurVal, 'theme');
                saveSetting('bg_dim', dimVal, 'theme');
                saveSetting('resource_bg', true, 'optimization');
                const btnBg = document.querySelector('#opt-active-resources [data-resource="bg"]');
                if (btnBg) btnBg.classList.add('active');
                applyResourceToggle('bg', true);
                applyCustomBg(item.url, blurVal, dimVal);

                showToast(`Обои "${item.title}" применены!`, 'success');
                render();
            });
        });

        grid.querySelectorAll('.workshop-stat-item[data-like-id]').forEach(likeBtn => {
            likeBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const id = likeBtn.dataset.likeId || likeBtn.getAttribute('data-like-id');
                const isCurrentlyLiked = getLikedState(id);
                localStorage.setItem(`nedotify_ws_like_${id}`, isCurrentlyLiked ? '0' : '1');
                render();
            });
        });
    };

    refreshWorkshop = render;
    render();

    if (searchInput) {
        let searchTimer;
        searchInput.addEventListener('input', (e) => {
            searchQuery = e.target.value;
            clearTimeout(searchTimer);
            searchTimer = setTimeout(render, 150);
        });
    }

    if (sortSelect) {
        sortSelect.addEventListener('change', (e) => {
            sortMode = e.target.value;
            render();
        });
    }

    if (tagsContainer) {
        tagsContainer.querySelectorAll('.tag-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                tagsContainer.querySelectorAll('.tag-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                activeTag = btn.dataset.tag;
                render();
            });
        });
    }
}

function showDeleteDuplicateModal() {
    return new Promise((resolve) => {
        const modal = document.getElementById('modal-delete-duplicate');
        const btnConfirm = document.getElementById('modal-ddup-confirm');
        const btnCancel = document.getElementById('modal-ddup-cancel');
        if (!modal || !btnConfirm || !btnCancel) { resolve(window.confirm('Удалить дубликат из медиатеки и с диска?')); return; }

        modal.style.display = 'flex';
        // Scoped to the modal: only its own icons are (re)inserted on open.
        if (window.lucide) setTimeout(() => window.lucide.createIcons({ nameAttr: 'data-lucide', attrs: {}, root: modal }), 10);
        openModalFocusTrap(modal, { initialFocus: '#modal-ddup-cancel' });

        const close = (result) => {
            closeModalFocusTrap(modal);
            modal.style.display = 'none';
            btnConfirm.removeEventListener('click', onConfirm);
            btnCancel.removeEventListener('click', onCancel);
            modal.removeEventListener('click', onOverlay);
            document.removeEventListener('keydown', onKeydown, true);
            resolve(result);
        };

        const onConfirm = () => close(true);
        const onCancel = () => close(false);
        const onOverlay = (e) => { if (e.target === modal) close(false); };
        // Escape cancels, like the other confirm modals in the app.
        const onKeydown = (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(false); } };

        btnConfirm.addEventListener('click', onConfirm);
        btnCancel.addEventListener('click', onCancel);
        modal.addEventListener('click', onOverlay);
        document.addEventListener('keydown', onKeydown, true);
    });
}

function renderDuplicateGroups(groups, container) {
    if (!container) return;
    if (!groups || groups.length === 0) {
        container.innerHTML = '<div style="font-size:12px; color:rgba(255,255,255,0.7); background:rgba(255,255,255,0.04); padding:10px 14px; border-radius:8px; border:1px solid rgba(255,255,255,0.1);">✅ Дубликатов в вашей медиатеке не обнаружено!</div>';
        return;
    }

    container.innerHTML = '';
    groups.forEach((group, idx) => {
        const groupEl = document.createElement('div');
        groupEl.style.cssText = 'background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.1); border-radius:10px; padding:12px; margin-bottom:10px; font-size:12px;';
        
        let tracksHtml = '';
        group.tracks.forEach(track => {
            tracksHtml += `
                <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 0; border-bottom:1px dashed rgba(255,255,255,0.08);">
                    <div>
                        <div style="font-weight:600; color:#fff;">${escapeHtml(track.title || 'Unknown')}</div>
                        <div style="color:var(--text-sec); font-size:11px;">${escapeHtml(track.artist || 'Unknown')} • ${(track.file_size_bytes / (1024*1024)).toFixed(2)} MB</div>
                    </div>
                    <button class="btn-sm text-xs btn-delete-dup" data-id="${escapeHtml(String(track.id))}" style="padding:4px 8px; border-radius:6px; background:rgba(239,68,68,0.2); color:#ef4444; border:1px solid rgba(239,68,68,0.3); cursor:pointer;">Удалить</button>
                </div>
            `;
        });

        groupEl.innerHTML = `
            <div style="font-weight:700; color:var(--primary); margin-bottom:6px;">Группа дубликатов #${idx + 1} (Совпадение ${group.match_confidence}%)</div>
            ${tracksHtml}
        `;

        groupEl.querySelectorAll('.btn-delete-dup').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const trackId = parseInt(e.target.dataset.id);
                if (!trackId || !window.pywebview?.api?.delete_duplicate_track) return;
                const confirmed = await showDeleteDuplicateModal();
                if (!confirmed) return;
                try {
                    const res = await window.pywebview.api.delete_duplicate_track(trackId, true);
                    if (res && res.success === true) {
                        e.target.closest('div').remove();
                        showToast('Дубликат удалён', 'success');
                    } else {
                        showToast(`Не удалось удалить дубликат: ${(res && res.error) || 'неизвестная ошибка'}`, 'error');
                    }
                } catch (err) {
                    showToast('Ошибка при удалении дубликата', 'error');
                }
            });
        });

        container.appendChild(groupEl);
    });
}

export function initSettingsSearchFilter() {
    const input = document.getElementById('settings-search');
    if (!input) return;
    const rowSelector = '.setting-row, .setting-card-group, .custom-theme-box, .setting-item, .theme-card, .theme-mode-switcher, .font-cards-grid, .font-categories, .settings-background-shortcuts, .saved-custom-themes';
    const normalize = value => String(value || '').toLocaleLowerCase('ru');
    const root = document.getElementById('view-settings') || document;
    let index = null;
    const buildIndex = () => Array.from(root.querySelectorAll('.settings-panel'), panel => {
        const button = root.querySelector(`.settings-nav-btn[data-panel="${panel.id.replace('settings-', '')}"]`);
        const sections = Array.from(panel.querySelectorAll('.settings-section'), section => ({
            section,
            title: normalize(section.querySelector('.settings-section-title')?.textContent),
            text: normalize(section.textContent),
            rows: Array.from(section.querySelectorAll(rowSelector), row => ({
                row,
                text: normalize(`${row.textContent} ${Array.from(row.querySelectorAll('input,select,button'), el => `${el.placeholder || ''} ${el.getAttribute('aria-label') || ''} ${el.title || ''}`).join(' ')}`),
            })),
        }));
        return {panel, button, text: normalize(button?.textContent), sections};
    });
    if (root && typeof MutationObserver === 'function') {
        new MutationObserver(() => { index = null; }).observe(root, {childList: true, subtree: true});
    }
    const apply = () => {
        index ||= buildIndex();
        const query = normalize(input.value.trim());
        let first = null, currentMatches = false;
        for (const entry of index) {
            const nameMatch = !!query && entry.text.includes(query);
            let panelMatch = !query || nameMatch;
            for (const section of entry.sections) {
                const headingMatch = nameMatch || !!query && section.title.includes(query);
                let sectionMatch = !query || headingMatch;
                for (const item of section.rows) {
                    const match = !query || headingMatch || item.text.includes(query);
                    item.row.hidden = !match;
                    sectionMatch ||= match;
                }
                if (!section.rows.length) sectionMatch ||= section.text.includes(query);
                section.section.hidden = !sectionMatch;
                panelMatch ||= sectionMatch;
            }
            entry.panel.hidden = !panelMatch;
            if (entry.button) entry.button.hidden = !panelMatch;
            if (panelMatch && !first) first = entry.button;
            if (panelMatch && entry.panel.classList.contains('active')) currentMatches = true;
        }
        const empty = document.getElementById('settings-search-empty');
        if (empty) empty.hidden = !!first || !query;
        if (query && !currentMatches && first) first.click();
        if (!query) {
            const selected = root.querySelector('.settings-nav-btn.active') || root.querySelector('.settings-nav-btn');
            if (selected) for (const {panel} of index) {
                const active = panel.id === `settings-${selected.dataset.panel}`;
                panel.classList.toggle('active', active);
                panel.style.display = active ? 'block' : 'none';
            }
        }
    };
    let timer;
    input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(apply, 120); });
    input.addEventListener('keydown', event => {
        if (event.key === 'Escape' && input.value) {
            event.stopPropagation(); clearTimeout(timer); input.value = ''; apply();
        }
    });
}
