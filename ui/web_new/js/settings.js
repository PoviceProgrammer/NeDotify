// NeDotify Р Р†Р вЂљ" Settings Module
import { renderIcons, escapeHtml } from './utils.js?v=20260814_9';
import { initParticles, stopParticles, setParticlesFps } from './particles.js?v=20260814_9';
import { setVisualizerFps } from './visualizer.js?v=20260814_9';
import { initOnboarding } from './onboarding.js?v=20260814_9';
import { DEFAULT_KEYBINDS, activeKeybinds, setListeningKeybind, getListeningKeybindId } from './hotkeys.js?v=20260814_9';

// Helper: read a localStorage setting that was saved by saveSetting()
function getLocalSetting(key, defaultVal) {
    try {
        const raw = localStorage.getItem(key);
        if (raw === null || raw === undefined) return defaultVal;
        return JSON.parse(raw);
    } catch(e) {
        return defaultVal;
    }
}

const THEMES = [
    { id: 'amoled', name: 'AMOLED', colors: ['#ffffff', '#000000'] },
    { id: 'dark', name: 'Dark', colors: ['#ffffff', '#121212'] },
    { id: 'midnight', name: 'Midnight', colors: ['#3b82f6', '#0a0e17'] },
    { id: 'emerald', name: 'Emerald', colors: ['#10b981', '#0b1410'] },
    { id: 'sunset', name: 'Sunset', colors: ['#f97316', '#170c0a'] },
    { id: 'ocean', name: 'Ocean', colors: ['#06b6d4', '#06141a'] },
    { id: 'lavender', name: 'Lavender', colors: ['#a855f7', '#130b1c'] },
    { id: 'rose', name: 'Rose', colors: ['#ec4899', '#1a0b12'] },
    { id: 'amber', name: 'Amber', colors: ['#ff9f1c', '#1a120e'] },
    { id: 'slate', name: 'Slate', colors: ['#94a3b8', '#0f172a'] }
];

export function initSettings() {

    setupToggle('toggle-unfocus-enabled', 'unfocus_enabled', 'efficiency');
    setupToggle('toggle-unfocus-blur', 'unfocus_blur_reduction', 'efficiency');
    setupToggle('toggle-unfocus-animations', 'unfocus_disable_animations', 'efficiency');
    setupToggle('toggle-unfocus-visualizations', 'unfocus_disable_visualizations', 'efficiency');
    
    setupSlider('slider-unfocus-fps', 'unfocus_fps_limit', 'efficiency', (v) => {
        setElText('label-unfocus-fps', `${v} FPS`);
    });

    // Settings panel navigation
    document.querySelectorAll('.settings-nav-btn[data-panel]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const panelName = btn.dataset.panel;
            if (!panelName) return;

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

            if (panelName === 'icons') setupIconsPanel();
            if (panelName === 'workshop') setupWorkshopPanel();
            if (panelName === 'optimization') setupOptimizationPanel();

            try {
                if (window.lucide) window.lucide.createIcons();
            } catch(err) {}
        });
    });

    // Render theme grid & setup appearance handlers
    renderThemeGrid();
    setupAppearancePanel();
    setupPlayerSettingsPanel();
    setupBackgroundPanel();
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
    setupToggle('toggle-particles', 'particles_enabled', 'ui');
    setupToggle('toggle-visualizer', 'cover_visualizer', 'ui');

    setupSlider('slider-crossfade-sec', 'crossfade_sec', 'audio', (v) => {
        setElText('label-crossfade-sec', `${v} сек`);
    });

    // Sliders
    setupSlider('slider-particles-count', 'particles_count', 'ui', (v) => {
        setElText('label-particles-count', v);
        initParticles();
    });
    setupSlider('slider-particles-size', 'particles_size', 'ui', (v) => {
        const labels = { 1: 'Мелкий', 2: 'Обычный', 3: 'Средний', 4: 'Крупный', 5: 'Огромный' };
        setElText('label-particles-size', labels[v] || 'Обычный');
        initParticles();
    });
    setupSlider('slider-particles-speed', 'particles_speed', 'ui', (v) => {
        const labels = { 1: 'Медленная', 2: 'Обычная', 3: 'Быстрая' };
        setElText('label-particles-speed', labels[v] || 'Обычная');
        initParticles();
    });
    setupSlider('slider-glass-blur', 'glass_blur', 'theme', (v) => {
        setElText('label-glass-blur', `${v}px`);
        setElText('label-bg-blur', `${v}px`);
        const bgBlurSlider = document.getElementById('slider-bg-blur');
        if (bgBlurSlider) bgBlurSlider.value = v;
        document.documentElement.style.setProperty('--glass-blur', `${v}px`);
        document.documentElement.style.setProperty('--blur-sm', `${Math.max(4, Math.round(v * 0.4))}px`);
        const dataUrl = localStorage.getItem('nedotify_theme_custom_bg_image');
        const dimVal = document.getElementById('slider-bg-dim')?.value || 30;
        if (dataUrl) {
            try { applyCustomBg(JSON.parse(dataUrl), v, dimVal); } catch(e) {}
        }
    });

    // Font Selection Bindings
    const selectFont = document.getElementById('select-font-family');
    if (selectFont) {
        selectFont.addEventListener('change', (e) => {
            const fontVal = e.target.value;
            document.documentElement.style.setProperty('--font-family', fontVal);
            saveSetting('font_family', fontVal, 'theme');
        });
    }

    // Window Transparency Bindings
    const toggleTrans = document.getElementById('toggle-transparency');
    const sliderTrans = document.getElementById('slider-transparency-level');
    if (toggleTrans && sliderTrans) {
        toggleTrans.addEventListener('click', () => {
            const isOn = toggleTrans.classList.toggle('on');
            saveSetting('transparency_enabled', isOn, 'theme');
            sliderTrans.disabled = !isOn;
            applyTransparency(sliderTrans.value, isOn);
        });
    }
    setupSlider('slider-transparency-level', 'transparency_level', 'theme', (v) => {
        setElText('label-transparency-level', `${v}%`);
        applyTransparency(v, document.getElementById('toggle-transparency')?.classList.contains('on'));
    });

    // Discord Rich Presence Binding
    const toggleDiscordRpc = document.getElementById('toggle-discord-rpc');
    if (toggleDiscordRpc) {
        const savedDiscordRpc = localStorage.getItem('nedotify_app_discord_rpc_enabled');
        const initialEnabled = savedDiscordRpc !== null ? JSON.parse(savedDiscordRpc) : true;
        toggleDiscordRpc.classList.toggle('on', initialEnabled);

        toggleDiscordRpc.addEventListener('click', () => {
            const isOn = toggleDiscordRpc.classList.toggle('on');
            saveSetting('discord_rpc_enabled', isOn, 'app');
            if (window.pywebview?.api?.toggle_discord_rpc) {
                window.pywebview.api.toggle_discord_rpc(isOn);
            }
        });
    }

    // Particle shapes
    document.querySelectorAll('.particle-shape-btn[data-shape]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.particle-shape-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            saveSetting('particles_shape', btn.dataset.shape, 'ui');
            initParticles();
        });
    });

    // Storage
    const clearStorageBtn = document.getElementById('btn-clear-storage');
    if (clearStorageBtn) {
        clearStorageBtn.addEventListener('click', async () => {
            if (window.pywebview?.api) {
                await window.pywebview.api.clear_storage('all');
                window.pywebview.api.get_storage_info();
            }
        });
    }

    // Duplicate Scanner Binding
    const scanDuplicatesBtn = document.getElementById('btn-scan-duplicates');
    const duplicatesContainer = document.getElementById('duplicates-results-container');
    if (scanDuplicatesBtn && duplicatesContainer) {
        scanDuplicatesBtn.addEventListener('click', async () => {
            duplicatesContainer.innerHTML = '<div style="font-size:12px; color:var(--text-sec); display:flex; align-items:center; gap:8px;"><div class="spinner" style="width:14px;height:14px;"></div> Сканирование медиатеки на дубликаты...</div>';
            if (window.pywebview?.api?.find_duplicate_tracks) {
                const groups = await window.pywebview.api.find_duplicate_tracks();
                renderDuplicateGroups(groups, duplicatesContainer);
            } else {
                duplicatesContainer.innerHTML = '<div style="font-size:12px; color:var(--text-sec);">Сканирование недоступно</div>';
            }
        });
    }
    // Setup font size slider
    setupSlider('slider-font-size', 'font_size', 'theme', (val) => {
        applyFontSize(val);
    });

    const savedFontSize = localStorage.getItem('nedotify_theme_font_size');
    if (savedFontSize) {
        try { applyFontSize(JSON.parse(savedFontSize)); } catch(e) {}
    }

    const savedGlassBlur = localStorage.getItem('nedotify_theme_glass_blur');
    if (savedGlassBlur !== null) {
        try {
            const v = JSON.parse(savedGlassBlur);
            setElText('label-glass-blur', `${v}px`);
            document.documentElement.style.setProperty('--glass-blur', `${v}px`);
            const slider = document.getElementById('slider-glass-blur');
            if (slider) {
                slider.value = v;
                const pct = (v - slider.min) / (slider.max - slider.min) * 100;
                slider.style.setProperty('--value-percent', `${pct}%`);
            }
        } catch(e) {}
    }

    // Custom theme random button
    const btnRandom = document.getElementById('btn-random-theme');
    if (btnRandom) {
        btnRandom.addEventListener('click', () => {
            const rColor = () => '#' + Math.floor(Math.random() * 16777215).toString(16).padStart(6, '0');
            const p = rColor();
            const a = rColor();
            document.documentElement.style.setProperty('--primary', p);
            document.documentElement.style.setProperty('--accent', a);
            saveSetting('custom_primary', p, 'theme');
            saveSetting('custom_accent', a, 'theme');
        });
    }

    // Playlist Import
    const btnImport = document.getElementById('btn-import-playlist');
    const inputImportUrl = document.getElementById('input-import-playlist-url');
    const inputImportName = document.getElementById('input-import-playlist-name');
    const statusImport = document.getElementById('import-playlist-status');

    if (btnImport && inputImportUrl) {
        btnImport.addEventListener('click', () => {
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

            if (window.pywebview?.api?.import_external_playlist) {
                window.pywebview.api.import_external_playlist(url, name);
            }
            setTimeout(() => {
                btnImport.disabled = false;
                if (statusImport) statusImport.style.display = 'none';
                inputImportUrl.value = '';
                if (inputImportName) inputImportName.value = '';
            }, 4000);
        });
    }

    // Auth inputs/select bindings
    const inputYandexToken = document.getElementById('input-yandex-token');
    if (inputYandexToken) {
        inputYandexToken.addEventListener('change', (e) => {
            saveSetting('yandex_token', e.target.value, 'auth');
        });
    }
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
        selectRegion.addEventListener('change', (e) => {
            saveSetting('region', e.target.value, 'general');
        });
    }

    // Yandex Device Auth button
    const btnYandexAuth = document.getElementById('btn-yandex-auth');
    if (btnYandexAuth) {
        btnYandexAuth.addEventListener('click', () => {
            if (!window.pywebview?.api) return;
            const statusEl = document.getElementById('yandex-device-status');
            if (statusEl) {
                statusEl.style.display = 'block';
                statusEl.innerHTML = '⏳ Запрос кода авторизации...';
                statusEl.style.color = 'var(--text-sec)';
            }
            btnYandexAuth.disabled = true;
            if (window.pywebview && window.pywebview.api && window.pywebview.api.yandex_device_auth) {
                window.pywebview.api.yandex_device_auth().then(res => {
                    if (res && !res.success) {
                        if (statusEl) {
                            statusEl.style.display = 'none';
                        }
                        btnYandexAuth.disabled = false;
                        showToast(res.message || 'Ошибка авторизации Яндекс Музыки', 'error');
                    }
                }).catch(() => {
                    if (statusEl) {
                        statusEl.style.display = 'none';
                    }
                    btnYandexAuth.disabled = false;
                });
            } else {
                showToast('Функция пока недоступна (Yandex Auth)', 'info');
                if (statusEl) {
                    statusEl.style.display = 'none';
                }
                btnYandexAuth.disabled = false;
            }
        });

        document.addEventListener('nedotify:yandex_device_auth_code', (e) => {
            const statusEl = document.getElementById('yandex-device-status');
            const data = e.detail || {};
            if (statusEl) {
                statusEl.style.display = 'block';
                statusEl.innerHTML = `🔑 Код авторизации: <b style="color:var(--primary);font-weight:800;letter-spacing:2px;">${escapeHtml(data.user_code || '')}</b><br><span style="font-size:11px;">Откройте ${escapeHtml(data.verification_url || 'passport.yandex.ru/device')} и введите код</span>`;
                statusEl.style.color = 'var(--text-sec)';
            }
        });

        document.addEventListener('nedotify:yandex_device_auth_result', (e) => {
            const statusEl = document.getElementById('yandex-device-status');
            const data = e.detail || {};
            if (statusEl) {
                statusEl.style.display = 'block';
                statusEl.innerHTML = escapeHtml(data.message || '');
                statusEl.style.color = data.success ? 'var(--primary)' : 'var(--danger, #f87171)';
            }
            btnYandexAuth.disabled = false;
        });
    }

    initKeybinds();
}

