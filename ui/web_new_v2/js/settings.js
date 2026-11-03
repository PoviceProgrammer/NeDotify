// NeDotify — Settings Module
import { renderIcons, escapeHtml, compressBackgroundImage, showToast, openModalFocusTrap, closeModalFocusTrap } from './utils.js';
import { setParticlesFps } from './particles.js';
import { restoreAtmosphereSettings } from './atmosphere-settings.js';
import { restoreDiscordSettings } from './discord-settings.js';
import { setVisualizerFps, setVisualizerEnabled } from './visualizer.js';
import { DEFAULT_KEYBINDS, activeKeybinds, setListeningKeybind, getListeningKeybindId } from './hotkeys.js';
import { evaluateEfficiencyState } from './efficiency.js';
import { setUiFps, applyAudioSettings } from './player.js';
import { initSettingsView, themePreviewPath, syncThemeSelection, syncCustomColorFields } from './settings-view.js';
import { settingAliases } from './setting-aliases.js';

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

// Helper: read a saved setting, preferring the backend (the durable store).
//
// The restore helpers below used to read localStorage unconditionally, so a
// cleared/evicted WebView2 cache silently reset every setting to its default
// even though the backend still had the user's value -- the "my settings did
// not save" symptom. window.settings is populated from the backend before these
// run, so it wins; localStorage stays as the fallback for keys the backend has
// not seen yet, and for the first paint before the bridge answers.
function savedSetting(category, key, defaultVal) {
    const fromBackend = window.settings?.[category]?.[key];
    if (fromBackend !== undefined && fromBackend !== null) return fromBackend;
    return getLocalSetting(`nedotify_${category}_${key}`, defaultVal);
}

function syncSwitch(toggle, enabled) {
    if (!toggle) return;
    toggle.classList.toggle('on', !!enabled);
    toggle.setAttribute('aria-checked', String(!!enabled));
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
    { id: 'default', name: 'По умолчанию', family: "'Segoe UI', system-ui, sans-serif", cat: 'system' },
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
        const card = document.createElement('button');
        card.type = 'button';
        const isActive = t.id === currentTheme;
        card.className = `theme-card${isActive ? ' active' : ''}`;
        card.dataset.theme = t.id;
        card.setAttribute('aria-pressed',String(isActive));
        card.setAttribute('aria-label',`Тема ${t.name}`);
        card.innerHTML = `
            <span class="theme-preview">${themePreviewPath(t.id) ? `<img src="${themePreviewPath(t.id)}" class="theme-preview-image" alt="" width="186" height="58" loading="lazy">` : ''}</span>
            <span class="theme-card-badge" ${isActive?'':'hidden'} aria-hidden="true">✓</span>
            <div class="theme-dots-row">
                <div class="theme-dot" style="background:${t.colors[1]}"></div>
                <div class="theme-dot" style="background:${t.colors[2]}"></div>
            </div>
            <span class="theme-card-name">${escapeHtml(t.name)}</span>
        `;
        card.querySelector('.theme-preview').style.background = `linear-gradient(135deg,${t.colors[0]},${t.colors[1]})`;
        card.querySelector('img')?.addEventListener('error', event => { event.currentTarget.hidden = true; });
        card.addEventListener('click', () => {
            document.documentElement.setAttribute('data-theme', t.id);
            saveSetting('theme', t.id, 'theme');
            saveSetting('theme_mode','dark','theme');
            document.querySelectorAll('.theme-mode-btn').forEach(button=>button.classList.toggle('active',button.dataset.mode==='dark'));
            resetCustomPalette(false);
            syncThemeSelection();
        });
        container.appendChild(card);
    });
}

