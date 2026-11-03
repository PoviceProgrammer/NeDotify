// Presentation only. Loaded before first paint; no player/bridge imports.
(() => {
    const root = document.documentElement;
    const system = window.matchMedia('(prefers-color-scheme: dark)');
    const read = (key, fallback) => {
        try { return JSON.parse(localStorage.getItem(`nedotify_interface_${key}`)) ?? fallback; }
        catch { return fallback; }
    };
    let style = read('ui_style', 'current');
    let mode = read('macos_mode', 'system');
    let save;
    let initialized = false;
    let enableEffects;
    let backgroundRequest;
    let backgroundImage;
    let backgroundTimer;
    let backgroundState = 'default';
    const setting = (category, key, fallback) => {
        if (window.settings?.[category]?.[key] !== undefined) return window.settings[category][key];
        try { return JSON.parse(localStorage.getItem(`nedotify_${category}_${key}`)) ?? fallback; }
        catch { return fallback; }
    };
    const setProperty = (name, value) => {
        if (root.style.getPropertyValue(name) !== value) root.style.setProperty(name, value);
    };

    // Keep the hue of the selected theme, adjusting brightness for AA text.
    function syncAccent() {
        if (style !== 'macos') return;
        const raw = getComputedStyle(root).getPropertyValue('--primary-rgb').trim();
        let rgb = raw.split(',').map(Number);
        if (rgb.length !== 3 || rgb.some(v => !Number.isFinite(v))) rgb = [0, 122, 255];
        const luminance = c => c.map(v => { v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; })
            .reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
        const dark = root.dataset.macosMode === 'dark';
        const surface = luminance(dark ? [40, 40, 42] : [245, 245, 247]);
        for (let i = 0; i < 100; i++) {
            const l = luminance(rgb);
            if ((Math.max(l, surface) + .05) / (Math.min(l, surface) + .05) >= 4.5) break;
            rgb = rgb.map(v => dark ? Math.min(255, v + 3) : Math.max(0, v - 3));
        }
        rgb = rgb.map(Math.round);
        setProperty('--mac-accent', `rgb(${rgb.join(', ')})`);
        setProperty('--mac-accent-rgb', rgb.join(', '));
        setProperty('--mac-accent-fg', luminance(rgb) > .179 ? '#000000' : '#ffffff');
    }

    function syncControls() {
        document.querySelectorAll('[data-ui-style-choice]').forEach(button => {
            button.setAttribute('aria-pressed', String(button.dataset.uiStyleChoice === style));
        });
        document.querySelectorAll('[data-macos-mode-choice]').forEach(button => {
            button.setAttribute('aria-pressed', String(button.dataset.macosModeChoice === mode));
        });
        const options = document.getElementById('macos-appearance-options');
        if (options) options.hidden = style !== 'macos';
        const note = document.getElementById('macos-palette-note');
        if (note) note.hidden = style !== 'macos';
        for (const key of ['bg','text','card','border','dim','focus']) {
            for (const id of [`picker-color-${key}`,`picker-color-${key}-hex`]) {
                const input = document.getElementById(id);
                if (input) input.disabled = style === 'macos';
            }
        }
    }

    function apply(nextStyle = style, nextMode = mode) {
        style = nextStyle === 'macos' ? 'macos' : 'current';
        mode = ['light', 'dark', 'system'].includes(nextMode) ? nextMode : 'system';
        root.dataset.uiStyle = style;
        root.dataset.macosMode = mode === 'system' ? (system.matches ? 'dark' : 'light') : mode;
        syncAccent();
        syncControls();
        syncResources();
        window.dispatchEvent(new Event('nedotify:appearance_changed'));
    }

    function restore(settings) {
        if (settings?.interface) {
            apply(settings.interface.ui_style ?? style, settings.interface.macos_mode ?? mode);
            // The backend is authoritative, including when WebView storage was cleared.
            try {
                localStorage.setItem('nedotify_interface_ui_style', JSON.stringify(style));
                localStorage.setItem('nedotify_interface_macos_mode', JSON.stringify(mode));
            } catch { /* Storage may be disabled; the durable backend still works. */ }
        }
        syncResources();
        syncAccent();
        syncProfile();
        syncBackdrop();
    }

    function syncResources() {
        const glass = setting('interface', 'macos_glass', true) !== false;
        // Surface alpha is independent of the expensive backdrop blur.
        root.dataset.macosGlass = String(glass);
        const strength = Math.max(0, Math.min(40, Number(setting('interface', 'macos_blur', 38)) || 0));
        setProperty('--mac-panel-blur', `${strength}px`);
        const family = setting('interface', 'macos_font_family', 'system');
        const systemFont = '-apple-system, BlinkMacSystemFont, "Segoe UI Variable Text", "Segoe UI", sans-serif';
        setProperty('--mac-font', !family || family === 'system' ? systemFont : `${family}, "Segoe UI", sans-serif`);
        const fontSize = Math.max(12, Math.min(22, Number(setting('interface', 'macos_font_size', 14)) || 14));
        setProperty('--mac-font-scale', String(fontSize / 14));
        const low = root.classList.contains('perf-low') || setting('optimization', 'performance_preset', 'high') === 'low';
        const configuredOff = setting('optimization', 'resource_blur', true) === false || setting('optimization', 'blur_quality', 'hq') === 'off';
        if (style === 'macos') {
            root.classList.toggle?.('blur-disabled', configuredOff || strength === 0);
        } else if (!configuredOff) {
            const standardBlur = Number(setting('theme', 'glass_blur', 15));
            root.classList.toggle?.('blur-disabled', standardBlur === 0);
        } else {
            // This runs inside the root's class MutationObserver. Adding an
            // existing token still emits a mutation; toggle is a no-op when set.
            root.classList.toggle?.('blur-disabled', true);
        }
        const disabled = configuredOff || root.classList.contains('blur-disabled');
        const battery = root.classList.contains('battery-saver-active');
        const unfocused = document.body?.classList.contains('unfocused-blur-disabled');
        const supported = !root.classList.contains('no-backdrop') && (window.CSS?.supports?.('backdrop-filter', 'blur(1px)') ?? true);
        const enabled = glass && strength > 0 && !low && !disabled && !battery && !unfocused && supported;
        const value = enabled ? 'true' : 'false';
        if (root.dataset.macosTransparency !== value) root.dataset.macosTransparency = value;
        const bg = setting('optimization', 'resource_bg', true) !== false;
        root.dataset.macosBackground = String(bg);
        const checkbox = document.getElementById('macos-glass-enabled');
        if (checkbox) checkbox.checked = glass;
        const status = document.getElementById('macos-effects-status');
        if (status) status.textContent = !supported ? 'Размытие недоступно в этой среде. Используются непрозрачные панели.' :
            !glass ? 'Матовые панели выключены.' : !strength ? 'Размытие установлено в 0 px. Увеличьте его в разделе «Эффект стекла».' : low ? 'Размытие отключено профилем «Экономия». Фоновое изображение остаётся доступным.' :
            disabled ? 'Размытие отключено в настройках эффективности.' : battery ? 'Размытие временно отключено экономией батареи.' :
            unfocused ? 'Размытие временно отключено для неактивного окна.' : 'Размытие и полупрозрачные панели включены.';
        const enable = document.getElementById('macos-enable-effects');
        if (enable) enable.hidden = !(supported && (low || disabled) && !battery);
        const bgStatus = document.getElementById('macos-background-status');
        if (bgStatus) bgStatus.textContent = !bg ? 'Фон выключен в настройках эффективности.' :
            backgroundState === 'failed' ? 'Выбранный фон недоступен. Используется встроенный фон macOS.' :
            backgroundState === 'loading' ? 'Загрузка выбранного фона… Пока используется встроенный фон macOS.' : '';
        if (style === 'macos') {
            const fontSlider = document.getElementById('slider-font-size');
            if (fontSlider && Number(fontSlider.value) !== fontSize) {
                fontSlider.value = fontSize;
                fontSlider.style.setProperty('--value-percent', `${(fontSize - 12) / 10 * 100}%`);
            }
            const fontLabel = document.getElementById('label-font-size');
            if (fontLabel && fontLabel.textContent !== `${fontSize}px`) fontLabel.textContent = `${fontSize}px`;
            const slider = document.getElementById('slider-glass-blur');
            if (slider && Number(slider.value) !== strength) {
                slider.value = strength;
                slider.style.setProperty('--value-percent', `${strength / 40 * 100}%`);
            }
            const label = document.getElementById('label-glass-blur');
            if (label && label.textContent !== `${strength}px`) label.textContent = `${strength}px`;
        }
    }

    function syncProfile() {
        const name = document.getElementById('macos-profile-name');
        if (name) name.textContent = window.settings?.personalization?.nickname || 'NeDotify';
        const source = document.getElementById('home-avatar-img');
        const target = document.getElementById('macos-profile-avatar');
        if (target && source) {
            target.hidden = source.hidden || !source.getAttribute('src');
            if (!target.hidden) target.src = source.src;
        }
    }

    function syncBackdrop() {
        const backdrop = document.getElementById('macos-backdrop');
        if (!backdrop) return;
        const raw = setting('theme', 'custom_bg_image', '');
        const source = typeof raw === 'string' ? raw.trim() : '';
        const url = window.NeDotifyAssets?.resolveBackground(source) ?? source;
        const custom = url && backgroundState === 'loaded' && url === backgroundRequest;
        const blur = Math.max(0, Math.min(16, Number(setting('theme', 'bg_blur', 0)) || 0));
        const dim = Math.max(0, Math.min(95, Number(setting('theme', 'bg_dim', 30)) || 0));
        setProperty('--mac-wallpaper-blur', `${custom ? blur : 0}px`);
        setProperty('--mac-wallpaper-dim', String(custom ? dim / 100 : .1));
        if (url === backgroundRequest) return;
        backgroundRequest = url;
        clearTimeout(backgroundTimer);
        if (backgroundImage) backgroundImage.onload = backgroundImage.onerror = null;
        backdrop.style.backgroundImage = '';
        backgroundState = url ? 'loading' : 'default';
        if (!url) { syncResources(); return; }
        // Keep the bundled wallpaper until a custom image really loads. A dead
        // remote wallpaper must not replace the whole scene with an empty URL.
        const image = new Image();
        backgroundImage = image;
        const finish = loaded => {
            if (backgroundImage !== image) return;
            clearTimeout(backgroundTimer);
            image.onload = image.onerror = null;
            backgroundState = loaded ? 'loaded' : 'failed';
            backdrop.style.backgroundImage = loaded ? `linear-gradient(rgba(0,0,0,var(--mac-wallpaper-dim)),rgba(0,0,0,var(--mac-wallpaper-dim))),url(${JSON.stringify(url)})` : '';
            syncBackdrop();
            syncResources();
        };
        image.onload = () => finish(true);
        image.onerror = () => finish(false);
        backgroundTimer = setTimeout(() => finish(false), 8000);
        image.src = url;
        syncResources();
    }

    function initFeedNavigation() {
        for (const id of ['home-history', 'home-top-tracks']) {
            const scroll = document.getElementById(id);
            const header = scroll?.closest('.feed-section')?.querySelector('.home-section-header');
            if (!header) continue;
            const nav = document.createElement('div');
            nav.className = 'macos-feed-nav';
            const buttons = [-1, 1].map(direction => {
                const button = document.createElement('button');
                button.type = 'button';
                button.setAttribute('aria-label', direction < 0 ? 'Прокрутить список назад' : 'Прокрутить список вперёд');
                button.innerHTML = `<svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="${direction < 0 ? 'M12 5L7 10l5 5' : 'M8 5l5 5-5 5'}"/></svg>`;
                button.addEventListener('click', () => scroll.scrollBy({
                    left: direction * scroll.clientWidth * .75,
                    behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'
                }));
                nav.appendChild(button);
                return button;
            });
            const sync = () => {
                buttons[0].disabled = scroll.scrollLeft <= 1;
                buttons[1].disabled = scroll.scrollLeft + scroll.clientWidth >= scroll.scrollWidth - 1;
            };
            header.appendChild(nav);
            scroll.addEventListener('scroll', sync, { passive: true });
            new ResizeObserver(sync).observe(scroll);
            new MutationObserver(sync).observe(scroll, { childList: true });
            sync();
        }
    }

    function init(persist, enableGlass) {
        save = persist;
        enableEffects = enableGlass;
        if (initialized) return;
        initialized = true;
        initFeedNavigation();
        document.querySelectorAll('[data-ui-style-choice], [data-macos-mode-choice]').forEach(button => {
            button.addEventListener('click', async () => {
                const isStyle = button.hasAttribute('data-ui-style-choice');
                const key = isStyle ? 'ui_style' : 'macos_mode';
                const value = isStyle ? button.dataset.uiStyleChoice : button.dataset.macosModeChoice;
                apply(isStyle ? value : style, isStyle ? mode : value);
                // Serialize user choices until the existing persistence call settles.
                const choices = document.querySelectorAll('[data-ui-style-choice], [data-macos-mode-choice]');
                choices.forEach(item => { item.disabled = true; });
                try { await save(key, value, 'interface'); }
                finally { choices.forEach(item => { item.disabled = false; }); }
            });
        });
        document.getElementById('macos-search-form')?.addEventListener('submit', event => {
            event.preventDefault();
            window.showPage('search');
            const input = document.getElementById('search-input');
            input.value = document.getElementById('macos-search-input').value.trim();
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.focus();
        });
        document.getElementById('macos-glass-enabled')?.addEventListener('change', async event => {
            const checkbox = event.target;
            checkbox.disabled = true;
            try {
                const pending = checkbox.checked && root.dataset.macosTransparency === 'false' && enableEffects
                    ? enableEffects() : save('macos_glass', checkbox.checked, 'interface');
                syncResources();
                await pending;
            } finally { checkbox.disabled = false; }
        });
        document.getElementById('macos-enable-effects')?.addEventListener('click', async event => {
            const button = event.currentTarget;
            button.disabled = true;
            try { await enableEffects?.(); }
            finally { button.disabled = false; syncResources(); }
        });
        window.addEventListener('nedotify:efficiency_state', syncResources);
        window.addEventListener('nedotify:profile_updated', syncProfile);
        const avatar = document.getElementById('home-avatar-img');
        if (avatar) new MutationObserver(syncProfile).observe(avatar, { attributes: true, attributeFilter: ['src', 'hidden'] });
        let paletteSignature = '';
        new MutationObserver(() => {
            const signature = root.dataset.theme + '|' + root.style.getPropertyValue('--primary-rgb');
            if (signature !== paletteSignature) { paletteSignature = signature; syncAccent(); }
            syncResources();
        }).observe(root, {
            attributes: true, attributeFilter: ['style', 'data-theme', 'class']
        });
        new MutationObserver(syncResources).observe(document.body, { attributes: true, attributeFilter: ['class'] });
        system.addEventListener('change', () => { if (mode === 'system') apply(); });
        syncControls();
        syncResources();
        syncAccent();
        syncProfile();
        syncBackdrop();
    }

    window.NeDotifyAppearance = { init, restore, apply, refresh: () => { syncControls(); syncResources(); syncBackdrop(); } };
    apply();
})();