const PRESET_THEMES = [
    { id: 'dark', name: 'Dark', colors: ['#121212', '#ffffff', '#1e1e1e'] },
    { id: 'amoled', name: 'AMOLED', colors: ['#000000', '#ffffff', '#27272a'] },
    { id: 'midnight', name: 'Midnight', colors: ['#0a0e17', '#3b82f6', '#101622'] },
    { id: 'sky', name: 'Sky', colors: ['#0c192c', '#38bdf8', '#0284c7'] },
    { id: 'mint', name: 'Mint', colors: ['#061a14', '#34d399', '#10b981'] },
    { id: 'violet', name: 'Violet', colors: ['#160c28', '#a855f7', '#8b5cf6'] },
    { id: 'blossom', name: 'Blossom', colors: ['#1f0b18', '#f43f5e', '#ec4899'] },
    { id: 'sakura', name: 'Sakura', colors: ['#1c0d15', '#fb7185', '#fda4af'] },
    { id: 'terminal', name: 'Terminal', colors: ['#051405', '#22c55e', '#4ade80'] },
    { id: 'sand', name: 'Sand', colors: ['#1c160c', '#f59e0b', '#fbbf24'] },
    { id: 'aqua', name: 'Aqua', colors: ['#081b24', '#06b6d4', '#22d3ee'] },
    { id: 'sunset', name: 'Sunset', colors: ['#1e100c', '#f97316', '#fb923c'] },
    { id: 'slate', name: 'Slate', colors: ['#0f172a', '#64748b', '#94a3b8'] },
    { id: 'neutral', name: 'Neutral', colors: ['#18181b', '#ffffff', '#71717a'] },
    { id: 'crimson', name: 'Crimson', colors: ['#1a0b0e', '#ef4444', '#f43f5e'] },
    { id: 'dracula', name: 'Dracula', colors: ['#1e1f29', '#ff79c6', '#bd93f9'] },
    { id: 'nord', name: 'Nord', colors: ['#2e3440', '#88c0d0', '#81a1c1'] },
    { id: 'rose', name: 'Rose', colors: ['#1a0b12', '#ec4899', '#f43f5e'] },
    { id: 'emerald', name: 'Emerald', colors: ['#0b1410', '#10b981', '#34d399'] },
    { id: 'amber', name: 'Amber', colors: ['#1a120e', '#ff9f1c', '#fbbf24'] },
    { id: 'lavender', name: 'Lavender', colors: ['#130b1c', '#a855f7', '#8b5cf6'] },
    { id: 'ocean', name: 'Ocean', colors: ['#06141a', '#06b6d4', '#0284c7'] }
];

const FONTS_LIST = [
    // System
    { id: 'default', name: 'Default', family: "'Inter', sans-serif", cat: 'system' },
    { id: 'inter', name: 'Inter', family: "'Inter', sans-serif", cat: 'system' },
    { id: 'arial', name: 'Arial', family: "Arial, sans-serif", cat: 'system' },
    { id: 'segoe_ui', name: 'Segoe UI', family: "'Segoe UI', sans-serif", cat: 'system' },
    { id: 'roboto', name: 'Roboto', family: "'Roboto', sans-serif", cat: 'system' },
    { id: 'helvetica', name: 'Helvetica Neue', family: "'Helvetica Neue', Arial, sans-serif", cat: 'system' },
    { id: 'tahoma', name: 'Tahoma', family: "Tahoma, sans-serif", cat: 'system' },
    { id: 'verdana', name: 'Verdana', family: "Verdana, sans-serif", cat: 'system' },
    { id: 'san_francisco', name: 'San Francisco', family: "-apple-system, BlinkMacSystemFont, sans-serif", cat: 'system' },
    { id: 'calibri', name: 'Calibri', family: "Calibri, sans-serif", cat: 'system' },
    { id: 'lucida', name: 'Lucida Sans', family: "'Lucida Sans', sans-serif", cat: 'system' },
    { id: 'arial_black', name: 'Arial Black', family: "'Arial Black', sans-serif", cat: 'system' },
    { id: 'arial_narrow', name: 'Arial Narrow', family: "'Arial Narrow', sans-serif", cat: 'system' },
    { id: 'segoe_light', name: 'Segoe UI Light', family: "'Segoe UI Light', 'Segoe UI', sans-serif", cat: 'system' },
    { id: 'segoe_semibold', name: 'Segoe UI Semibold', family: "'Segoe UI Semibold', 'Segoe UI', sans-serif", cat: 'system' },

    // Modern
    { id: 'outfit', name: 'Outfit', family: "'Outfit', sans-serif", cat: 'modern' },
    { id: 'montserrat', name: 'Montserrat', family: "'Montserrat', sans-serif", cat: 'modern' },
    { id: 'plus_jakarta', name: 'Plus Jakarta', family: "'Plus Jakarta Sans', sans-serif", cat: 'modern' },

    // Serif
    { id: 'georgia', name: 'Georgia', family: "Georgia, serif", cat: 'serif' },
    { id: 'times', name: 'Times New Roman', family: "'Times New Roman', serif", cat: 'serif' },
    { id: 'garamond', name: 'Garamond', family: "Garamond, serif", cat: 'serif' },

    // Mono
    { id: 'consolas', name: 'Consolas', family: "Consolas, monospace", cat: 'mono' },
    { id: 'courier', name: 'Courier New', family: "'Courier New', monospace", cat: 'mono' },
    { id: 'monaco', name: 'Monaco', family: "Monaco, monospace", cat: 'mono' },

    // Hand
    { id: 'cursive', name: 'Cursive', family: "cursive", cat: 'hand' },
    { id: 'comic_sans', name: 'Comic Sans', family: "'Comic Sans MS', cursive", cat: 'hand' },

    // Deco
    { id: 'impact', name: 'Impact', family: "Impact, fantasy", cat: 'deco' },
    { id: 'trebuchet', name: 'Trebuchet MS', family: "'Trebuchet MS', sans-serif", cat: 'deco' },

    // Game
    { id: 'press_start', name: '8-Bit Retro', family: "'Courier New', monospace", cat: 'game' },
    { id: 'copperplate', name: 'Copperplate', family: "Copperplate, fantasy", cat: 'game' }
];