function renderFontCards(activeCat = 'system') {
    const container = document.getElementById('font-cards-grid');
    if (!container) return;

    // The picker families (Inter, Outfit, Roboto, Montserrat, Plus Jakarta
    // Sans) are remote and loaded on demand by boot.js. Request them here -
    // i.e. when the picker is actually rendered - so a cold start does not
    // pay for them. Idempotent; a failed/offline load just leaves the fallback.
    if (typeof window.NeDotifyEnsurePickerFonts === 'function') {
        try { window.NeDotifyEnsurePickerFonts(); } catch (e) {}
    }

    container.innerHTML = '';
    const filteredFonts = FONTS_LIST.filter(f => f.cat === activeCat || activeCat === 'all');
    filteredFonts.forEach(f => {
        const card = document.createElement('div');
        const normalizedFont = value => value.replace(/["']/g, '').replace(/\s+/g, '').toLowerCase();
        const macos = document.documentElement.dataset.uiStyle === 'macos';
        const savedFont = savedSetting(macos?'interface':'theme',macos?'macos_font_family':'font_family','system');
        const isActive = savedFont === 'system' ? f.id === 'default' : normalizedFont(savedFont) === normalizedFont(f.family);
        card.className = `font-card${isActive ? ' active' : ''}`;
        card.dataset.font = f.family;
        card.innerHTML = `
            <div class="font-preview-letters" style="font-family:${f.family}">Aa</div>
            <span class="font-card-name">${escapeHtml(f.name)}</span>
        `;
        card.addEventListener('click', () => {
            container.querySelectorAll('.font-card').forEach(c => c.classList.remove('active'));
            card.classList.add('active');
            document.documentElement.style.setProperty('--font-family', f.family);
            const macos = document.documentElement.dataset.uiStyle === 'macos';
            const val = f.id === 'default' ? 'system' : f.family;
            saveSetting(macos?'macos_font_family':'font_family', val, macos?'interface':'theme');
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
    syncSwitch(toggle, savedSetting(category, key, toggle.classList.contains('on')));

    if (toggle._boundClick) toggle.removeEventListener('click', toggle._boundClick);

    const clickHandler = async () => {
        const isOn = toggle.classList.toggle('on');
        toggle.setAttribute('aria-checked', String(isOn));
        const pending = saveSetting(key, isOn, category);
        
        if (onChange) onChange(isOn);

        // Apply immediately
        if (key === 'cover_visualizer') {
            const canvas = document.getElementById('visualizer-canvas');
            if (canvas) canvas.style.display = isOn ? 'block' : 'none';
        }
        const saved = await pending;
        if (!saved) {
            const restored = savedSetting(category, key, !isOn);
            syncSwitch(toggle, restored);
            if (onChange) onChange(restored);
        }
        return saved;
    };
    toggle._boundClick = clickHandler;
    toggle.addEventListener('click', clickHandler);
}

function setupSlider(id, key, category, onChange, resolveTarget = () => ({key,category}), afterSave) {
    const slider = document.getElementById(id);
    if (!slider) return;

    const updatePercent = (val) => {
        const min = parseFloat(slider.min) || 0;
        const max = parseFloat(slider.max) || 100;
        const pct = (val - min) / (max - min) * 100;
        slider.style.setProperty('--value-percent', `${pct}%`);
    };
    updatePercent(slider.value);

    if (slider._boundInput) slider.removeEventListener('input', slider._boundInput);
    if (slider._boundChange) slider.removeEventListener('change', slider._boundChange);

    let preview;
    const inputHandler = (e) => {
        const target = resolveTarget();
        if (!preview || preview.category !== target.category || preview.key !== target.key) {
            preview = { ...target, value: savedSetting(target.category, target.key, Number(slider.defaultValue || slider.value)),
                previous: settingAliases(target.category, target.key).map(([cat, name]) => [cat, name, window.settings?.[cat]?.[name]]) };
        }
        // Preview consumers read window.settings; only change persists to disk.
        window.settings ||= {};
        window.settings[target.category] ||= {};
        window.settings[target.category][target.key] = Number(e.target.value);
        for (const [cat, name] of settingAliases(target.category, target.key)) {
            window.settings[cat] ||= {};
            window.settings[cat][name] = Number(e.target.value);
        }
        if (target.category === 'audio') applyAudioSettings(window.settings.audio);
        updatePercent(e.target.value);
        if (onChange) onChange(e.target.value);
    };
    const changeHandler = async (e) => {
        inputHandler(e);
        const target = resolveTarget();
        const snapshot = preview;
        preview = null;
        const value = Number(e.target.value);
        const saved = await saveSetting(target.key, value, target.category, { previous: snapshot.previous });
        if (saved && afterSave) await afterSave(value);
        if (!saved && !preview) {
            const restored = savedSetting(target.category, target.key, snapshot.value);
            syncSlider(id, restored);
            if (onChange) onChange(String(restored));
        }
        return saved;
    };

    slider._boundInput = inputHandler;
    slider._boundChange = changeHandler;
    slider.addEventListener('input', inputHandler);
    slider.addEventListener('change', changeHandler);
}

export function syncPrivacySettings() {
    syncSwitch(document.getElementById('toggle-lyrics-enabled'), window.settings?.lyrics?.enabled !== false);
    for (const [key, fallback] of [['mode', 'auto'], ['animations', 'standard']]) {
        const input = document.getElementById(`lyrics-${key}`);
        if (input) input.value = window.settings?.lyrics?.[key] || fallback;
    }
    syncSwitch(document.getElementById('toggle-lastfm-enabled'), window.settings?.services?.lastfm_enabled === true);
    for (const name of ['youtube','soundcloud']) {
        syncSwitch(document.getElementById(`toggle-source-${name}`), window.settings?.services?.[`${name}_enabled`] !== false);
    }
    const lastfmUsername = document.getElementById('input-lastfm-username');
    if (lastfmUsername && window.settings?.auth?.lastfm_username !== undefined) {
        lastfmUsername.value = String(window.settings.auth.lastfm_username || '');
    }
    const lastfmApiKey = document.getElementById('input-lastfm-api-key');
    if (lastfmApiKey) {
        // The backend returns only the masked value plus has_lastfm_api_key.
        // Never reflect a credential into this input from settings state.
        const hasSavedKey = window.settings?.services?.has_lastfm_api_key === true ||
            window.settings?.auth?.has_lastfm_api_key === true;
        lastfmApiKey.placeholder = hasSavedKey ? 'Ключ сохранён (введите новый, чтобы заменить)' : 'Введите API-ключ';
    }
}

export function applyBorderRadius(value = 12) {
    const numeric = Number(value);
    const radius = Number.isFinite(numeric) ? Math.max(0, Math.min(24, Math.round(numeric))) : 12;
    const root = document.documentElement;
    root.style.setProperty('--interface-radius', `${radius}px`);
    for (const [name, scale] of [['xs',.25],['sm',.5],['md',1],['lg',1.5],['xl',2]]) {
        root.style.setProperty(`--radius-${name}`, `${Math.round(radius * scale)}px`);
    }
    root.classList?.add?.('has-interface-radius');
    const slider = document.getElementById('slider-border-radius');
    if (slider) {
        slider.value = radius;
        slider.style.setProperty('--value-percent', `${radius / 24 * 100}%`);
    }
    setElText('label-border-radius', `${radius}px`);
    return radius;
}

export function applySettingsFromBackend(settings) {
    if (!settings) return;
    window.settings ||= {};
    for (const [category, values] of Object.entries(settings)) {
        if (values && typeof values === 'object' && !Array.isArray(values)) {
            window.settings[category] = { ...window.settings[category], ...values };
        }
    }
    syncPrivacySettings();
    applyBorderRadius(window.settings.interface?.border_radius);
    window.dispatchEvent(new CustomEvent('nedotify:lyrics_settings_changed', {detail: window.settings.lyrics || {}}));
    window.NeDotifyAppearance?.restore(settings);
    applyAudioSettings(settings.audio || {});

    const appliedTheme = settings.theme?.theme || settings.theme?.name || settings.theme?.mode || settings.ui?.theme || settings.interface?.theme;
    if (appliedTheme) {
        document.documentElement.setAttribute('data-theme', appliedTheme);
        document.querySelectorAll('.theme-btn, .theme-card').forEach(btn => {
            btn.classList.toggle('active', (btn.dataset.theme === appliedTheme || btn.dataset.themeId === appliedTheme));
        });
    }

    // theme_mode is the actual light/dark/system switch (theme.theme is the palette name).
    // Both used to be written to the same data-theme attribute, so applying the
    // mode straight after the palette made the chosen palette vanish on every
    // restart. The palette now wins; the mode only picks the colours when no
    // palette is stored, and the mode buttons always reflect the saved state.
    if (settings.theme && settings.theme.theme_mode !== undefined) {
        const mode = String(settings.theme.theme_mode);
        document.querySelectorAll('.theme-mode-btn[data-mode]').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });
        const hasPalette = !!(settings.theme.theme || settings.theme.name);
        if (!hasPalette) {
            try { applyThemeMode(mode); } catch(e) {}
        }
    }
    restoreCustomPalette(settings.theme);
    syncThemeSelection();
    renderSavedCustomThemes(settings.theme);

    if (settings.ui) {
        if (settings.ui.cover_visualizer !== undefined) {
            const toggle = document.getElementById('toggle-visualizer');
            if (toggle) toggle.classList.toggle('on', !!settings.ui.cover_visualizer);
            try { setVisualizerEnabled(!!settings.ui.cover_visualizer, { silent: true }); } catch(e) {}
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
            // BUG-U3-005: мёртвый lookup select-font-family удалён — элемента нет
            // в разметке. setProperty — живое применение сохранённого шрифта при
            // загрузке настроек (выбор — карточки font-cards-grid, settings.js:183).
            document.documentElement.style.setProperty('--font-family', settings.theme.font_family === 'system' ? '"Segoe UI", system-ui, sans-serif' : settings.theme.font_family);
        }

        if (settings.theme) {
            if (settings.theme.transparency_enabled !== undefined) {
                const toggle = document.getElementById('toggle-transparency');
                if (toggle) toggle.classList.toggle('on', settings.theme.transparency_enabled);
            }
            if (settings.theme.transparency_level !== undefined) {
                const slider = document.getElementById('slider-transparency-level');
                if (slider) {
                    slider.value = transparencyPercent(settings.theme.transparency_level);
                    const pct = (slider.value - slider.min) / (slider.max - slider.min) * 100;
                    slider.style.setProperty('--value-percent', `${pct}%`);
                }
                setElText('label-transparency-level', `${transparencyPercent(settings.theme.transparency_level)}%`);
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


    if (settings.audio) {
        const toggleCF = document.getElementById('toggle-crossfade');
        if (toggleCF) toggleCF.classList.toggle('on', !!settings.audio.crossfade_enabled);
        const cfSec = settings.audio.crossfade_duration_sec ?? settings.audio.crossfade_sec ?? settings.audio.crossfade_duration;
        if (cfSec !== undefined) {
            const sliderCF = document.getElementById('slider-crossfade-sec');
            if (sliderCF) {
                sliderCF.value = cfSec;
                const pct = (sliderCF.value - sliderCF.min) / (sliderCF.max - sliderCF.min) * 100;
                sliderCF.style.setProperty('--value-percent', `${pct}%`);
            }
            setElText('label-crossfade-sec', `${cfSec} сек`);
        }
        const toggleGL = document.getElementById('toggle-gapless');
        if (toggleGL) toggleGL.classList.toggle('on', settings.audio.gapless_playback !== false);
        const toggleAP = document.getElementById('toggle-autoplay');
        if (toggleAP) toggleAP.classList.toggle('on', !!settings.audio.autoplay);
        // volume_normalization is bound in setupToggle('toggle-normalization',
        // 'volume_normalization', 'audio') so it was saved on every change but
        // never read back here, leaving the toggle stuck at its default after a
        // restart even though the backend had the right value.
        if (settings.audio.volume_normalization !== undefined) {
            const toggleVN = document.getElementById('toggle-normalization');
            if (toggleVN) toggleVN.classList.toggle('on', !!settings.audio.volume_normalization);
        }
    }

    if (settings.general) {
        const selectRegion = document.getElementById('select-region');
        if (selectRegion && settings.general.region !== undefined) {
            selectRegion.value = settings.general.region;
        }
    }

    restoreDiscordSettings(window.settings);

    if (settings.efficiency) {
        setupEfficiencyPanel();
    }

    if (settings.optimization) {
        setupOptimizationPanel();
    }

    if (settings.player) {
        if (upgradeQueuePanelPreferences(settings.player)) {
            Promise.resolve(saveSetting('show_queue', true, 'player')).then(result => {
                if (result !== false && result?.success !== false) return saveSetting('queue_panel_version', 1, 'player');
            }).catch(() => {});
        }
        if (settings.player.title_align) applyTitleAlignment(settings.player.title_align);
        if (settings.player.player_style) applyPlayerStyle(settings.player.player_style);
        if (settings.player.slider_type) applySliderType(settings.player.slider_type);
        applyProgressColor(savedSetting('player', 'progress_color', '#10d6a3'));
        applyProgressTransparency(savedSetting('player', 'progress_transparency', 18));
        if (settings.player.show_queue !== undefined) applyShowQueue(settings.player.show_queue);
        if (settings.player.queue_pos) applyQueuePosition(settings.player.queue_pos);
        if (settings.player.compact_queue_btn !== undefined) applyCompactQueueBtn(settings.player.compact_queue_btn);
        if (settings.player.next_track_preview !== undefined) applyNextTrackPreview(settings.player.next_track_preview);
        if (settings.player.aura_orbs_enabled !== undefined) applyAuraOrbs(settings.player.aura_orbs_enabled);
        if (settings.player.queue_view) applyQueueViewMode(settings.player.queue_view);
        if (settings.player.mp_progress) applyMpProgress(settings.player.mp_progress);
        if (settings.player.mp_cover_shape) applyMpCoverShape(settings.player.mp_cover_shape);
        if (settings.player.mp_shape) applyMpShape(settings.player.mp_shape);
        if (settings.player.mp_pos) applyMpPos(settings.player.mp_pos);
        // Now that window.settings holds the backend values, repaint the Player
        // tab's cards and toggles. The earlier setupPlayerSettingsPanel() pass
        // ran before the bridge answered and could only guess from localStorage.
        try { syncPlayerSettingsUI(); } catch(e) {}
    }

    if (settings.storage) {
        document.getElementById('toggle-auto-download-favorites')?.classList.toggle('on', !!savedSetting('storage', 'auto_download_favorites', false));
        for (const [id, key] of [['select-auto-download-quota','auto_download_favorites_quota_gb'], ['select-cache-quota','cache_quota_gb']]) {
            const select = document.getElementById(id);
            if (select && settings.storage[key] !== undefined) select.value = String(settings.storage[key]);
        }
    }
    if (settings.theme?.font_family !== undefined) renderFontCards(document.querySelector('.font-cat-btn.active')?.dataset.cat || 'system');
    if (settings.theme?.bg_blur !== undefined) syncSlider('slider-bg-blur', settings.theme.bg_blur, 'label-bg-blur', 'px');
    if (settings.theme?.bg_dim !== undefined) syncSlider('slider-bg-dim', settings.theme.bg_dim, 'label-bg-dim', '%');
    restoreAtmosphereSettings(window.settings);
    document.dispatchEvent(new CustomEvent('nedotify:settings_applied', { detail: window.settings }));

    if (settings.auth) {
        const inputYandexToken = document.getElementById('input-yandex-token');
        if (inputYandexToken) {
            inputYandexToken.value = '';
            inputYandexToken.placeholder = settings.auth.has_yandex_token ? 'Токен сохранён (введите новый, чтобы заменить)' : 'Введите yandex_token...';
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
        if (inputOauthClientId) {
            inputOauthClientId.disabled = true;
            inputOauthClientId.title = 'В разработке';
            if (settings.auth.oauth_client_id !== undefined) {
                inputOauthClientId.value = settings.auth.oauth_client_id;
            }
        }
        
        // SECURITY WARNING: OAuth client secret must not be stored or transmitted in frontend.
        // Use PKCE flow or backend token exchange.
        const inputOauthClientSecret = document.getElementById('input-oauth-client-secret');
        if (inputOauthClientSecret) {
            inputOauthClientSecret.disabled = true;
            inputOauthClientSecret.title = 'В разработке';
            inputOauthClientSecret.value = '';
            inputOauthClientSecret.placeholder = settings.auth.has_oauth_client_secret ? 'Секрет сохранён (введите новый, чтобы заменить)' : 'Client Secret...';
        }
        
        const btnYtmusicOauth = document.getElementById('btn-ytmusic-oauth');
        if (btnYtmusicOauth) {
            btnYtmusicOauth.disabled = true;
            btnYtmusicOauth.title = 'В разработке';
            if (settings.auth.oauth_completed) {
                btnYtmusicOauth.textContent = '✅ Привязано';
                btnYtmusicOauth.style.background = 'var(--success, #10b981)';
            }
        }
        
        // Yandex auth errors arrive as a dedicated event; token values stay
        // backend-only and are never copied into this form.
    }
}

// The backend sends only an invalid flag, never the credential itself.
export function setYandexWarning(visible) {
    const warning = document.getElementById('yandex-auth-warning');
    if (warning) {
        warning.style.display = visible ? 'flex' : 'none';
        renderIcons();
    }
}

export function onStorageInfo(data) {
    if (!data) return;
    if (data.used_bytes !== undefined) {
        const usedMb = (data.used_bytes / (1024 * 1024)).toFixed(1);
        setElText('storage-total', `${usedMb} MB`);
        setElText('storage-streams', `${usedMb} MB`);
        setElText('storage-protected', `${data.protected_count || 0} треков`);
        if (data.quota_gb !== undefined) {
            const quotaSelect = document.getElementById('select-cache-quota');
            if (quotaSelect) quotaSelect.value = String(data.quota_gb);
        }
    } else {
        setElText('storage-total', `${(data.total || 0).toFixed(1)} MB`);
        if (data.tracks) setElText('storage-streams', `${data.tracks.size || '0 MB'}`);
        if (data.covers) setElText('storage-protected', `${data.covers.count || 0} обложек`);
    }
}

const settingRevisions = new Map();
const SECRET_SETTING_KEYS = new Set([
    'yandex_token', 'oauth_client_secret', 'proxy_url',
    'lastfm_api_key', 'lastfm_api_secret',
]);
function saveSetting(key, value, category, options = {}) {
    if (!window.settings) window.settings = {};
    const storageKey = `nedotify_${category}_${key}`;
    const isSecret = category === 'auth' || SECRET_SETTING_KEYS.has(String(key).toLowerCase());
    const maskInMemory = SECRET_SETTING_KEYS.has(String(key).toLowerCase()) ||
        (category === 'auth' && ['yandex_token', 'yandex_refresh_token', 'oauth_client_secret', 'proxy_url'].includes(String(key).toLowerCase()));
    const aliases = settingAliases(category, key);
    const revision = Math.max(...aliases.map(([cat,name]) => settingRevisions.get(`nedotify_${cat}_${name}`) || 0)) + 1;
    const previous = options.previous || aliases.map(([cat,name]) => [cat,name,window.settings[cat]?.[name]]);
    for (const [cat,name] of aliases) settingRevisions.set(`nedotify_${cat}_${name}`, revision);
    const hasKey = `has_${key}`;
    const previousHas = category ? window.settings[category]?.[hasKey] : undefined;
    if (category) {
        for (const [cat,name] of aliases) {
            window.settings[cat] ||= {};
            window.settings[cat][name] = maskInMemory ? '' : value;
        }
        if (maskInMemory && value) window.settings[category][hasKey] = true;
    }
    try {
        if (isSecret) localStorage.removeItem(storageKey);
        else for (const [cat,name] of aliases) localStorage.setItem(`nedotify_${cat}_${name}`, JSON.stringify(value));
    } catch (e) {}
    if (['interface', 'optimization', 'theme'].includes(category)) window.NeDotifyAppearance?.refresh();
    if (category === 'interface' && key === 'border_radius') applyBorderRadius(value);
    if (category === 'audio') applyAudioSettings(window.settings.audio || {});
    const rollback = () => {
        if (settingRevisions.get(storageKey) !== revision) return false;
        for (const [cat,name,oldValue] of previous) {
            if (oldValue === undefined) delete window.settings[cat][name];
            else window.settings[cat][name] = oldValue;
            try {
                const aliasKey = `nedotify_${cat}_${name}`;
                if (oldValue === undefined || isSecret) localStorage.removeItem(aliasKey);
                else localStorage.setItem(aliasKey, JSON.stringify(oldValue));
            } catch {}
        }
        if (previousHas === undefined) delete window.settings[category][hasKey];
        else window.settings[category][hasKey] = previousHas;
        applySettingsFromBackend(window.settings);
        showToast('Не удалось сохранить настройку. Повторите изменение.', 'error');
        return false;
    };
    try {
        if (!window.pywebview?.api?.save_setting) throw new Error('Bridge unavailable');
        return Promise.resolve(window.pywebview.api.save_setting(key, value, category)).then(result => {
            if (result === false || result?.success === false) throw new Error('Setting rejected');
            return true;
        }).catch(rollback);
    } catch {
        // Roll back after the caller's optimistic preview, even when the
        // bridge throws synchronously instead of returning a rejected promise.
        return Promise.resolve().then(rollback);
    }
}

async function enableMacosGlass() {
    // Explicitly enabling effects leaves FPS, covers and other resource choices
    // alone. Only the options that suppress the requested glass are changed.
    const pending = [saveSetting('macos_glass', true, 'interface')];
    if (!Number(savedSetting('interface', 'macos_blur', 38))) pending.push(saveSetting('macos_blur', 38, 'interface'));
    if (savedSetting('optimization', 'performance_preset', 'high') === 'low' || document.documentElement.classList.contains('perf-low')) {
        document.documentElement.classList.remove('perf-low');
        document.documentElement.classList.add('perf-medium');
        _syncActiveCard('opt-perf-preset', 'balanced');
        pending.push(saveSetting('performance_preset', 'balanced', 'optimization'));
    }
    const quality = savedSetting('optimization', 'blur_quality', 'hq');
    const resolved = quality === 'off' ? 'lq' : quality;
    const amount = Number(savedSetting('theme', 'glass_blur', 14)) || 14;
    applyBlurQuality(resolved);
    applyGlassBlur(amount);
    pending.push(saveSetting('blur_quality', resolved, 'optimization'));
    pending.push(saveSetting('glass_blur', amount, 'theme'));
    pending.push(saveSetting('resource_blur', true, 'optimization'));
    await Promise.all(pending);
    window.NeDotifyAppearance?.refresh();
}

function setElText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

export async function loadSettings() {
    await ensureSettingsPanel();
    if (window.pywebview?.api) {
        Promise.resolve(window.pywebview.api.get_storage_info()).then(onStorageInfo).catch(() => {
            showToast('Не удалось получить сведения о хранилище', 'error');
        });
    }
}

function transparencyPercent(level) {
    const value = Number(level);
    return Math.max(10, Math.min(100, Math.round(value > 0 && value <= 1 ? value * 100 : value || 80)));
}

function syncSlider(id, value, labelId, suffix = '') {
    const slider = document.getElementById(id);
    if (!slider) return;
    const min = Number(slider.min) || 0;
    const max = Number(slider.max) || 100;
    const numeric = Number(value);
    slider.value = Math.max(min, Math.min(max, Number.isFinite(numeric) ? numeric : min));
    slider.style.setProperty('--value-percent', `${(slider.value - slider.min) / (slider.max - slider.min) * 100}%`);
    if (labelId) setElText(labelId, `${slider.value}${suffix}`);
}

export function applyTransparency(level, enabled) {
    const opacity = enabled ? (transparencyPercent(level) / 100) : 1.0;
    document.documentElement.style.setProperty('--app-bg-opacity', opacity);
    const slider = document.getElementById('slider-transparency-level');
    if (slider) slider.disabled = !enabled;
}

export function applyFontSize(val) {
    const size = parseInt(val) || 16;
    const scale = size / 14;
    setElText('label-font-size', `${size}px`);
    document.documentElement.style.fontSize = `${size}px`;
    document.documentElement.style.setProperty('--font-size-base', `${size}px`);
    document.documentElement.style.setProperty('--font-size', `${size}px`);
    document.documentElement.style.setProperty('--app-font-scale', scale);
    window.NeDotifyAppearance?.refresh();

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
                saveSetting(kb.id, kb.defaultKey, 'hotkeys');
            });
            setListeningKeybind(null);
            renderKeybindsList();
            window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Горячие клавиши сброшены!', type: 'info' } }));
        });
    }
}

/**
 * Human label for a single bare KeyboardEvent.code - no modifiers.
 * Split out of formatKeyName() so the combo splitter below can reuse it.
 * @param {string} code
 * @returns {string}
 */
function formatBaseKeyName(code) {
    if (!code) return code;
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

// Modifier names exactly as parseKeyEventCombo() emits them, in the order it
// pushes them. 'Meta' is the Windows key.
const KEYBIND_MODIFIER_LABELS = {
    'Ctrl': 'Ctrl',
    'Alt': 'Alt',
    'Shift': 'Shift',
    'Meta': 'Win'
};

/**
 * Human label for a full combo string as stored in activeKeybinds.
 *
 * parseKeyEventCombo() joins the modifiers and the base key with '+', so
 * 'Ctrl+ArrowRight' is a TWO-part string. This used to look the whole string up
 * in a map that only ever contained bare codes, miss, and fall through to
 * `return code` - which is why every modified default rendered as the literal
 * text "Ctrl+ArrowRight" in the Settings list, while the unmodified 'ArrowRight'
 * correctly rendered as "Стрелка Вправо". Any binding the user made with a
 * modifier held down was equally unreadable. Split on '+' and label each part.
 */
function formatKeyName(code) {
    if (!code) return 'Не назначено';
    const parts = String(code).split('+').filter(Boolean);
    if (parts.length === 0) return 'Не назначено';

    const labels = parts.map(part =>
        Object.prototype.hasOwnProperty.call(KEYBIND_MODIFIER_LABELS, part)
            ? KEYBIND_MODIFIER_LABELS[part]
            : formatBaseKeyName(part)
    );
    return labels.join(' + ');
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
                <div class="setting-label">${escapeHtml(kb.label)}</div>
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
export function setupEfficiencyPanel() {
    const syncSwitch = (id, key, defaultVal = true) => {
        const toggle = document.getElementById(id);
        if (!toggle) return;
        let val = window.settings?.efficiency?.[key];
        if (val === undefined) {
            val = getLocalSetting(`nedotify_efficiency_${key}`, defaultVal);
        }
        toggle.classList.toggle('on', !!val);
    };

    syncSwitch('toggle-unfocus-enabled', 'unfocus_enabled', true);
    syncSwitch('toggle-unfocus-blur', 'unfocus_blur_reduction', true);
    syncSwitch('toggle-unfocus-animations', 'unfocus_disable_animations', true);
    syncSwitch('toggle-unfocus-visualizations', 'unfocus_disable_visualizations', true);

    const sliderFps = document.getElementById('slider-unfocus-fps');
    if (sliderFps) {
        let fps = window.settings?.efficiency?.unfocus_fps_limit;
        if (fps === undefined) {
            fps = getLocalSetting('nedotify_efficiency_unfocus_fps_limit', 15);
        }
        sliderFps.value = fps;
        const pct = (fps - sliderFps.min) / (sliderFps.max - sliderFps.min) * 100;
        sliderFps.style.setProperty('--value-percent', `${pct}%`);
        setElText('label-unfocus-fps', `${fps} FPS`);
    }

    const onEffChange = () => {
        window.dispatchEvent(new CustomEvent('nedotify:efficiency_setting_changed'));
        evaluateEfficiencyState();
    };

    setupToggle('toggle-unfocus-enabled', 'unfocus_enabled', 'efficiency', onEffChange);
    setupToggle('toggle-unfocus-blur', 'unfocus_blur_reduction', 'efficiency', onEffChange);
    setupToggle('toggle-unfocus-animations', 'unfocus_disable_animations', 'efficiency', onEffChange);
    setupToggle('toggle-unfocus-visualizations', 'unfocus_disable_visualizations', 'efficiency', onEffChange);
    
    setupSlider('slider-unfocus-fps', 'unfocus_fps_limit', 'efficiency', (v) => {
        setElText('label-unfocus-fps', `${v} FPS`);
        onEffChange();
    });
}

function _syncActiveCard(containerId, val) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.querySelectorAll('.opt-card').forEach(c => {
        const cVal = c.dataset.val;
        const matches = (cVal === val) ||
                        (val === 'balanced' && cVal === 'medium') ||
                        (val === 'medium' && cVal === 'balanced') ||
                        (val === 'subtle' && cVal === 'soft') ||
                        (val === 'soft' && cVal === 'subtle') ||
                        (val === 'lq' && cVal === 'mid') ||
                        (val === 'mid' && cVal === 'lq');
        c.classList.toggle('active', !!matches);
    });
}

export function applyPerformancePreset(preset, skipSave = false) {
    const root = document.documentElement;
    const normalized = (preset === 'balanced' || preset === 'medium') ? 'medium' : (preset === 'low' ? 'low' : 'high');
    
    root.classList.remove('perf-medium', 'perf-low');

    _syncActiveCard('opt-perf-preset', preset);

    if (normalized === 'low') {
        root.classList.add('perf-low');
        applyBlurQuality('off');
        applyGlowSettings('off');
        _setSlidersForPreset(15, 10, 30, skipSave);
        _syncActiveCard('opt-blur-quality', 'off');
        _syncActiveCard('opt-glow-quality', 'off');
    } else if (normalized === 'medium') {
        root.classList.add('perf-medium');
        applyBlurQuality('lq');
        applyGlowSettings('subtle');
        _setSlidersForPreset(30, 18, 45, skipSave);
        _syncActiveCard('opt-blur-quality', 'lq');
        _syncActiveCard('opt-glow-quality', 'subtle');
    } else { // high
        applyBlurQuality('hq');
        applyGlowSettings('full');
        _setSlidersForPreset(60, 24, 60, skipSave);
        _syncActiveCard('opt-blur-quality', 'hq');
        _syncActiveCard('opt-glow-quality', 'full');
    }

    if (!skipSave) {
        saveSetting('performance_preset', preset, 'optimization');
        saveSetting('blur_quality', normalized === 'low' ? 'off' : normalized === 'medium' ? 'lq' : 'hq', 'optimization');
        saveSetting('glow_quality', normalized === 'low' ? 'off' : normalized === 'medium' ? 'subtle' : 'full', 'optimization');
        const target = glassSettingTarget();
        saveSetting(target.key, normalized === 'low' ? 0 : normalized === 'medium' ? 6 : 14, target.category);
        saveSetting('resource_blur', normalized !== 'low', 'optimization');
        document.querySelector('#opt-active-resources [data-resource="blur"]')?.classList.toggle('active', normalized !== 'low');
    }
    applyAuraOrbs(savedSetting('player', 'aura_orbs_enabled', true));
    window.dispatchEvent(new CustomEvent('nedotify:performance_preset_changed', { detail: { preset: normalized } }));
}

// skipSave is threaded through so the restore path can lay the preset's values
// onto the sliders without writing them back. saveSetting() also mutates
// window.settings, so saving here during restore overwrote the user's own
// fps_* / blur / glow values with the preset's defaults on every startup --
// which also made the final applied value depend on a race with the restore
// block that runs right after this call.
function _setSlidersForPreset(vizFps, particlesFps, uiFps = 60, skipSave = false) {
    const sv = document.getElementById('slider-fps-visualizer');
    if (sv) {
        sv.value = vizFps;
        const pct = (vizFps - sv.min) / (sv.max - sv.min) * 100;
        sv.style.setProperty('--value-percent', `${pct}%`);
        setElText('label-fps-visualizer', `${vizFps} FPS`);
        setVisualizerFps(vizFps);
        if (!skipSave) saveSetting('fps_visualizer', vizFps, 'optimization');
    }
    const sp = document.getElementById('slider-fps-particles');
    if (sp) {
        sp.value = particlesFps;
        const pct = (particlesFps - sp.min) / (sp.max - sp.min) * 100;
        sp.style.setProperty('--value-percent', `${pct}%`);
        setElText('label-fps-particles', `${particlesFps} FPS`);
        setParticlesFps(particlesFps);
        if (!skipSave) saveSetting('fps_particles', particlesFps, 'optimization');
    }
    const su = document.getElementById('slider-fps-ui');
    if (su) {
        su.value = uiFps;
        const pct = (uiFps - su.min) / (su.max - su.min) * 100;
        su.style.setProperty('--value-percent', `${pct}%`);
        setElText('label-fps-ui', `${uiFps} FPS`);
        setUiFps(uiFps);
        if (!skipSave) saveSetting('fps_ui', uiFps, 'optimization');
    }
}

function applyGlassBlur(value) {
    const val = Math.max(0, Math.min(40, Number(value) || 0));
    const root = document.documentElement;
    root.style.setProperty('--glass-blur', `${val}px`);
    root.style.setProperty('--blur-sm', `${Math.round(val * 0.4)}px`);
    root.style.setProperty('--blur-md', `${val}px`);
    root.style.setProperty('--blur-lg', `${Math.round(val * 1.3)}px`);
    root.style.setProperty('--blur-xl', `${Math.round(val * 1.6)}px`);
    root.classList.toggle('blur-disabled', val === 0);
    syncSlider('slider-glass-blur', val, 'label-glass-blur', 'px');
    _syncActiveCard('opt-blur-quality', ({0:'off',4:'fast',6:'lq',14:'hq'})[val] || 'custom');
    document.querySelector('#opt-active-resources [data-resource="blur"]')?.classList.toggle('active', val > 0);
}

function glassSettingTarget() {
    return document.documentElement.dataset.uiStyle === 'macos'
        ? {key: 'macos_blur', category: 'interface'}
        : {key: 'glass_blur', category: 'theme'};
}

export function enableBlurPerformance() {
    if (savedSetting('optimization', 'performance_preset', 'balanced') !== 'low') return;
    // Keep custom FPS limits when the user explicitly enables an effect.
    document.documentElement.classList.remove('perf-low');
    document.documentElement.classList.add('perf-medium');
    _syncActiveCard('opt-perf-preset', 'balanced');
    saveSetting('performance_preset', 'balanced', 'optimization');
}

export function applyBlurQuality(val) {
    const map = {
        hq:   { sm: '8px', md: '14px', lg: '18px', xl: '24px', glass: '14px' },
        lq:   { sm: '4px', md: '6px',  lg: '8px',  xl: '10px', glass: '6px'  },
        mid:  { sm: '4px', md: '6px',  lg: '8px',  xl: '10px', glass: '6px'  },
        fast: { sm: '2px', md: '4px',  lg: '6px',  xl: '8px',  glass: '4px'  },
        off:  { sm: '0px', md: '0px',  lg: '0px',  xl: '0px',  glass: '0px'  }
    };
    const v = map[val] || map.hq;
    const root = document.documentElement;
    root.style.setProperty('--blur-sm',   v.sm);
    root.style.setProperty('--blur-md',   v.md);
    root.style.setProperty('--blur-lg',   v.lg);
    root.style.setProperty('--blur-xl',   v.xl);
    root.style.setProperty('--glass-blur', v.glass);

    root.classList.toggle('blur-disabled', val === 'off');
    _syncActiveCard('opt-blur-quality', val);

    const glassSlider = document.getElementById('slider-glass-blur');
    if (glassSlider) {
        glassSlider.value = parseInt(v.glass) || 0;
        const min = parseFloat(glassSlider.min) || 0;
        const max = parseFloat(glassSlider.max) || 30;
        const pct = ((glassSlider.value - min) / (max - min)) * 100;
        glassSlider.style.setProperty('--value-percent', `${pct}%`);
        setElText('label-glass-blur', v.glass);
    }
}

export function applyGlowSettings(val) {
    const map = {
        full:   { blur: '40px', opacity: '0.55', mode: 'full' },
        subtle: { blur: '20px', opacity: '0.35', mode: 'med' },
        soft:   { blur: '20px', opacity: '0.35', mode: 'med' },
        off:    { blur:  '0px', opacity: '0',    mode: 'off' }
    };
    const v = map[val] || map.full;
    const root = document.documentElement;
    root.style.setProperty('--player-glow-blur',    v.blur);
    root.style.setProperty('--player-glow-opacity', v.opacity);

    root.classList.remove('orbit-glow-low', 'orbit-glow-med', 'orbit-glow-off');
    if (v.mode === 'off') {
        root.classList.add('orbit-glow-off', 'orbit-glow-low');
    } else if (v.mode === 'med') {
        root.classList.add('orbit-glow-med');
    }

    _syncActiveCard('opt-glow-quality', val);
    window.dispatchEvent(new CustomEvent('nedotify:performance_preset_changed', { detail: { glow: val } }));
}

export function applyResourceToggle(res, isActive) {
    const root = document.documentElement;
    if (res === 'bg') {
        root.classList.toggle('resource-bg-disabled', !isActive);
        const orbs = document.getElementById('aura-orbs-container');
        if (orbs) orbs.style.display = isActive ? '' : 'none';
        window.dispatchEvent(new CustomEvent('nedotify:background_decoration_changed'));
    } else if (res === 'particles') {
        window.settings ||= {};
        window.settings.atmosphere ||= {};
        window.settings.atmosphere.enabled = !!isActive;
        restoreAtmosphereSettings(window.settings);
    } else if (res === 'covers') {
        root.classList.toggle('resource-covers-disabled', !isActive);
    } else if (res === 'visualizers') {
        setVisualizerEnabled(isActive, { silent: true });
    } else if (res === 'blur') {
        if (isActive) {
            const quality = savedSetting('optimization', 'blur_quality', 'hq');
            applyBlurQuality(quality === 'off' ? 'hq' : quality);
            const target = glassSettingTarget();
            applyGlassBlur(savedSetting(target.category, target.key, 14) || 14);
        } else applyBlurQuality('off');
    }
}

export function setupOptimizationPanel() {
    const setupCardGroup = (containerId, settingKey, onChange) => {
        const container = document.getElementById(containerId);
        if (!container) return;
        container.querySelectorAll('.opt-card').forEach(card => {
            if (card._boundClick) card.removeEventListener('click', card._boundClick);
            const clickHandler = async () => {
                container.querySelectorAll('.opt-card').forEach(c => c.classList.remove('active'));
                card.classList.add('active');
                if (settingKey !== 'performance_preset' && !await saveSetting(settingKey, card.dataset.val, 'optimization')) return;
                if (onChange) onChange(card.dataset.val);
            };
            card._boundClick = clickHandler;
            card.addEventListener('click', clickHandler);
        });
    };

    // 1. Presets
    setupCardGroup('opt-perf-preset', 'performance_preset', applyPerformancePreset);

    // 2. Limit state
    setupCardGroup('opt-limit-state', 'limit_state', (val) => {
        const root = document.documentElement;
        root.classList.remove('limit-state-off', 'limit-state-minimize', 'limit-state-focus');
        root.classList.add(`limit-state-${val}`);
        evaluateEfficiencyState();
    });

    // 3. Blur Quality
    setupCardGroup('opt-blur-quality', 'blur_quality', val => {
        if (val !== 'off') enableBlurPerformance();
        applyBlurQuality(val);
        const macos = document.documentElement.dataset.uiStyle === 'macos';
        saveSetting(macos ? 'macos_blur' : 'glass_blur', Number(document.getElementById('slider-glass-blur')?.value || 0), macos ? 'interface' : 'theme');
        saveSetting('resource_blur', val !== 'off', 'optimization');
        document.querySelector('#opt-active-resources [data-resource="blur"]')?.classList.toggle('active', val !== 'off');
    });

    // 4. Ambient Glow
    setupCardGroup('opt-glow-quality', 'glow_quality', val => {
        if (val !== 'off') enableBlurPerformance();
        applyGlowSettings(val);
    });

    // 5. Active resource toggles
    const resourceContainer = document.getElementById('opt-active-resources');
    if (resourceContainer) {
        resourceContainer.querySelectorAll('.opt-toggle-btn').forEach(btn => {
            if (btn._boundClick) btn.removeEventListener('click', btn._boundClick);
            const clickHandler = async () => {
                const isActive = btn.classList.toggle('active');
                const res = btn.dataset.resource;
                if (!await saveSetting(`resource_${res}`, isActive, 'optimization')) return;
                if (res === 'blur' && isActive) enableBlurPerformance();
                applyResourceToggle(res, isActive);
                if (res === 'blur' && isActive) {
                    const quality = savedSetting('optimization', 'blur_quality', 'hq');
                    saveSetting('blur_quality', quality === 'off' ? 'hq' : quality, 'optimization');
                    const target = glassSettingTarget();
                    saveSetting(target.key, Number(document.getElementById('slider-glass-blur')?.value || 14), target.category);
                }
            };
            btn._boundClick = clickHandler;
            btn.addEventListener('click', clickHandler);
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
        setUiFps(v);
    });

    // 8. Restore all saved optimization settings from localStorage/window.settings
    try {
        let preset = window.settings?.optimization?.performance_preset;
        if (!preset) preset = getLocalSetting('nedotify_optimization_performance_preset', 'high');

        let limitState = window.settings?.optimization?.limit_state;
        if (!limitState) limitState = getLocalSetting('nedotify_optimization_limit_state', 'minimize');

        let blur = window.settings?.optimization?.blur_quality;
        if (!blur) blur = getLocalSetting('nedotify_optimization_blur_quality', 'hq');

        let glow = window.settings?.optimization?.glow_quality;
        if (!glow) glow = getLocalSetting('nedotify_optimization_glow_quality', 'full');

        let fpsPart = window.settings?.optimization?.fps_particles;
        if (fpsPart === undefined) fpsPart = getLocalSetting('nedotify_optimization_fps_particles', 24);

        let fpsViz = window.settings?.optimization?.fps_visualizer;
        if (fpsViz === undefined) fpsViz = getLocalSetting('nedotify_optimization_fps_visualizer', 30);

        let fpsUi = window.settings?.optimization?.fps_ui;
        if (fpsUi === undefined) fpsUi = getLocalSetting('nedotify_optimization_fps_ui', 60);

        _syncActiveCard('opt-perf-preset', preset);
        _syncActiveCard('opt-limit-state', limitState);
        _syncActiveCard('opt-blur-quality', blur);
        _syncActiveCard('opt-glow-quality', glow);

        applyPerformancePreset(preset, true);

        const root = document.documentElement;
        root.classList.remove('limit-state-off', 'limit-state-minimize', 'limit-state-focus');
        root.classList.add(`limit-state-${limitState}`);

        applyBlurQuality(blur);
        applyGlowSettings(glow);

        const sp = document.getElementById('slider-fps-particles');
        if (sp) {
            sp.value = fpsPart;
            const pct = (sp.value - sp.min) / (sp.max - sp.min) * 100;
            sp.style.setProperty('--value-percent', `${pct}%`);
            setElText('label-fps-particles', `${sp.value} FPS`);
            setParticlesFps(sp.value);
        }

        const sv = document.getElementById('slider-fps-visualizer');
        if (sv) {
            sv.value = fpsViz;
            const pct = (sv.value - sv.min) / (sv.max - sv.min) * 100;
            sv.style.setProperty('--value-percent', `${pct}%`);
            setElText('label-fps-visualizer', `${sv.value} FPS`);
            setVisualizerFps(sv.value);
        }

        const su = document.getElementById('slider-fps-ui');
        if (su) {
            su.value = fpsUi;
            const pct = (su.value - su.min) / (su.max - su.min) * 100;
            su.style.setProperty('--value-percent', `${pct}%`);
            setElText('label-fps-ui', `${su.value} FPS`);
            setUiFps(su.value);
        }

        // Sync & apply resource toggle buttons
        ['bg', 'particles', 'covers', 'visualizers', 'blur'].forEach(res => {
            let val = window.settings?.optimization?.[`resource_${res}`];
            if (val === undefined) {
                val = getLocalSetting(`nedotify_optimization_resource_${res}`, true);
            }
            if (res === 'particles') val = !!val && savedSetting('atmosphere', 'enabled', false);
            if (res === 'visualizers') val = !!val && savedSetting('ui', 'cover_visualizer', false);
            const btn = document.querySelector(`#opt-active-resources [data-resource="${res}"]`);
            if (btn) btn.classList.toggle('active', !!val);
            applyResourceToggle(res, !!val);
        });
        if (savedSetting('optimization', 'resource_blur', true)) {
            const target = glassSettingTarget();
            applyGlassBlur(savedSetting(target.category, target.key, 14));
        }
    } catch(e) {}
}

const CUSTOM_COLOR_PROPS={primary:'--primary',accent:'--accent',bg:'--bg-main',text:'--text-main',card:'--bg-card',border:'--border',dim:'--text-dim',focus:'--focus'};
function setCustomColor(key,value) {
    const prop=CUSTOM_COLOR_PROPS[key];if(!prop)return;
    const root=document.documentElement;
    if(!/^#[\da-f]{6}$/i.test(value || '')){root.style.removeProperty(prop);if(['primary','accent'].includes(key))root.style.removeProperty(`${prop}-rgb`);return;}
    root.style.setProperty(prop,value);
    if(['primary','accent'].includes(key))root.style.setProperty(`${prop}-rgb`,[1,3,5].map(i=>parseInt(value.slice(i,i+2),16)).join(', '));
}
function restoreCustomPalette(theme={}) {
    const enabled=theme?.custom_palette_enabled===true;
    if(!enabled)for(const key of Object.keys(CUSTOM_COLOR_PROPS))setCustomColor(key,'');
    const toggle=document.getElementById('custom-palette-enabled');if(toggle)toggle.checked=enabled;
    const computed=getComputedStyle(document.documentElement);
    for(const [key,prop] of Object.entries(CUSTOM_COLOR_PROPS)){
        const value=enabled?(theme?.[`color_${key}`] ?? (['primary','accent'].includes(key)?theme?.[`custom_${key}`]:undefined) ?? ''):'';
        if(value)setCustomColor(key,value);
        else if(theme && Object.prototype.hasOwnProperty.call(theme,`color_${key}`))setCustomColor(key,'');
        const picker=document.getElementById(`picker-color-${key}`);
        if(picker){const active=value || computed.getPropertyValue(prop).trim();const rgb=active.match(/^rgb\((\d+),?\s+(\d+),?\s+(\d+)\)$/);picker.value=/^#[\da-f]{6}$/i.test(active)?active:rgb?'#'+rgb.slice(1).map(n=>Number(n).toString(16).padStart(2,'0')).join(''):picker.defaultValue;}
    }
    syncCustomColorFields();
}
function activateCustomPalette() {
    if(window.settings?.theme?.custom_palette_enabled===true)return;
    // Initialise from the currently visible palette, never from dormant legacy editor values.
    for(const key of Object.keys(CUSTOM_COLOR_PROPS)){const picker=document.getElementById(`picker-color-${key}`);if(picker)saveSetting(`color_${key}`,picker.value,'theme');}
    saveSetting('custom_palette_enabled',true,'theme');
    const toggle=document.getElementById('custom-palette-enabled');if(toggle)toggle.checked=true;
}
function resetCustomPalette(notify=true) {
    saveSetting('custom_palette_enabled',false,'theme');
    for(const key of Object.keys(CUSTOM_COLOR_PROPS)){setCustomColor(key,'');saveSetting(`color_${key}`,'','theme');}
    saveSetting('custom_primary','','theme');saveSetting('custom_accent','','theme');
    restoreCustomPalette(window.settings?.theme);syncCustomColorFields();
    if(notify)showToast('Цвета возвращены к выбранной теме','success');
}
function getSavedCustomThemes(theme=window.settings?.theme) {
    let local=[];try{local=JSON.parse(localStorage.getItem('nedotify_custom_themes') || '[]');}catch{}
    const backend=theme?.custom_themes;
    const list=Array.isArray(backend)?backend:local;
    return Array.isArray(list)?list.filter(item=>item && typeof item.name==='string' && item.palette && typeof item.palette==='object'):[];
}
function renderSavedCustomThemes(theme=window.settings?.theme) {
    const container=document.getElementById('saved-custom-themes');if(!container)return;
    container.replaceChildren();
    getSavedCustomThemes(theme).forEach(item=>{
        const button=document.createElement('button');button.className='saved-theme-button';button.type='button';button.textContent=item.name;button.title=`Применить тему «${item.name}»`;
        const swatch=document.createElement('span');if(/^#[\da-f]{6}$/i.test(item.palette['--primary'] || ''))swatch.style.backgroundColor=item.palette['--primary'];button.prepend(swatch);
        button.onclick=()=>{
            activateCustomPalette();
            for(const [key,prop] of Object.entries(CUSTOM_COLOR_PROPS)){const value=item.palette[prop];if(!/^#[\da-f]{6}$/i.test(value || ''))continue;setCustomColor(key,value);saveSetting(`color_${key}`,value,'theme');if(['primary','accent'].includes(key))saveSetting(`custom_${key}`,value,'theme');}
            restoreCustomPalette(window.settings?.theme);document.getElementById('input-custom-theme-name').value=item.name;
        };container.appendChild(button);
    });
}



function applyThemeMode(mode) {
    if (mode === 'system') {
        const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
    } else {
        document.documentElement.setAttribute('data-theme', mode);
    }
    applyAuraOrbs(savedSetting('player', 'aura_orbs_enabled', true));
}





export function applyCustomBg(bgDataUrl, blurPx = 0, dimPct = 30) {
    bgDataUrl = window.NeDotifyAssets?.resolveBackground(bgDataUrl) ?? bgDataUrl;
    blurPx = Math.max(0, Math.min(16, Number(blurPx) || 0));
    let bgLayer = document.getElementById('custom-bg-layer');
    let dimLayer = document.getElementById('custom-bg-dim-layer');
    const previewRow = document.getElementById('row-custom-bg-preview');
    const previewImg = document.getElementById('bg-image-preview');

    if (!bgDataUrl) {
        document.documentElement.classList.remove('has-custom-bg');
        document.body.classList.remove('has-custom-bg');
        const appCont = document.getElementById('app-container');
        if (appCont) appCont.classList.remove('has-custom-bg');
        if (bgLayer) bgLayer.style.display = 'none';
        if (dimLayer) dimLayer.style.display = 'none';
        if (previewRow) previewRow.style.display = 'none';
        if (previewImg) previewImg.style.backgroundImage = '';
        try {
            localStorage.removeItem('nedotify_theme_custom_bg_image');
        } catch(e) {}
        window.NeDotifyAppearance?.refresh();
        return;
    }

    document.documentElement.classList.add('has-custom-bg');
    document.body.classList.add('has-custom-bg');
    const appCont = document.getElementById('app-container');
    if (appCont) appCont.classList.add('has-custom-bg');

    try {
        localStorage.setItem('nedotify_theme_custom_bg_image', JSON.stringify(bgDataUrl));
        localStorage.setItem('nedotify_theme_bg_blur', JSON.stringify(blurPx || 0));
        localStorage.setItem('nedotify_theme_bg_dim', JSON.stringify(dimPct !== undefined ? dimPct : 30));
    } catch(e) {}

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
    bgLayer.style.backgroundImage = `url(${JSON.stringify(bgDataUrl)})`;
    bgLayer.style.filter = `blur(${blurPx || 0}px)`;
    bgLayer.style.transform = `scale(${blurPx > 0 ? 1.06 : 1})`;

    dimLayer.style.display = 'block';
    dimLayer.style.backgroundColor = `rgba(0, 0, 0, ${(dimPct !== undefined ? dimPct : 30) / 100})`;

    if (previewRow) previewRow.style.display = 'flex';
    if (previewImg) previewImg.style.backgroundImage = `url(${JSON.stringify(bgDataUrl)})`;
    window.NeDotifyAppearance?.refresh();
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

    // Logo. Write into the .sidebar-logo-icon slot only: the rail title is the
    // collapse/expand toggle and owns two .sidebar-logo-text variants
    // ("NeDotify" / the collapsed "N"). Replacing logoEl.innerHTML wholesale
    // used to leave a bare text node here, which silently destroyed that
    // structure the first time a user switched icon packs.
    const logoEl = document.querySelector('.sidebar-logo');
    if (logoEl) {
        const iconSlot = logoEl.querySelector('.sidebar-logo-icon') || logoEl;
        iconSlot.innerHTML = `<i data-lucide="${map.logo}" style="width:24px;height:24px;filter:drop-shadow(0 0 10px ${pack.color});"></i>`;
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
        ['border-color','box-shadow','background'].forEach(property => card.style.removeProperty(property));
    });
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
    root.classList.remove('player-style-default', 'player-style-vinyl');
    root.classList.add(`player-style-${style}`);
}

export function syncAuraOrbsState() {
    const el = document.getElementById('aura-orbs-container');
    if (!el || el.classList.contains('disabled')) return;
    const isPlaying = document.body.classList.contains('playback-playing');
    const isWindowFocused = !document.hidden && !document.body.classList.contains('unfocused-animations-disabled');
    const shouldPause = !isPlaying || !isWindowFocused || document.documentElement.dataset.uiStyle === 'macos';
    el.classList.toggle('paused', shouldPause);
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
    if (!shouldDisable) {
        syncAuraOrbsState();
    }
}

// Window visibility & playback state listeners for Aura Orbs power saving
window.addEventListener('blur', syncAuraOrbsState);
window.addEventListener('focus', syncAuraOrbsState);
document.addEventListener('visibilitychange', syncAuraOrbsState);
document.addEventListener('nedotify:state_changed', (e) => {
    document.body.classList.toggle('playback-playing', e.detail === 'playing');
    document.body.classList.toggle('playback-paused', e.detail !== 'playing');
    syncAuraOrbsState();
});
document.addEventListener('nedotify:efficiency_state', syncAuraOrbsState);

function normalizeProgressStyle(type) {
    if (type === 'solid' || type === 'thin' || type === 'ios') return 'solid';
    return 'panel';
}

function normalizeProgressColor(color) {
    return typeof color === 'string' && /^#[\da-f]{6}$/i.test(color) ? color.toLowerCase() : '#10d6a3';
}

export function applySliderType(type) {
    const root = document.documentElement;
    const style = normalizeProgressStyle(type);
    root.classList.remove('slider-type-default', 'slider-type-thin', 'slider-type-ios', 'slider-type-wave', 'slider-type-bars', 'slider-type-solid', 'slider-type-hidden', 'slider-type-panel');
    root.classList.add(`slider-type-${style}`);
    root.dataset.progressStyle = style;
    document.dispatchEvent(new CustomEvent('nedotify:slider_type_changed', { detail: { type: style } }));
}

function applyProgressColor(color) {
    const normalized = normalizeProgressColor(color);
    document.documentElement.style.setProperty('--player-progress-color', normalized);
    document.dispatchEvent(new Event('nedotify:progress_appearance_changed'));
    return normalized;
}

function applyProgressTransparency(value) {
    const numeric = Number(value);
    const transparency = Math.min(80, Math.max(0, Number.isFinite(numeric) ? numeric : 18));
    document.documentElement.dataset.progressTransparency = String(transparency);
    document.documentElement.style.setProperty('--player-progress-opacity', String(1 - transparency / 100));
    document.dispatchEvent(new Event('nedotify:progress_appearance_changed'));
    return transparency;
}

export function upgradeQueuePanelPreferences(player) {
    if (Number(player.queue_panel_version || 0) >= 1) return false;
    player.show_queue = true;
    player.queue_panel_version = 1;
    return true;
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

// Repaint the Player tab's cards and toggles from the saved values.
//
// This runs twice on a cold start: once from setupPlayerSettingsPanel() (before
// the bridge has answered, so it can only see localStorage) and again from
// applySettingsFromBackend() once the backend values are known. Without the
// second call the toggles kept whatever the first pass guessed, so a cleared
// localStorage left the Player tab showing "queue on" while the queue was
// actually hidden. applyShowQueue() and friends change behaviour but not the
// toggle markup, so the visual state has to be re-synced explicitly.
function syncPlayerSettingsUI() {
    const syncActiveCard = (containerId, val) => {
        const c = document.getElementById(containerId);
        if (c) {
            c.querySelectorAll('.opt-card').forEach(card => {
                card.classList.toggle('active', card.dataset.val === val);
            });
        }
    };
    const syncToggleVisual = (id, val) => {
        const t = document.getElementById(id);
        if (t) t.classList.toggle('on', !!val);
    };

    syncActiveCard('opt-title-align', savedSetting('player', 'title_align', 'left'));
    syncActiveCard('opt-player-style', savedSetting('player', 'player_style', 'default'));
    syncActiveCard('opt-slider-type', normalizeProgressStyle(savedSetting('player', 'slider_type', 'bars')));
    syncActiveCard('opt-queue-pos', savedSetting('player', 'queue_pos', 'bottom'));
    syncActiveCard('opt-queue-view', savedSetting('player', 'queue_view', 'normal'));
    syncActiveCard('opt-mp-progress', savedSetting('player', 'mp_progress', 'line'));
    syncActiveCard('opt-mp-cover-shape', savedSetting('player', 'mp_cover_shape', 'default'));
    syncActiveCard('opt-mp-shape', savedSetting('player', 'mp_shape', 'default'));
    document.querySelectorAll('#mp-pos-btn-group .opt-card-btn, #opt-mp-pos .opt-card-btn').forEach(button => {
        const active = button.dataset.pos === savedSetting('player','mp_pos','bottom-right');
        button.classList.toggle('active', active);
        button.style.background = active ? 'var(--primary)' : 'var(--bg-card)';
        button.style.color = active ? 'var(--primary-fg)' : 'var(--text-main)';
        button.style.borderColor = active ? 'var(--primary)' : 'var(--border)';
    });

    syncToggleVisual('toggle-show-queue', savedSetting('player', 'show_queue', true));
    syncToggleVisual('toggle-compact-queue-btn', savedSetting('player', 'compact_queue_btn', true));
    syncToggleVisual('toggle-next-track-preview', savedSetting('player', 'next_track_preview', true));
    syncToggleVisual('toggle-player-prefetch', savedSetting('player', 'player_prefetch', true));
    syncToggleVisual('toggle-auto-download-favorites', savedSetting('storage', 'auto_download_favorites', false));
    syncToggleVisual('toggle-aura-orbs', savedSetting('player', 'aura_orbs_enabled', true));

    const progressColor = document.getElementById('player-progress-color');
    if (progressColor) progressColor.value = normalizeProgressColor(savedSetting('player', 'progress_color', '#10d6a3'));
    const progressTransparency = document.getElementById('player-progress-transparency');
    const transparencyValue = Math.min(80, Math.max(0, Number(savedSetting('player', 'progress_transparency', 18)) || 0));
    if (progressTransparency) progressTransparency.value = String(transparencyValue);
    if (progressTransparency) progressTransparency.style.setProperty('--value-percent', `${transparencyValue / 80 * 100}%`);
    const transparencyOutput = document.getElementById('player-progress-transparency-value');
    if (transparencyOutput) transparencyOutput.value = `${transparencyValue}%`;
}




// ─── WORKSHOP (МАСТЕРСКАЯ) MODULE ───






// ==========================================================================
// FEATURE 4: Settings Live Search Filter Engine
// ==========================================================================



// The runtime restores appearance/audio immediately. Panel catalogues and controls
// are fetched on intent or after app readiness, outside the bridge startup gate.
let settingsPanelPromise = null;
let settingsPanelReady = false;
let settingsIntentBound = false;
let settingsPanelDisposed = false;
let settingsWarmHandle = null;
let settingsWarmIsIdle = false;
export function ensureSettingsPanel() {
    if (settingsPanelDisposed) return Promise.resolve(null);
    if (!settingsPanelPromise) {
        settingsPanelPromise = import('./settings-panel.js').then(panel => {
            if (settingsPanelDisposed) return null;
            panel.initSettings();
            applySettingsFromBackend(window.settings);
            window.NeDotifyAppearance?.refresh();
            settingsPanelReady = true;
            return panel;
        }).catch(error => {
            settingsPanelPromise = null;
            throw error;
        });
    }
    return settingsPanelPromise;
}

export function initSettings() {
    if (settingsIntentBound) return;
    settingsIntentBound = true;
    // Remove legacy secret mirrors written by older versions.
    try {
        for (let index = localStorage.length - 1; index >= 0; index--) {
            const key = localStorage.key(index);
            if (key?.startsWith('nedotify_auth_') ||
                key === 'nedotify_services_lastfm_api_key' || key === 'nedotify_services_lastfm_api_secret') {
                localStorage.removeItem(key);
            }
        }
    } catch {}
    window.NeDotifyAppearance?.init(saveSetting, enableMacosGlass);
    window.addEventListener('nedotify:appearance_changed', syncAuraOrbsState);
    window.addEventListener('nedotify:appearance_changed', () => {
        if (document.documentElement.dataset.uiStyle !== 'macos') {
            applyGlassBlur(savedSetting('theme', 'glass_blur', 15));
            applyFontSize(savedSetting('theme', 'font_size', 14));
        }
        renderFontCards(document.querySelector('.font-cat-btn.active')?.dataset.cat || 'system');
    });

    // Backend may push theme changes (theme string) at runtime — re-apply the active theme
    window.addEventListener('nedotify:theme_changed', (e) => {
        applyThemeMode?.(String(e.detail ?? getLocalSetting('theme_mode', 'system')));
    });

    const warm = () => ensureSettingsPanel().catch(error => console.error('Settings panel failed:', error));
    document.querySelectorAll('[data-page="settings"]').forEach(button => {
        button.addEventListener('pointerenter', warm, { once: true });
        button.addEventListener('focus', warm, { once: true });
    });
    // Preserve the first interaction if the user opens settings before prewarm.
    const view = document.getElementById('view-settings');
    // Keep native typing, focus navigation and Escape intact while loading.
    view?.addEventListener('keydown', warm, true);
    for (const type of ['click', 'input', 'change']) {
        view?.addEventListener(type, event => {
            if (settingsPanelReady || settingsPanelDisposed || event.target === view) return;
            event.stopImmediatePropagation();
            if (type === 'click') event.preventDefault();
            const target = event.target;
            const value = target.value;
            const checked = target.checked;
            const replay = new event.constructor(event.type, event);
            ensureSettingsPanel().then(() => {
                if (settingsPanelDisposed || !settingsPanelReady || !target.isConnected) return;
                if (type === 'input' || type === 'change') {
                    target.value = value;
                    if (typeof checked === 'boolean') target.checked = checked;
                }
                target.dispatchEvent(replay);
            }).catch(error => console.error('Settings interaction failed:', error));
        }, true);
    }
    window.addEventListener('nedotify:app_ready', () => {
        if (settingsPanelDisposed || settingsPanelReady) return;
        settingsWarmIsIdle = !!window.requestIdleCallback;
        const run = () => { settingsWarmHandle = null; warm(); };
        settingsWarmHandle = settingsWarmIsIdle
            ? window.requestIdleCallback(run, { timeout: 1000 }) : setTimeout(run, 0);
    }, { once: true });
    window.addEventListener('pagehide', () => {
        settingsPanelDisposed = true;
        if (settingsWarmHandle !== null) {
            if (settingsWarmIsIdle) window.cancelIdleCallback?.(settingsWarmHandle);
            else clearTimeout(settingsWarmHandle);
            settingsWarmHandle = null;
        }
    }, { once: true });
}

// Shared runtime helpers used by the deferred settings panel.
export { PRESET_THEMES, activateCustomPalette, applyGlassBlur, applyProgressColor, applyProgressTransparency, applyThemeMode, enableMacosGlass, getLocalSetting, getSavedCustomThemes, normalizeProgressColor, normalizeProgressStyle, renderFontCards, renderSavedCustomThemes, renderThemeGrid, resetCustomPalette, restoreCustomPalette, saveSetting, savedSetting, setElText, setupSlider, setupToggle, syncPlayerSettingsUI, syncSwitch };