function renderThemePresets() {
    const container = document.getElementById('theme-presets-grid');
    if (!container) return;

    const currentTheme = document.documentElement.getAttribute('data-theme') || 'sand';

    container.innerHTML = '';
    PRESET_THEMES.forEach(t => {
        const card = document.createElement('div');
        const isActive = t.id === currentTheme;
        card.className = `theme-card${isActive ? ' active' : ''}`;
        card.dataset.theme = t.id;
        card.innerHTML = `
            ${isActive ? '<div class="theme-card-badge">✓</div>' : ''}
            <div class="theme-dots-row">
                <div class="theme-dot" style="background:${t.colors[0]}"></div>
                <div class="theme-dot" style="background:${t.colors[1]}"></div>
                <div class="theme-dot" style="background:${t.colors[2]}"></div>
            </div>
            <span class="theme-card-name">${t.name}</span>
        `;
        card.addEventListener('click', () => {
            container.querySelectorAll('.theme-card').forEach(c => {
                c.classList.remove('active');
                const badge = c.querySelector('.theme-card-badge');
                if (badge) badge.remove();
            });
            card.classList.add('active');
            const badge = document.createElement('div');
            badge.className = 'theme-card-badge';
            badge.textContent = '✓';
            card.appendChild(badge);

            document.documentElement.setAttribute('data-theme', t.id);
            saveSetting('theme', t.id, 'ui');
        });
        container.appendChild(card);
    });
}

function renderFontCards(activeCat = 'system') {
    const container = document.getElementById('font-cards-grid');
    if (!container) return;

    const currentFont = getComputedStyle(document.documentElement).getPropertyValue('--font-family').trim() || "'Inter', sans-serif";

    container.innerHTML = '';
    const filteredFonts = FONTS_LIST.filter(f => f.cat === activeCat || activeCat === 'all');
    filteredFonts.forEach(f => {
        const card = document.createElement('div');
        const isActive = currentFont.includes(f.name) || (f.id === 'default' && (currentFont.includes('Inter') || currentFont === ''));
        card.className = `font-card${isActive ? ' active' : ''}`;
        card.dataset.font = f.family;
        card.innerHTML = `
            <div class="font-preview-letters" style="font-family:${f.family}">Aa</div>
            <span class="font-card-name">${f.name}</span>
        `;
        card.addEventListener('click', () => {
            container.querySelectorAll('.font-card').forEach(c => c.classList.remove('active'));
            card.classList.add('active');
            document.documentElement.style.setProperty('--font-family', f.family);
            saveSetting('font_family', f.family, 'theme');
        });
        container.appendChild(card);
    });
}

function renderThemeGrid() {
    renderThemePresets();
    renderFontCards('system');
}

function setupToggle(id, key, category, onChange) {
    const toggle = document.getElementById(id);
    if (!toggle) return;

    toggle.addEventListener('click', () => {
        const isOn = toggle.classList.toggle('on');
        saveSetting(key, isOn, category);
        
        if (onChange) onChange(isOn);

        // Apply immediately
        if (key === 'particles_enabled') {
            if (window.settings && window.settings.ui) window.settings.ui.particles_enabled = isOn;
            if (isOn) {
                initParticles();
            } else {
                stopParticles();
            }
        }
        if (key === 'cover_visualizer') {
            const canvas = document.getElementById('visualizer-canvas');
            if (canvas) canvas.style.display = isOn ? 'block' : 'none';
        }
    });
}

function setupSlider(id, key, category, onChange) {
    const slider = document.getElementById(id);
    if (!slider) return;

    const updatePercent = (val) => {
        const pct = (val - slider.min) / (slider.max - slider.min) * 100;
        slider.style.setProperty('--value-percent', `${pct}%`);
    };
    updatePercent(slider.value);

    slider.addEventListener('input', (e) => {
        updatePercent(e.target.value);
        if (onChange) onChange(e.target.value);
    });
    slider.addEventListener('change', (e) => {
        saveSetting(key, parseInt(e.target.value), category);
    });
}

export function applySettingsFromBackend(settings) {
    if (!settings) return;

    if (settings.ui) {
        if (settings.ui.theme) {
            document.documentElement.setAttribute('data-theme', settings.ui.theme);
            // Update grid
            document.querySelectorAll('.theme-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.theme === settings.ui.theme);
            });
        }
        if (settings.ui.particles_enabled !== undefined) {
            const toggle = document.getElementById('toggle-particles');
            if (toggle) toggle.classList.toggle('on', !!settings.ui.particles_enabled);
            if (settings.ui.particles_enabled) {
                initParticles();
            } else {
                stopParticles();
            }
        }
        if (settings.ui.cover_visualizer !== undefined) {
            const toggle = document.getElementById('toggle-visualizer');
            if (toggle) toggle.classList.toggle('on', settings.ui.cover_visualizer);
        }
        if (settings.ui.particles_count !== undefined) {
            const slider = document.getElementById('slider-particles-count');
            if (slider) {
                slider.value = settings.ui.particles_count;
                const pct = (slider.value - slider.min) / (slider.max - slider.min) * 100;
                slider.style.setProperty('--value-percent', `${pct}%`);
            }
            setElText('label-particles-count', settings.ui.particles_count);
        }
        if (settings.ui.particles_shape) {
            document.querySelectorAll('.particle-shape-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.shape === settings.ui.particles_shape);
            });
        }
    }

        if (settings.theme && settings.theme.glass_blur !== undefined) {
            const slider = document.getElementById('slider-glass-blur');
            if (slider) {
                slider.value = settings.theme.glass_blur;
                const pct = (slider.value - slider.min) / (slider.max - slider.min) * 100;
                slider.style.setProperty('--value-percent', `${pct}%`);
            }
            setElText('label-glass-blur', `${settings.theme.glass_blur}px`);
            document.documentElement.style.setProperty('--glass-blur', `${settings.theme.glass_blur}px`);
        }

        if (settings.theme && settings.theme.font_family !== undefined) {
            const selectFont = document.getElementById('select-font-family');
            document.documentElement.style.setProperty('--font-family', settings.theme.font_family);
        }

        if (settings.theme) {
            if (settings.theme.transparency_enabled !== undefined) {
                const toggle = document.getElementById('toggle-transparency');
                if (toggle) toggle.classList.toggle('on', settings.theme.transparency_enabled);
            }
            if (settings.theme.transparency_level !== undefined) {
                const slider = document.getElementById('slider-transparency-level');
                if (slider) {
                    slider.value = settings.theme.transparency_level;
                    const pct = (slider.value - slider.min) / (slider.max - slider.min) * 100;
                    slider.style.setProperty('--value-percent', `${pct}%`);
                }
                setElText('label-transparency-level', `${settings.theme.transparency_level}%`);
            }
            const enabled = !!settings.theme.transparency_enabled;
            const level = settings.theme.transparency_level !== undefined ? settings.theme.transparency_level : 80;
            applyTransparency(level, enabled);
            if (settings.theme.font_size !== undefined) {
                applyFontSize(settings.theme.font_size);
            }
            if (settings.theme.icon_pack) {
                applyIconPack(settings.theme.icon_pack);
            }
            if (settings.theme.custom_bg_image !== undefined) {
                const blur = settings.theme.bg_blur !== undefined ? settings.theme.bg_blur : 0;
                const dim = settings.theme.bg_dim !== undefined ? settings.theme.bg_dim : 30;
                // Also update localStorage so instant restore on boot works perfectly
                try {
                    localStorage.setItem('nedotify_theme_custom_bg_image', JSON.stringify(settings.theme.custom_bg_image));
                    localStorage.setItem('nedotify_theme_bg_blur', JSON.stringify(blur));
                    localStorage.setItem('nedotify_theme_bg_dim', JSON.stringify(dim));
                } catch(e) {}
                applyCustomBg(settings.theme.custom_bg_image, blur, dim);
            }
        }

    if (settings.ui && settings.ui.particles_size !== undefined) {
        const slider = document.getElementById('slider-particles-size');
        if (slider) {
            slider.value = settings.ui.particles_size;
            const pct = (slider.value - slider.min) / (slider.max - slider.min) * 100;
            slider.style.setProperty('--value-percent', `${pct}%`);
        }
        const labels = { 1: 'Мелкий', 2: 'Обычный', 3: 'Средний', 4: 'Крупный', 5: 'Огромный' };
        setElText('label-particles-size', labels[settings.ui.particles_size] || 'Обычный');
    }

    if (settings.audio) {
        const toggleCF = document.getElementById('toggle-crossfade');
        if (toggleCF) toggleCF.classList.toggle('on', !!settings.audio.crossfade_enabled);
        const toggleGL = document.getElementById('toggle-gapless');
        if (toggleGL) toggleGL.classList.toggle('on', settings.audio.gapless_playback !== false);
        const toggleAP = document.getElementById('toggle-autoplay');
        if (toggleAP) toggleAP.classList.toggle('on', !!settings.audio.autoplay);
    }

    if (settings.general) {
        const selectRegion = document.getElementById('select-region');
        if (selectRegion && settings.general.region !== undefined) {
            selectRegion.value = settings.general.region;
        }
    }

    if (settings.optimization) {
        if (settings.optimization.performance_preset) applyPerformancePreset(settings.optimization.performance_preset, true);
        if (settings.optimization.blur_quality) applyBlurQuality(settings.optimization.blur_quality);
        if (settings.optimization.glow_quality) applyGlowSettings(settings.optimization.glow_quality);
        if (settings.optimization.fps_particles !== undefined) setParticlesFps(settings.optimization.fps_particles);
        if (settings.optimization.fps_visualizer !== undefined) setVisualizerFps(settings.optimization.fps_visualizer);
    }

    if (settings.player) {
        if (settings.player.title_align) applyTitleAlignment(settings.player.title_align);
        if (settings.player.player_style) applyPlayerStyle(settings.player.player_style);
        if (settings.player.slider_type) applySliderType(settings.player.slider_type);
        if (settings.player.show_queue !== undefined) applyShowQueue(settings.player.show_queue);
        if (settings.player.queue_pos) applyQueuePosition(settings.player.queue_pos);
        if (settings.player.compact_queue_btn !== undefined) applyCompactQueueBtn(settings.player.compact_queue_btn);
        if (settings.player.next_track_preview !== undefined) applyNextTrackPreview(settings.player.next_track_preview);
        if (settings.player.queue_view) applyQueueViewMode(settings.player.queue_view);
        if (settings.player.mp_progress) applyMpProgress(settings.player.mp_progress);
        if (settings.player.mp_cover_shape) applyMpCoverShape(settings.player.mp_cover_shape);
        if (settings.player.mp_shape) applyMpShape(settings.player.mp_shape);
        if (settings.player.mp_pos) applyMpPos(settings.player.mp_pos);
    }

    if (settings.auth) {
        const inputYandexToken = document.getElementById('input-yandex-token');
        if (inputYandexToken && settings.auth.yandex_token !== undefined) {
            inputYandexToken.value = settings.auth.yandex_token;
        }
        const selectBrowserCookies = document.getElementById('select-browser-cookies');
        if (selectBrowserCookies && settings.auth.browser_cookies !== undefined) {
            selectBrowserCookies.value = settings.auth.browser_cookies;
        }
        const inputCookiesPath = document.getElementById('input-cookies-path');
        if (inputCookiesPath && settings.auth.cookies_file_path !== undefined) {
            inputCookiesPath.value = settings.auth.cookies_file_path;
        }
        const inputProxyUrl = document.getElementById('input-proxy-url');
        if (inputProxyUrl && settings.auth.proxy_url !== undefined) {
            inputProxyUrl.value = settings.auth.proxy_url;
        }
        
        const inputOauthClientId = document.getElementById('input-oauth-client-id');
        if (inputOauthClientId && settings.auth.oauth_client_id !== undefined) {
            inputOauthClientId.value = settings.auth.oauth_client_id;
        }
        
        // SECURITY WARNING: OAuth client secret must not be stored or transmitted in frontend.
        // Use PKCE flow or backend token exchange.
        const inputOauthClientSecret = document.getElementById('input-oauth-client-secret');
        if (inputOauthClientSecret && settings.auth.oauth_client_secret !== undefined) {
            inputOauthClientSecret.value = settings.auth.oauth_client_secret;
        }
        
        if (settings.auth.oauth_completed) {
            const btnYtmusicOauth = document.getElementById('btn-ytmusic-oauth');
            if (btnYtmusicOauth) {
                btnYtmusicOauth.textContent = '✅ Привязано';
                btnYtmusicOauth.style.background = 'var(--success, #10b981)';
            }
        }
        
        setYandexWarning(!!settings.auth.yandex_auth_error);
    }
}

export function setYandexWarning(visible) {
    const warning = document.getElementById('yandex-auth-warning');
    if (warning) {
        warning.style.display = visible ? 'flex' : 'none';
        renderIcons();
    }
}

export function onStorageInfo(data) {
    if (!data) return;
    setElText('storage-total', `${(data.total || 0).toFixed(1)} MB`);
    if (data.tracks) setElText('storage-tracks', `${data.tracks.count} файлов • ${data.tracks.size}`);
    if (data.covers) setElText('storage-covers', `${data.covers.count} файлов • ${data.covers.size}`);
}

function saveSetting(key, value, category) {
    if (window.settings && category) {
        if (!window.settings[category]) window.settings[category] = {};
        window.settings[category][key] = value;
    }
    try {
        localStorage.setItem(`nedotify_${category}_${key}`, JSON.stringify(value));
    } catch (e) {}
    if (window.pywebview && window.pywebview.api && window.pywebview.api.save_setting) {
        window.pywebview.api.save_setting(key, value, category);
    }
}

function setElText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

export function loadSettings() {
    if (window.pywebview?.api) {
        window.pywebview.api.get_storage_info();
    }
}

export function applyTransparency(level, enabled) {
    const opacity = enabled ? (level / 100) : 1.0;
    document.documentElement.style.setProperty('--app-bg-opacity', opacity);
    const slider = document.getElementById('slider-transparency-level');
    if (slider) slider.disabled = !enabled;
}

export function applyFontSize(val) {
    const size = parseInt(val) || 16;
    const scale = size / 16;
    setElText('label-font-size', `${size}px`);
    document.documentElement.style.fontSize = `${size}px`;
    document.documentElement.style.setProperty('--font-size-base', `${size}px`);
    document.documentElement.style.setProperty('--app-font-scale', scale);

    const slider = document.getElementById('slider-font-size');
    if (slider) {
        slider.value = size;
        const pct = (slider.value - slider.min) / (slider.max - slider.min) * 100;
        slider.style.setProperty('--value-percent', `${pct}%`);
    }
}


export function initKeybinds() {
    window.renderKeybindsList = renderKeybindsList;
    renderKeybindsList();

    const resetBtn = document.getElementById('btn-reset-keybinds');
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            DEFAULT_KEYBINDS.forEach(kb => {
                activeKeybinds[kb.id] = kb.defaultKey;
                saveSetting(kb.id, kb.defaultKey, 'keybinds');
            });
            setListeningKeybind(null);
            renderKeybindsList();
            window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Горячие клавиши сброшены!', type: 'info' } }));
        });
    }
}

function triggerKeybindAction(actionId) {
    switch(actionId) {
        case 'play_pause':
            document.getElementById('pb-btn-play')?.click();
            break;
        case 'next_track':
            document.getElementById('pb-btn-next')?.click();
            break;
        case 'prev_track':
            document.getElementById('pb-btn-prev')?.click();
            break;
        case 'volume_up':
            window.NeDotify?.adjustVolume?.(5);
            break;
        case 'volume_down':
            window.NeDotify?.adjustVolume?.(-5);
            break;
        case 'toggle_mute':
            document.getElementById('pb-volume-btn')?.click();
            break;
        case 'toggle_lyrics':
            document.getElementById('pp-btn-lyrics')?.click();
            break;
        case 'toggle_mini':
            document.getElementById('btn-mini-player')?.click();
            break;
    }
}

function formatKeyName(code) {
    if (!code) return 'Не назначено';
    const translations = {
        'Space': 'Пробел',
        'ArrowRight': 'Стрелка Вправо',
        'ArrowLeft': 'Стрелка Влево',
        'ArrowUp': 'Стрелка Вверх',
        'ArrowDown': 'Стрелка Вниз',
        'MediaTrackNext': 'Медиа Вперед',
        'MediaTrackPrevious': 'Медиа Назад',
        'MediaPlayPause': 'Медиа Пауза',
        'Enter': 'Ввод (Enter)',
        'Tab': 'Таб (Tab)',
        'Backspace': 'Стирание (Backspace)',
        'Delete': 'Удалить (Delete)',
        'ControlLeft': 'Левый Ctrl',
        'ControlRight': 'Правый Ctrl',
        'ShiftLeft': 'Левый Shift',
        'ShiftRight': 'Правый Shift',
        'AltLeft': 'Левый Alt',
        'AltRight': 'Правый Alt',
        'BracketLeft': 'Скобка [',
        'BracketRight': 'Скобка ]',
        'Semicolon': 'Точка с запятой ;',
        'Quote': 'Кавычка \'',
        'Comma': 'Запятая ,',
        'Period': 'Точка .',
        'Slash': 'Слэш /',
        'Backslash': 'Обратный слэш \\',
        'Minus': 'Минус -',
        'Equal': 'Равно ='
    };
    if (translations[code]) return translations[code];
    if (code.startsWith('Key')) return `Клавиша ${code.replace('Key', '')}`;
    if (code.startsWith('Digit')) return `Цифра ${code.replace('Digit', '')}`;
    if (code.startsWith('Numpad')) return `Нумпад ${code.replace('Numpad', '')}`;
    return code;
}

function renderKeybindsList() {
    const listEl = document.getElementById('keybinds-list');
    if (!listEl) return;
    listEl.innerHTML = '';

    DEFAULT_KEYBINDS.forEach(kb => {
        const row = document.createElement('div');
        row.className = 'setting-row';
        row.style.display = 'flex';
        row.style.justifyContent = 'space-between';
        row.style.alignItems = 'center';
        
        const isListening = getListeningKeybindId() === kb.id;
        const rawKey = activeKeybinds[kb.id] || kb.defaultKey;
        const currentKeyDisplay = formatKeyName(rawKey);

        row.innerHTML = `
            <div>
                <div class="setting-label">${kb.label}</div>
            </div>
            <button class="filter-btn keybind-record-btn ${isListening ? 'active' : ''}" style="min-width: 140px; font-size: 13px;">
                ${isListening ? 'Нажмите клавишу...' : currentKeyDisplay}
            </button>
        `;

        const btn = row.querySelector('.keybind-record-btn');
        btn.addEventListener('click', () => {
            if (getListeningKeybindId() === kb.id) {
                setListeningKeybind(null);
            } else {
                setListeningKeybind(kb.id);
            }
            renderKeybindsList();
        });

        listEl.appendChild(row);
    });
}

// --- Exported so applySettingsFromBackend can restore preset on load ---
export function applyPerformancePreset(preset, skipSave = false) {
    const root = document.documentElement;
    root.classList.remove('perf-medium', 'perf-low');

    document.querySelectorAll('#opt-perf-preset .opt-card').forEach(c => {
        c.classList.toggle('active', c.dataset.val === preset);
    });

    if (preset === 'medium') {
        root.classList.add('perf-medium');
        _setSlidersForPreset(20, 18);
    } else if (preset === 'low') {
        root.classList.add('perf-low');
        _setSlidersForPreset(15, 12);
    } else {
        _setSlidersForPreset(30, 24);
    }

    if (!skipSave) {
        saveSetting('performance_preset', preset, 'optimization');
    }
    applyAuraOrbs(getLocalSetting('nedotify_player_aura_orbs_enabled', true));
}

function _setSlidersForPreset(vizFps, particlesFps) {
    const sv = document.getElementById('slider-fps-visualizer');
    if (sv) {
        sv.value = vizFps;
        setElText('label-fps-visualizer', `${vizFps} FPS`);
        setVisualizerFps(vizFps);
    }
    const sp = document.getElementById('slider-fps-particles');
    if (sp) {
        sp.value = particlesFps;
        setElText('label-fps-particles', `${particlesFps} FPS`);
        setParticlesFps(particlesFps);
    }
}

function applyBlurQuality(val) {
    const map = { hq: { sm: '8px',  md: '14px', lg: '18px', xl: '24px', glass: '10px' },
                  mid: { sm: '4px', md: '8px',  lg: '10px', xl: '12px', glass: '6px'  },
                  fast:{ sm: '2px', md: '4px',  lg: '6px',  xl: '8px',  glass: '4px'  },
                  off: { sm: '0px', md: '0px',  lg: '0px',  xl: '0px',  glass: '0px'  } };
    const v = map[val] || map.hq;
    const root = document.documentElement;
    root.style.setProperty('--blur-sm',   v.sm);
    root.style.setProperty('--blur-md',   v.md);
    root.style.setProperty('--blur-lg',   v.lg);
    root.style.setProperty('--blur-xl',   v.xl);
    // Only update --glass-blur if not overridden by user's manual slider
    const glassSlider = document.getElementById('slider-glass-blur');
    if (!glassSlider || glassSlider.dataset.userSet !== '1') {
        root.style.setProperty('--glass-blur', v.glass);
        if (glassSlider) {
            glassSlider.value = parseInt(v.glass);
            const pct = (glassSlider.value - glassSlider.min) / (glassSlider.max - glassSlider.min) * 100;
            glassSlider.style.setProperty('--value-percent', `${pct}%`);
            setElText('label-glass-blur', v.glass);
        }
    }
}

function applyGlowSettings(val) {
    const map = { full: { blur: '40px', opacity: '0.55' },
                  soft: { blur: '22px', opacity: '0.35' },
                  off:  { blur:  '0px', opacity:  '0'   } };
    const v = map[val] || map.full;
    document.documentElement.style.setProperty('--player-glow-blur',    v.blur);
    document.documentElement.style.setProperty('--player-glow-opacity', v.opacity);
}

function setupOptimizationPanel() {
    const setupCardGroup = (containerId, settingKey, onChange) => {
        const container = document.getElementById(containerId);
        if (!container) return;
        container.querySelectorAll('.opt-card').forEach(card => {
            card.addEventListener('click', () => {
                container.querySelectorAll('.opt-card').forEach(c => c.classList.remove('active'));
                card.classList.add('active');
                saveSetting(settingKey, card.dataset.val, 'optimization');
                if (onChange) onChange(card.dataset.val);
            });
        });
    };

    // 1. Presets
    setupCardGroup('opt-perf-preset', 'performance_preset', applyPerformancePreset);

    // 2. Limit state
    setupCardGroup('opt-limit-state', 'limit_state', (val) => {
        const root = document.documentElement;
        root.classList.remove('limit-state-off', 'limit-state-minimize', 'limit-state-focus');
        root.classList.add(`limit-state-${val}`);
    });

    // 3. Blur Quality
    setupCardGroup('opt-blur-quality', 'blur_quality', applyBlurQuality);

    // 4. Ambient Glow
    setupCardGroup('opt-glow-quality', 'glow_quality', applyGlowSettings);

    // 5. Active resource toggles
    const resourceContainer = document.getElementById('opt-active-resources');
    if (resourceContainer) {
        resourceContainer.querySelectorAll('.opt-toggle-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const isActive = btn.classList.toggle('active');
                const res = btn.dataset.resource;
                saveSetting(`resource_${res}`, isActive, 'optimization');

                if (res === 'particles') {
                    if (isActive) initParticles(); else stopParticles();
                }
                if (res === 'visualizers') {
                    const canvases = ['visualizer-canvas', 'home-visualizer-canvas'];
                    canvases.forEach(id => {
                        const c = document.getElementById(id);
                        if (c) c.style.display = isActive ? '' : 'none';
                    });
                }
                if (res === 'blur') {
                    applyBlurQuality(isActive ? 'hq' : 'off');
                }
                if (res === 'glow') {
                    applyGlowSettings(isActive ? 'full' : 'off');
                }
            });
        });
    }

    // 6. FPS Sliders
    setupSlider('slider-fps-particles', 'fps_particles', 'optimization', (v) => {
        setElText('label-fps-particles', `${v} FPS`);
        setParticlesFps(v);
    });
    setupSlider('slider-fps-visualizer', 'fps_visualizer', 'optimization', (v) => {
        setElText('label-fps-visualizer', `${v} FPS`);
        setVisualizerFps(v);
    });
    setupSlider('slider-fps-ui', 'fps_ui', 'optimization', (v) => {
        setElText('label-fps-ui', `${v} FPS`);
    });

    // 7. Glass blur listener
    const glassSlider = document.getElementById('slider-glass-blur');
    if (glassSlider) {
        glassSlider.addEventListener('mousedown', () => { glassSlider.dataset.userSet = '1'; });
    }

    // 8. Restore all saved optimization settings from localStorage
    try {
        const preset = getLocalSetting('nedotify_optimization_performance_preset', 'high');
        const limitState = getLocalSetting('nedotify_optimization_limit_state', 'minimize');
        const blur = getLocalSetting('nedotify_optimization_blur_quality', 'hq');
        const glow = getLocalSetting('nedotify_optimization_glow_quality', 'full');
        const fpsPart = getLocalSetting('nedotify_optimization_fps_particles', 24);
        const fpsViz = getLocalSetting('nedotify_optimization_fps_visualizer', 30);
        const fpsUi = getLocalSetting('nedotify_optimization_fps_ui', 60);

        const syncGroup = (containerId, val) => {
            const container = document.getElementById(containerId);
            if (container) {
                container.querySelectorAll('.opt-card').forEach(c => {
                    c.classList.toggle('active', c.dataset.val === val);
                });
            }
        };

        syncGroup('opt-perf-preset', preset);
        syncGroup('opt-limit-state', limitState);
        syncGroup('opt-blur-quality', blur);
        syncGroup('opt-glow-quality', glow);

        applyPerformancePreset(preset, true);
        const root = document.documentElement;
        root.classList.remove('limit-state-off', 'limit-state-minimize', 'limit-state-focus');
        root.classList.add(`limit-state-${limitState}`);

        applyBlurQuality(blur);
        applyGlowSettings(glow);

        const sp = document.getElementById('slider-fps-particles');
        if (sp) { sp.value = fpsPart; setElText('label-fps-particles', `${fpsPart} FPS`); setParticlesFps(fpsPart); }

        const sv = document.getElementById('slider-fps-visualizer');
        if (sv) { sv.value = fpsViz; setElText('label-fps-visualizer', `${fpsViz} FPS`); setVisualizerFps(fpsViz); }

        const su = document.getElementById('slider-fps-ui');
        if (su) { su.value = fpsUi; setElText('label-fps-ui', `${fpsUi} FPS`); }

        // Sync resource toggle buttons
        ['bg', 'particles', 'covers', 'visualizers', 'blur'].forEach(res => {
            const val = getLocalSetting(`nedotify_optimization_resource_${res}`, true);
            const btn = document.querySelector(`#opt-active-resources [data-resource="${res}"]`);
            if (btn) btn.classList.toggle('active', !!val);
        });
    } catch(e) {}
}

function setupAppearancePanel() {
    // 1. Theme Mode Switcher (Dark, Light, System)
    document.querySelectorAll('.theme-mode-btn[data-mode]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.theme-mode-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const mode = btn.dataset.mode;
            saveSetting('theme_mode', mode, 'theme');
            applyThemeMode(mode);
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
                saveSetting(item.id.replace('picker-color-', 'color_'), val, 'theme');
            });
        }
    });

    // Random Theme Palette Generator
    const btnRandom = document.getElementById('btn-random-theme');
    if (btnRandom) {
        btnRandom.addEventListener('click', () => {
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
            });
            window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Палитра случайно сгенерирована!', type: 'info' } }));
        });
    }

    // Save Custom Theme
    const btnSaveCustom = document.getElementById('btn-save-custom-theme');
    const inputThemeName = document.getElementById('input-custom-theme-name');
    if (btnSaveCustom) {
        btnSaveCustom.addEventListener('click', () => {
            const name = (inputThemeName?.value || 'Моя тема').trim();
            const palette = {};
            colorPickers.forEach(item => {
                const el = document.getElementById(item.id);
                if (el) palette[item.prop] = el.value;
            });
            const saved = JSON.parse(localStorage.getItem('nedotify_custom_themes') || '[]');
            saved.push({ name, palette, date: Date.now() });
            localStorage.setItem('nedotify_custom_themes', JSON.stringify(saved));
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
        btnExportFont.addEventListener('click', () => {
            const fontVal = getComputedStyle(document.documentElement).getPropertyValue('--font-family').trim();
            const fontSize = getComputedStyle(document.documentElement).fontSize;
            const configStr = `font-family: ${fontVal}; font-size: ${fontSize};`;
            if (navigator.clipboard) {
                navigator.clipboard.writeText(configStr);
            }
            window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Конфигурация шрифта скопирована в буфер!', type: 'success' } }));
        });
    }
}

function applyThemeMode(mode) {
    if (mode === 'system') {
        const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
    } else {
        document.documentElement.setAttribute('data-theme', mode);
    }
    applyAuraOrbs(getLocalSetting('nedotify_player_aura_orbs_enabled', true));
}

function setupZapretPanel() {
    const toggleZapret = document.getElementById('toggle-zapret-enabled');
    const selectZapretMode = document.getElementById('select-zapret-mode');
    const toggleAutoUpdate = document.getElementById('toggle-zapret-autoupdate');
    const btnUpdateZapret = document.getElementById('btn-update-zapret');
    const versionBadge = document.getElementById('zapret-version-badge');
    const updateStatus = document.getElementById('zapret-update-status');

    let selectedMode = 'youtube_discord';
    let savedCustomArgs = '';
    let savedBinaryPath = '';

    if (selectZapretMode) {
        selectZapretMode.addEventListener('change', (e) => {
            selectedMode = e.target.value;
            if (toggleZapret && toggleZapret.classList.contains('on')) {
                applyZapret(true);
            }
        });
    }

    if (toggleAutoUpdate) {
        toggleAutoUpdate.addEventListener('click', () => {
            const isOn = toggleAutoUpdate.classList.toggle('on');
            if (window.pywebview?.api?.set_setting) {
                window.pywebview.api.set_setting('zapret', 'autoupdate', isOn);
            }
        });
    }

    if (btnUpdateZapret) {
        btnUpdateZapret.addEventListener('click', async () => {
            btnUpdateZapret.disabled = true;
            btnUpdateZapret.style.opacity = '0.6';
            if (updateStatus) updateStatus.textContent = 'Проверка и загрузка актуальной версии...';

            try {
                if (window.pywebview?.api?.update_zapret) {
                    const res = await window.pywebview.api.update_zapret(true);
                    if (res?.success) {
                        if (versionBadge && res.status?.version) versionBadge.textContent = res.status.version;
                        if (updateStatus) updateStatus.textContent = 'Установлена последняя версия';
                        window.dispatchEvent(new CustomEvent('nedotify:toast', {
                            detail: { msg: res.message || 'Zapret успешно обновлен!', type: 'success' }
                        }));
                    } else {
                        if (updateStatus) updateStatus.textContent = 'Ошибка проверки обновления';
                        window.dispatchEvent(new CustomEvent('nedotify:toast', {
                            detail: { msg: res.message || 'Не удалось обновить Zapret', type: 'error' }
                        }));
                    }
                }
            } catch (err) {
                if (updateStatus) updateStatus.textContent = 'Ошибка сети при обновлении';
            } finally {
                btnUpdateZapret.disabled = false;
                btnUpdateZapret.style.opacity = '1';
            }
        });
    }

    async function applyZapret(enable) {
        const customArgs = savedCustomArgs || '';
        const binPath = savedBinaryPath || '';

        if (window.pywebview?.api?.toggle_zapret) {
            const res = await window.pywebview.api.toggle_zapret(enable, selectedMode, customArgs, binPath);
            if (res) {
                if (enable && !res.success) {
                    if (toggleZapret) toggleZapret.classList.remove('on');
                    window.dispatchEvent(new CustomEvent('nedotify:toast', {
                        detail: { msg: res.message || res.error || 'Не удалось запустить winws.exe. Проверьте права администратора.', type: 'warning' }
                    }));
                } else if (enable) {
                    window.dispatchEvent(new CustomEvent('nedotify:toast', {
                        detail: { msg: res.message || 'Zapret (Обход DPI) успешно включен!', type: 'success' }
                    }));
                } else {
                    window.dispatchEvent(new CustomEvent('nedotify:toast', {
                        detail: { msg: res.message || 'Zapret остановлен', type: 'info' }
                    }));
                }
            }
        }
    }

    if (toggleZapret) {
        toggleZapret.addEventListener('click', () => {
            const isOn = toggleZapret.classList.toggle('on');
            applyZapret(isOn);
        });
    }

    // Initial Status Check
    if (window.pywebview?.api?.get_zapret_status) {
        window.pywebview.api.get_zapret_status().then(status => {
            if (status) {
                const isRunning = !!(status.running || status.enabled);
                if (toggleZapret) toggleZapret.classList.toggle('on', isRunning);
                if (status.mode && selectZapretMode) {
                    selectedMode = status.mode;
                    selectZapretMode.value = status.mode;
                }
                if (versionBadge && status.version) {
                    versionBadge.textContent = status.version;
                }
                savedCustomArgs = status.custom_args || '';
                savedBinaryPath = status.binary_path || '';
                if (toggleAutoUpdate && status.autoupdate !== undefined) {
                    toggleAutoUpdate.classList.toggle('on', status.autoupdate === true);
                }
            }
        }).catch(() => {});
    }
}

export function applyCustomBg(bgDataUrl, blurPx = 0, dimPct = 30) {
    let bgLayer = document.getElementById('custom-bg-layer');
    let dimLayer = document.getElementById('custom-bg-dim-layer');
    const previewRow = document.getElementById('row-custom-bg-preview');
    const previewImg = document.getElementById('bg-image-preview');

    if (!bgDataUrl) {
        if (bgLayer) bgLayer.style.display = 'none';
        if (dimLayer) dimLayer.style.display = 'none';
        if (previewRow) previewRow.style.display = 'none';
        return;
    }

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
    bgLayer.style.backgroundImage = `url("${bgDataUrl}")`;
    bgLayer.style.filter = `blur(${blurPx || 0}px)`;

    dimLayer.style.display = 'block';
    dimLayer.style.background = `rgba(0, 0, 0, ${(dimPct !== undefined ? dimPct : 30) / 100})`;

    if (previewRow) previewRow.style.display = 'flex';
    if (previewImg) previewImg.style.backgroundImage = `url("${bgDataUrl}")`;
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
                reader.onload = (event) => {
                    const dataUrl = event.target.result;
                    saveSetting('custom_bg_image', dataUrl, 'theme');
                    const blurVal = document.getElementById('slider-bg-blur')?.value || 0;
                    const dimVal = document.getElementById('slider-bg-dim')?.value || 30;
                    applyCustomBg(dataUrl, blurVal, dimVal);
                };
                reader.readAsDataURL(file);
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
        setElText('label-bg-blur', `${v}px`);
        setElText('label-glass-blur', `${v}px`);
        const glassSlider = document.getElementById('slider-glass-blur');
        if (glassSlider) glassSlider.value = v;
        document.documentElement.style.setProperty('--glass-blur', `${v}px`);
        document.documentElement.style.setProperty('--blur-sm', `${Math.max(4, Math.round(v * 0.4))}px`);
        const dataUrl = localStorage.getItem('nedotify_theme_custom_bg_image');
        const dimVal = document.getElementById('slider-bg-dim')?.value || 30;
        if (dataUrl) {
            try { applyCustomBg(JSON.parse(dataUrl), v, dimVal); } catch(e) {}
        }
    });

    setupSlider('slider-bg-dim', 'bg_dim', 'theme', (v) => {
        setElText('label-bg-dim', `${v}%`);
        const dataUrl = localStorage.getItem('nedotify_theme_custom_bg_image');
        const blurVal = document.getElementById('slider-bg-blur')?.value || 0;
        if (dataUrl) {
            try { applyCustomBg(JSON.parse(dataUrl), blurVal, v); } catch(e) {}
        }
    });

    // Restore saved custom background image on setup
    const savedBg = localStorage.getItem('nedotify_theme_custom_bg_image');
    const savedBlurRaw = localStorage.getItem('nedotify_theme_bg_blur');
    const savedDimRaw = localStorage.getItem('nedotify_theme_bg_dim');

    if (savedBg) {
        try {
            const url = JSON.parse(savedBg);
            const savedBlur = savedBlurRaw ? JSON.parse(savedBlurRaw) : 0;
            const savedDim = savedDimRaw ? JSON.parse(savedDimRaw) : 30;
            if (url) applyCustomBg(url, savedBlur, savedDim);
        } catch(e) {}
    }
}

const ICON_PACKS = [
    { id: 'aura_neon', name: 'AURA Neon', icon: 'music', desc: 'Классическая нота NeDotify в неоновом розовoм свечении', color: '#ff2d55' },
    { id: 'cyber_disc', name: 'Cyber Disc', icon: 'disc', desc: 'Киберпанк винил с фиолетовой неоновой подсветкой', color: '#a855f7' },
    { id: 'flame_beats', name: 'Flame Beats', icon: 'flame', desc: 'Огненный ритм для чартов и горячих хит-парадов', color: '#f97316' },
    { id: 'cosmic_star', name: 'Cosmic Sound', icon: 'sparkles', desc: 'Космический саундскейп и звездный блеск', color: '#38bdf8' },
    { id: 'deep_subwoofer', name: 'Deep Subwoofer', icon: 'speaker', desc: 'Мощный бас и глубокий акустический звук', color: '#10b981' },
    { id: 'vintage_mic', name: 'Studio Vintage', icon: 'mic', desc: 'Классический студийный винтажный микрофон', color: '#eab308' },
    { id: 'wave_radio', name: 'Wave Radio', icon: 'radio', desc: 'Атмосферная радиоволна и лофай эстетика', color: '#ec4899' },
    { id: 'electric_heart', name: 'Electric Heart', icon: 'heart', desc: 'Музыкальный пульс прямо в сердце', color: '#ef4444' },
    { id: 'infinity_stream', name: 'Infinity Stream', icon: 'infinity', desc: 'Бесконечный гибридный поток треков', color: '#6366f1' },
    { id: 'crown_gold', name: 'Crown Gold', icon: 'crown', desc: 'Премиальный золотой VIP флагманский стиль', color: '#f59e0b' }
];

export const PACK_ICON_MAPS = {
    aura_neon: {
        logo: 'music',
        play: 'play',
        pause: 'pause',
        next: 'skip-forward',
        prev: 'skip-back',
        shuffle: 'shuffle',
        repeat: 'repeat',
        volume: 'volume-2',
        settings: 'settings',
        home: 'home',
        search: 'search',
        library: 'list-music',
        queue: 'list-plus'
    },
    cyber_disc: {
        logo: 'disc',
        play: 'play',
        pause: 'pause',
        next: 'skip-forward',
        prev: 'skip-back',
        shuffle: 'refresh-cw',
        repeat: 'repeat-1',
        volume: 'volume-x',
        settings: 'monitor',
        home: 'disc',
        search: 'search',
        library: 'folder-open',
        queue: 'list-music'
    },
    flame_beats: {
        logo: 'zap',
        play: 'play',
        pause: 'pause',
        next: 'skip-forward',
        prev: 'skip-back',
        shuffle: 'zap',
        repeat: 'repeat',
        volume: 'volume-2',
        settings: 'settings',
        home: 'zap',
        search: 'search',
        library: 'hard-drive',
        queue: 'list-plus'
    },
    cosmic_star: {
        logo: 'sparkles',
        play: 'play',
        pause: 'pause',
        next: 'skip-forward',
        prev: 'skip-back',
        shuffle: 'sparkles',
        repeat: 'sun',
        volume: 'sparkles',
        settings: 'settings',
        home: 'sparkles',
        search: 'search',
        library: 'sparkles',
        queue: 'list-music'
    },
    deep_subwoofer: {
        logo: 'volume-2',
        play: 'play',
        pause: 'pause',
        next: 'skip-forward',
        prev: 'skip-back',
        shuffle: 'shuffle',
        repeat: 'repeat-1',
        volume: 'volume-2',
        settings: 'settings',
        home: 'volume-2',
        search: 'search',
        library: 'folder-open',
        queue: 'list-music'
    },
    vintage_mic: {
        logo: 'mic',
        play: 'play',
        pause: 'pause',
        next: 'skip-forward',
        prev: 'skip-back',
        shuffle: 'shuffle',
        repeat: 'repeat',
        volume: 'mic',
        settings: 'settings',
        home: 'radio',
        search: 'search',
        library: 'folder-open',
        queue: 'list-music'
    },
    wave_radio: {
        logo: 'radio',
        play: 'play',
        pause: 'pause',
        next: 'skip-forward',
        prev: 'skip-back',
        shuffle: 'shuffle',
        repeat: 'repeat',
        volume: 'volume-1',
        settings: 'settings',
        home: 'radio',
        search: 'search',
        library: 'list-music',
        queue: 'list-plus'
    },
    electric_heart: {
        logo: 'heart',
        play: 'play',
        pause: 'pause',
        next: 'skip-forward',
        prev: 'skip-back',
        shuffle: 'shuffle',
        repeat: 'heart',
        volume: 'volume-1',
        settings: 'heart',
        home: 'heart',
        search: 'search',
        library: 'heart',
        queue: 'list-music'
    },
    infinity_stream: {
        logo: 'infinity',
        play: 'play',
        pause: 'pause',
        next: 'skip-forward',
        prev: 'skip-back',
        shuffle: 'infinity',
        repeat: 'refresh-cw',
        volume: 'volume-2',
        settings: 'settings',
        home: 'infinity',
        search: 'search',
        library: 'infinity',
        queue: 'list-music'
    },
    crown_gold: {
        logo: 'crown',
        play: 'play',
        pause: 'pause',
        next: 'skip-forward',
        prev: 'skip-back',
        shuffle: 'crown',
        repeat: 'shield',
        volume: 'award',
        settings: 'settings',
        home: 'crown',
        search: 'sparkles',
        library: 'shield',
        queue: 'list-music'
    }
};

export function applyIconPack(packId) {
    const pack = ICON_PACKS.find(p => p.id === packId) || ICON_PACKS[0];
    const map = PACK_ICON_MAPS[packId] || PACK_ICON_MAPS['aura_neon'];
    const root = document.documentElement;
    root.setAttribute('data-icon-pack', pack.id);

    // Cache map globally so player.js can read play/pause icon names synchronously
    window.__PACK_ICON_MAPS__ = PACK_ICON_MAPS;

    // Helper: set data-lucide on parent element's icon child (i or svg)
    const setIcon = (containerSelector, iconName) => {
        const parent = document.querySelector(containerSelector);
        if (!parent || !iconName) return;
        const iconEl = parent.querySelector('i, svg');
        const newI = document.createElement('i');
        newI.setAttribute('data-lucide', iconName);
        if (iconEl) {
            const style = iconEl.getAttribute('style');
            if (style) newI.setAttribute('style', style);
            iconEl.replaceWith(newI);
        } else {
            parent.appendChild(newI);
        }
    };

    // Logo
    const logoEl = document.querySelector('.sidebar-logo');
    if (logoEl) {
        logoEl.innerHTML = `<i data-lucide="${map.logo}" style="width:24px;height:24px;filter:drop-shadow(0 0 10px ${pack.color});"></i> NeDotify`;
    }

    // Player bar transport controls
    setIcon('#pb-btn-play', map.play);
    setIcon('#pb-btn-next', map.next);
    setIcon('#pb-btn-prev', map.prev);
    setIcon('#pb-btn-shuffle', map.shuffle);
    setIcon('#pb-btn-repeat', map.repeat);
    setIcon('#pb-btn-queue', map.queue);
    setIcon('#pb-volume-btn', map.volume);

    // Full player page (popup player / big player)
    setIcon('#pp-btn-play', map.play);
    setIcon('#pp-btn-next', map.next);
    setIcon('#pp-btn-prev', map.prev);
    setIcon('#pp-btn-shuffle', map.shuffle);
    setIcon('#pp-btn-repeat', map.repeat);
    setIcon('#pp-volume-btn', map.volume);
    setIcon('#fs-volume-btn', map.volume);

    // Mini-player transport controls
    setIcon('#mp-btn-play', map.play);
    setIcon('#mp-btn-next', map.next);
    setIcon('#mp-btn-prev', map.prev);
    setIcon('#btn-mini-play', map.play);
    setIcon('#btn-mini-next', map.next);
    setIcon('#btn-mini-prev', map.prev);

    // Sidebar navigation icons
    setIcon('.nav-item[data-page="home"]', map.home);
    setIcon('.nav-item[data-page="search"]', map.search);
    setIcon('.nav-item[data-page="library"]', map.library);
    setIcon('.nav-item[data-page="player"]', map.play);
    setIcon('.nav-item[data-page="settings"]', map.settings);

    // Re-render all Lucide icons that now have data-lucide set
    try {
        if (window.lucide) {
            window.lucide.createIcons();
        }
    } catch(e) {}

    // Highlight active pack card in settings grid
    document.querySelectorAll('#icon-packs-grid .opt-card').forEach(card => {
        const isActive = card.dataset.id === pack.id;
        card.classList.toggle('active', isActive);
        if (isActive) {
            card.style.setProperty('border-color', pack.color, 'important');
            card.style.setProperty('box-shadow', `0 0 20px ${pack.color}66`, 'important');
            card.style.setProperty('background', `rgba(255,255,255,0.12)`, 'important');
        } else {
            card.style.setProperty('border-color', 'rgba(255,255,255,0.14)', 'important');
            card.style.setProperty('box-shadow', 'none', 'important');
            card.style.setProperty('background', 'rgba(255,255,255,0.07)', 'important');
        }
    });
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

    const savedPack = localStorage.getItem('nedotify_theme_icon_pack');
    if (savedPack) {
        try {
            const pid = JSON.parse(savedPack);
            if (pid) applyIconPack(pid);
        } catch(e) {}
    } else {
        const currentPack = document.documentElement.getAttribute('data-icon-pack') || 'aura_neon';
        applyIconPack(currentPack);
    }
}


// в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ
// Player Settings Customizations
// в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ

export function applyTitleAlignment(align) {
    const root = document.documentElement;
    root.classList.remove('title-align-left', 'title-align-center', 'title-align-right');
    root.classList.add(`title-align-${align}`);
}

export function applyPlayerStyle(style) {
    const root = document.documentElement;
    root.classList.remove('player-style-default', 'player-style-vinyl', 'player-style-expanded');
    root.classList.add(`player-style-${style}`);
}

export function applyAuraOrbs(enabled) {
    const el = document.getElementById('aura-orbs-container');
    if (!el) return;
    const isLightMode = document.documentElement.getAttribute('data-theme') === 'light';
    const isPerfLow = document.documentElement.classList.contains('perf-low');
    const isBatterySaver = document.documentElement.classList.contains('battery-saver-active');
    
    // Automatically disable in light mode or low-performance / battery saver modes
    const shouldDisable = !enabled || isLightMode || isPerfLow || isBatterySaver;
    el.classList.toggle('disabled', shouldDisable);
}

export function applySliderType(type) {
    const root = document.documentElement;
    root.classList.remove('slider-type-default', 'slider-type-thin', 'slider-type-ios', 'slider-type-wave');
    root.classList.add(`slider-type-${type}`);
    window.dispatchEvent(new CustomEvent('nedotify:slider_type_changed', { detail: { type } }));
}

export function applyShowQueue(enabled) {
    const btn = document.getElementById('pb-btn-queue');
    if (btn) btn.style.display = enabled ? '' : 'none';
}

export function applyQueuePosition(pos) {
    const root = document.documentElement;
    root.classList.remove('queue-pos-bottom', 'queue-pos-left', 'queue-pos-right');
    root.classList.add(`queue-pos-${pos}`);
}

export function applyCompactQueueBtn(enabled) {
    const btn = document.getElementById('pb-btn-queue');
    if (btn) btn.classList.toggle('compact-queue-btn', !!enabled);
}

export function applyNextTrackPreview(enabled) {
    let badge = document.getElementById('next-track-preview-badge');
    if (!badge && enabled) {
        badge = document.createElement('div');
        badge.id = 'next-track-preview-badge';
        badge.className = 'next-track-preview-badge';
        const playerCenter = document.querySelector('.player-center');
        if (playerCenter) playerCenter.appendChild(badge);
    }
    if (badge) badge.style.display = enabled ? 'flex' : 'none';
}

export function applyQueueViewMode(mode) {
    const root = document.documentElement;
    root.classList.remove('queue-view-normal', 'queue-view-expanded');
    root.classList.add(`queue-view-${mode}`);
}

export function applyMpProgress(type) {
    const root = document.documentElement;
    root.classList.remove('mp-progress-line', 'mp-progress-bg', 'mp-progress-cover');
    root.classList.add(`mp-progress-${type}`);
}

export function applyMpCoverShape(shape) {
    const root = document.documentElement;
    root.classList.remove('mp-cover-default', 'mp-cover-circle');
    root.classList.add(`mp-cover-${shape}`);
}

export function applyMpShape(shape) {
    const root = document.documentElement;
    root.classList.remove('mp-shape-default', 'mp-shape-capsule');
    root.classList.add(`mp-shape-${shape}`);
}

export function applyMpPos(pos) {
    const root = document.documentElement;
    root.classList.remove('mp-pos-top-left', 'mp-pos-top-center', 'mp-pos-top-right', 'mp-pos-bottom-left', 'mp-pos-bottom-center', 'mp-pos-bottom-right', 'mp-pos-center');
    root.classList.add(`mp-pos-${pos}`);
    if (window.pywebview?.api?.set_mini_player_position) {
        try {
            window.pywebview.api.set_mini_player_position(pos);
        } catch(e) {}
    }
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
    setupToggle('toggle-queue-autopilot', 'queue_autopilot', 'player');
    setupToggle('toggle-player-prefetch', 'player_prefetch', 'player');
    setupToggle('toggle-aura-orbs', 'aura_orbs_enabled', 'player', applyAuraOrbs);

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

    // Restore saved settings from localStorage
    const saved = {
        align: getLocalSetting('nedotify_player_title_align', 'left'),
        style: getLocalSetting('nedotify_player_player_style', 'default'),
        slider: getLocalSetting('nedotify_player_slider_type', 'default'),
        showQueue: getLocalSetting('nedotify_player_show_queue', true),
        queuePos: getLocalSetting('nedotify_player_queue_pos', 'bottom'),
        compactQueue: getLocalSetting('nedotify_player_compact_queue_btn', true),
        nextPreview: getLocalSetting('nedotify_player_next_track_preview', true),
        autopilot: getLocalSetting('nedotify_player_queue_autopilot', true),
        prefetch: getLocalSetting('nedotify_player_player_prefetch', true),
        auraOrbs: getLocalSetting('nedotify_player_aura_orbs_enabled', true),
        queueView: getLocalSetting('nedotify_player_queue_view', 'normal'),
        mpProg: getLocalSetting('nedotify_player_mp_progress', 'line'),
        mpCover: getLocalSetting('nedotify_player_mp_cover_shape', 'default'),
        mpShape: getLocalSetting('nedotify_player_mp_shape', 'default'),
        mpPos: getLocalSetting('nedotify_player_mp_pos', 'bottom-right'),
    };

    // Update active UI cards according to saved state
    const syncActiveCard = (containerId, val) => {
        const c = document.getElementById(containerId);
        if (c) {
            c.querySelectorAll('.opt-card').forEach(card => {
                card.classList.toggle('active', card.dataset.val === val);
            });
        }
    };

    // Sync toggle visual states from saved values
    const syncToggleVisual = (id, val) => {
        const t = document.getElementById(id);
        if (t) t.classList.toggle('on', !!val);
    };

    syncActiveCard('opt-title-align', saved.align);
    syncActiveCard('opt-player-style', saved.style);
    syncActiveCard('opt-slider-type', saved.slider);
    syncActiveCard('opt-queue-pos', saved.queuePos);
    syncActiveCard('opt-queue-view', saved.queueView);
    syncActiveCard('opt-mp-progress', saved.mpProg);
    syncActiveCard('opt-mp-cover-shape', saved.mpCover);
    syncActiveCard('opt-mp-shape', saved.mpShape);

    // Sync toggle visuals
    syncToggleVisual('toggle-show-queue', saved.showQueue);
    syncToggleVisual('toggle-compact-queue-btn', saved.compactQueue);
    syncToggleVisual('toggle-next-track-preview', saved.nextPreview);
    syncToggleVisual('toggle-queue-autopilot', saved.autopilot);
    syncToggleVisual('toggle-player-prefetch', saved.prefetch);
    syncToggleVisual('toggle-aura-orbs', saved.auraOrbs);

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


// ─── WORKSHOP (МАСТЕРСКАЯ) MODULE ───
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

// Proxy Unsplash images to bypass regional blocks
WORKSHOP_ITEMS.forEach(item => {
    if (item.preview.includes('unsplash.com')) {
        item.preview = `https://wsrv.nl/?url=${encodeURIComponent(item.preview)}`;
    }
    if (item.url.includes('unsplash.com')) {
        item.url = `https://wsrv.nl/?url=${encodeURIComponent(item.url)}`;
    }
});

export function setupWorkshopPanel() {
    const grid = document.getElementById('workshop-cards-grid');
    const searchInput = document.getElementById('workshop-search-input');
    const sortSelect = document.getElementById('workshop-sort-select');
    const tagsContainer = document.getElementById('workshop-tags-container');

    if (!grid) return;

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
            grid.innerHTML = '<div class="empty-state" style="grid-column: 1 / -1; padding: 40px; text-align: center; color: var(--text-sec)">РќРёС‡РµРіРѕ не найденРѕ</div>';
            return;
        }

        const activeBgUrl = getLocalSetting('nedotify_theme_custom_bg_image', '');

        grid.innerHTML = items.map(it => {
            const isApplied = activeBgUrl === it.url;
            const isLiked = getLikedState(it.id);
            const displayLikes = isLiked ? it.likes + 1 : it.likes;

            return `
                <div class="workshop-card ${isApplied ? 'applied' : ''}" data-id="${it.id}">
                    <div class="workshop-card-preview">
                        <img src="${it.preview}" class="workshop-card-media" alt="${it.title}" loading="lazy">
                        ${it.badge ? `<div class="workshop-card-badge">${it.badge}</div>` : ''}
                        <div class="workshop-card-overlay">
                            <button class="workshop-btn-apply" data-id="${it.id}">
                                <i data-lucide="${isApplied ? 'check' : 'image'}" style="width:16px;height:16px"></i>
                                <span>${isApplied ? 'Установлено' : 'Применить'}</span>
                            </button>
                        </div>
                    </div>
                    <div class="workshop-card-info">
                        <div>
                            <div class="workshop-card-title" title="${it.title}">${it.title}</div>
                            <div class="workshop-card-author">by ${it.author}</div>
                        </div>
                        <div class="workshop-card-stats">
                            <div class="workshop-stat-item ${isLiked ? 'liked' : ''}" data-like-id="${it.id}">
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

        renderIcons();

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

    render();

    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            searchQuery = e.target.value;
            render();
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
                    <button class="btn-sm text-xs btn-delete-dup" data-id="${track.id}" style="padding:4px 8px; border-radius:6px; background:rgba(239,68,68,0.2); color:#ef4444; border:1px solid rgba(239,68,68,0.3); cursor:pointer;">Удалить</button>
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
                if (trackId && window.pywebview?.api?.delete_duplicate_track) {
                    await window.pywebview.api.delete_duplicate_track(trackId, true);
                    e.target.closest('div').remove();
                }
            });
        });

        container.appendChild(groupEl);
    });
}





