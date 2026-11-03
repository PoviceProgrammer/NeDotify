import { renderIcons, showToast, openModalFocusTrap, closeModalFocusTrap } from './utils.js';
import { listAudioOutputs, applySettings } from './player.js';
import { applySettingsFromBackend } from './settings.js';
import { openSetupPanel } from './setup-panel.js';
import { preferenceDraft, preferencePayload, mountOnboardingPreferences } from './onboarding-preferences.js';
import { mountOnboardingMotion } from './onboarding-motion.js';

const THEMES = {
    dark: { name: 'Тёмная', bg: '#0a0a0f', surface: '#14141d', accent: '#a855f7', ink: '#ffffff', muted: '#b7b4c2', foreground: '#ffffff' },
    midnight: { name: 'Полночь', bg: '#0a0e17', surface: '#101622', accent: '#3b82f6', ink: '#ffffff', muted: '#b2bfd2', foreground: '#ffffff' },
    mint: { name: 'Мята', bg: '#061a14', surface: '#0c2920', accent: '#34d399', ink: '#ffffff', muted: '#adc8bc', foreground: '#061a14' },
    light: { name: 'Светлая', bg: '#f5f3f8', surface: '#ffffff', accent: '#a855f7', ink: '#1b1425', muted: '#625a70', foreground: '#1b1425' },
};
const PROFILES = { balanced: 'Баланс', high: 'Все эффекты', low: 'Экономия' };
let initialization = null;
let activeSession = null;

function readStorage(key) {
    try { return localStorage.getItem(key); } catch { return null; }
}
function writeStorage(key, value) {
    try { localStorage.setItem(key, value); } catch { /* Backend remains authoritative. */ }
}
const SECRET_KEYS = new Set(['yandex_token','oauth_client_secret','proxy_url','lastfm_api_key','lastfm_api_secret']);
function cacheableSettings(settings) {
    const copy = settings && typeof settings === 'object' ? {...settings} : {};
    delete copy.auth;
    if (copy.services && typeof copy.services === 'object') {
        copy.services = {...copy.services};
        for (const key of SECRET_KEYS) delete copy.services[key];
    }
    return copy;
}
function isComplete(settings) {
    return settings?.general?.first_launch_done === true || settings?.personalization?.onboarding_completed === true || settings?.onboarding_done === true;
}
function localComplete() {
    // Keep the legacy key readable for existing installations.
    let legacy = false;
    try { legacy = localStorage.getItem('aura_onboarding_done') === 'true'; } catch {}
    return legacy || readStorage('nedotify_general_first_launch_done') === 'true' || readStorage('nedotify_personalization_onboarding_completed') === 'true';
}
function rememberCompletion() {
    for (const key of ['aura_onboarding_done', 'nedotify_general_first_launch_done', 'nedotify_personalization_onboarding_completed']) {
        try { localStorage.removeItem(key); } catch {}
    }
    try { localStorage.removeItem('nedotify_onboarding_draft'); } catch {}
}

export function validatePlaylistUrl(value) {
    if (!value.trim()) return 'Вставьте ссылку на плейлист или выберите пустую медиатеку.';
    try {
        const url = new URL(value.trim());
        const host = url.hostname.toLowerCase();
        const validHost = ['youtube.com','www.youtube.com','music.youtube.com','soundcloud.com','www.soundcloud.com','on.soundcloud.com','deezer.com','www.deezer.com','link.deezer.com'].includes(host);
        const playlist = host.endsWith('youtube.com') ? url.pathname === '/playlist' && !!url.searchParams.get('list')
            : host === 'on.soundcloud.com' ? /^\/[A-Za-z0-9_-]+\/?$/.test(url.pathname)
            : host.endsWith('soundcloud.com') ? /^\/[^/]+\/sets\/[^/]+\/?$/.test(url.pathname)
            : host === 'link.deezer.com' ? url.pathname.length > 1
            : /^\/(?:[a-z]{2}\/)?playlist\/\d+\/?$/.test(url.pathname);
        if (url.protocol !== 'https:' || url.username || url.password || !validHost || !playlist) throw new Error('Unsupported URL');
        return '';
    } catch { return 'Нужна ссылка на плейлист YouTube, SoundCloud или Deezer.'; }
}

export function initOnboarding() {
    if (!initialization) initialization = startOnboarding().catch(error => {
        initialization = null;
        console.error('Failed to initialize onboarding:', error);
    });
    return initialization;
}
export function reopenOnboarding() {
    initialization = startOnboarding(true).catch(error => { initialization = null; console.error('Onboarding unavailable:', error); });
    return initialization;
}

async function startOnboarding(force = false) {
    const wizard = document.getElementById('onboarding-wizard');
    if (!wizard) return;
    if (!window.nedotifySettingsReady && !window.pywebview?.api?.get_settings && window.awaitBridge) {
        await window.awaitBridge();
        try {
            const settings = await window.pywebview.api.get_settings();
            if (settings) {
                window.settings = settings;
                applySettings(settings);applySettingsFromBackend(settings);
            }
        } catch (error) { console.warn('First-launch settings are not available yet:',error); }
    }
    if (window.nedotifySettingsReady) await window.nedotifySettingsReady;
    if (!window.settings) {
        await new Promise(resolve => {
            const deadline = Date.now() + 2000;
            const check = () => window.settings || Date.now() >= deadline ? resolve() : setTimeout(check, 50);
            check();
        });
    }
    if (!force && isComplete(window.settings)) { rememberCompletion(); return; }
    if (!force && localComplete()) {
        // Older releases stored completion only in localStorage. Keep those
        // profiles out of the wizard and migrate the legacy marker to the
        // backend's canonical setting before removing the local copy.
        const saveSetting = window.pywebview?.api?.save_setting;
        if (typeof saveSetting === 'function') {
            try {
                const result = await saveSetting('first_launch_done', true, 'general');
                if (result !== false && result?.success !== false) {
                    window.settings ||= {};
                    window.settings.general = {...window.settings.general, first_launch_done: true};
                    rememberCompletion();
                }
            } catch (error) {
                console.warn('Legacy onboarding state could not be migrated yet:', error);
            }
        }
        return;
    }

    const $ = id => document.getElementById(id);
    if (window.pywebview?.api?.get_setup_status) {
        const proceed = await openSetupPanel({firstRun: !force});
        if (!proceed) { initialization = null; return; }
    }
    const steps = [...wizard.querySelectorAll('.onboarding-step')];
    // Re-entering setup must replace the previous handlers, including native
    // picker and completion callbacks. One click always submits one draft.
    activeSession?.abort();
    const session = activeSession = new AbortController();
    const bind = (node, event, callback) => node.addEventListener(event, callback, {signal: session.signal});
    const settings = window.settings || {};
    const draft = { theme: THEMES[settings.theme?.theme] ? settings.theme.theme : 'dark',
        profile: PROFILES[settings.optimization?.performance_preset] ? settings.optimization.performance_preset : 'balanced',
        library: 'empty', playlist: '', device: settings.audio?.output_device || 'default',
        crossfade: settings.audio?.crossfade_enabled === true, normalization: settings.audio?.volume_normalization === true,
        autostart: settings.general?.autostart === true, tray: false,
        ...preferenceDraft(settings) };
    try {
        const saved = JSON.parse(readStorage('nedotify_onboarding_draft') || 'null');
        if (!force && (saved?.version === 1 || saved?.version === 2)) {
            if (THEMES[saved.theme]) draft.theme = saved.theme;
            if (PROFILES[saved.profile]) draft.profile = saved.profile;
            if (saved.library === 'import') draft.library = 'import';
            for (const key of ['crossfade','normalization','autostart','tray']) if (typeof saved[key] === 'boolean') draft[key] = saved[key];
            if (typeof saved.playlist === 'string') draft.playlist = saved.playlist.slice(0,2048);
            if (typeof saved.device === 'string' && saved.device.length <= 512) draft.device = saved.device || 'default';
            Object.assign(draft, preferenceDraft(settings, saved));
        }
    } catch {}
    let currentStep = 1, saving = false, finished = false, outputGeneration = 0;
    const persistDraft = () => writeStorage('nedotify_onboarding_draft', JSON.stringify({version:2,...draft}));
    const paintPreferences = mountOnboardingPreferences(wizard, draft, {signal:session.signal, onChange:() => {paint();persistDraft();}});
    const motion = mountOnboardingMotion(wizard, {signal:session.signal});
    wizard.dataset.motionState = 'editing';
    wizard.setAttribute('aria-busy','false');
    $('ob-btn-finish').textContent='Начать слушать';
    const controls = [...wizard.querySelectorAll('button,input,select')];
    const paintChoice = (selector, value) => wizard.querySelectorAll(selector).forEach(button => {
        const active = button.dataset.value === value;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', String(active));
    });
    const paint = () => {
        paintPreferences();
        const theme = THEMES[draft.theme];
        for (const key of ['bg','surface','accent','ink','muted','foreground']) wizard.style.setProperty(`--ob-${key}`, theme[key]);
        wizard.dataset.previewTheme = draft.theme;
        wizard.dataset.motionProfile = draft.profile;
        motion.preview(draft);
        paintChoice('[data-ob-theme]', draft.theme);
        paintChoice('[data-ob-profile]', draft.profile);
        paintChoice('[data-ob-library]', draft.library);
        $('ob-library-import').hidden = draft.library !== 'import';
        $('ob-preview-theme').textContent = theme.name;
        $('ob-preview-profile').textContent = PROFILES[draft.profile];
        $('ob-preview-note').textContent = draft.profile === 'low' ? 'Спокойный интерфейс без фоновых эффектов' : draft.profile === 'high' ? 'Свечение, частицы и плавные анимации' : 'Плавный интерфейс и умеренная нагрузка';
        $('ob-summary-theme').textContent = theme.name;
        $('ob-summary-profile').textContent = PROFILES[draft.profile];
        $('ob-summary-sound').textContent = [draft.crossfade ? 'Плавные переходы' : 'Обычные переходы', draft.normalization ? 'ровная громкость' : 'исходная громкость'].join(', ');
        $('ob-summary-library').textContent = draft.library === 'import' ? 'Импортировать плейлист после настройки' : 'Начать с пустой медиатеки';
    };
    function showStep(number, focus = true) {
        const previous = currentStep;
        currentStep = Math.max(1,Math.min(steps.length,number));
        steps.forEach((step,index) => { step.hidden = index + 1 !== currentStep;step.classList.toggle('active',!step.hidden); });
        wizard.querySelectorAll('[data-ob-step]').forEach(button => {
            const number = Number(button.dataset.obStep);
            button.setAttribute('aria-current', number === currentStep ? 'step' : 'false');
            button.classList.toggle('completed', number < currentStep);
        });
        $('ob-progress-label').textContent = `Шаг ${currentStep} из ${steps.length}`;
        $('ob-progress').value = currentStep;
        $('ob-progress').max = steps.length;
        wizard.style.setProperty('--ob-progress', String(currentStep / steps.length));
        $('ob-btn-back').hidden = currentStep === 1;
        $('ob-btn-next').hidden = currentStep === steps.length;
        $('ob-btn-finish').hidden = currentStep !== steps.length;
        $('ob-step-announcement').textContent = steps[currentStep-1].querySelector('h2').textContent;
        $('ob-step-content').scrollTop = 0;
        if (focus) steps[currentStep-1].querySelector('h2').focus({preventScroll:true});
        if (currentStep === 3) refreshOutputs();
        paint();
        motion.step(currentStep, previous);
        wizard.querySelector('[aria-current="step"]')?.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});
    }
    function validLibrary() {
        const error = draft.library === 'import' ? validatePlaylistUrl(draft.playlist) : '';
        $('ob-playlist-error').textContent = error;
        $('ob-playlist-url').setAttribute('aria-invalid', String(!!error));
        if (error) { showStep(4);$('ob-playlist-url').focus(); }
        return !error;
    }
    async function refreshOutputs(permission = false) {
        const generation = ++outputGeneration;
        $('ob-audio-status').textContent = 'Проверяем доступные устройства…';
        $('ob-audio-refresh').disabled = true;
        try {
            const result = await listAudioOutputs(permission);
            if (finished || generation !== outputGeneration) return;
            const select = $('ob-audio-device');select.replaceChildren();
            const devices = [{deviceId:'default',label:'Устройство Windows по умолчанию'},...(result.devices || []).filter(device=>device.deviceId !== 'default')];
            devices.forEach(device => { const option=document.createElement('option');option.value=device.deviceId;option.textContent=device.label || 'Аудиоустройство';select.append(option); });
            if (!devices.some(device=>device.deviceId===draft.device)) draft.device='default';
            select.value = draft.device;select.disabled = !result.supported || saving;
            $('ob-audio-status').textContent = result.error || (result.supported ? 'Выбранное устройство будет использоваться для музыки.' : 'Используется устройство Windows по умолчанию. Выбор другого устройства здесь недоступен.');
            $('ob-audio-permission').hidden = !result.supported || typeof navigator.mediaDevices?.selectAudioOutput !== 'function';
        } catch { $('ob-audio-status').textContent = 'Не удалось получить устройства. Можно продолжить с устройством Windows.'; }
        finally { if (generation===outputGeneration) $('ob-audio-refresh').disabled = saving; }
    }
    async function finish(skip = false) {
        if (saving || finished || session.signal.aborted || (!skip && !validLibrary())) return;
        saving = true;wizard.setAttribute('aria-busy','true');$('ob-save-error').hidden = true;
        const disabled = new Map(controls.map(control=>[control,control.disabled]));
        const restoreControls = () => disabled.forEach((value,control)=>control.disabled=value);
        session.signal.addEventListener('abort', restoreControls, {once:true});
        controls.forEach(control=>control.disabled=true);
        $('ob-btn-finish').textContent = 'Сохраняем…';
        const payload = skip ? {} : {
            theme:draft.theme, theme_mode:draft.theme === 'light'?'light':'dark', performance_preset:draft.profile,
            particles_enabled:draft.profile !== 'low', audio_device:draft.device,
            crossfade_enabled:draft.crossfade, volume_normalization:draft.normalization,
            autostart:draft.autostart, minimize_to_tray:false,
            ...preferencePayload(draft),
        };
        try {
            const api = window.pywebview?.api;
            if (!api?.complete_onboarding) throw new Error('Нет подключения к приложению. Подождите и повторите попытку.');
            const result = await api.complete_onboarding(payload);
            if (result !== true && result?.success !== true) throw new Error(result?.error || 'Не удалось сохранить настройки. Повторите попытку.');
            let settings = result?.settings;
            if (!settings && api.get_settings) { try { settings = await api.get_settings(); } catch {} }
            settings = settings && !Array.isArray(settings) ? settings : window.settings || {};
            settings.general = {...settings.general,first_launch_done:true};
            settings.personalization = {...settings.personalization,onboarding_completed:true};
            window.settings = settings;
            try {
                applySettings(settings);applySettingsFromBackend(settings);
                writeStorage('nedotify_cached_settings',JSON.stringify(cacheableSettings(settings)));
                for (const [category, values] of Object.entries(settings)) {
                    if (category === 'auth' || !values || typeof values !== 'object') continue;
                    for (const [key,value] of Object.entries(values)) {
                        if (SECRET_KEYS.has(String(key).toLowerCase())) continue;
                        writeStorage(`nedotify_${category}_${key}`,JSON.stringify(value));
                    }
                }
            } catch (error) { console.warn('Onboarding saved; settings will restore on next launch:',error); }
            rememberCompletion();finished=true;outputGeneration++;
            if (!skip) await motion.complete();
            if (activeSession !== session || session.signal.aborted) return;
            session.abort();
            closeModalFocusTrap(wizard);wizard.hidden=true;wizard.classList.add('hidden');
            if (!skip && draft.library === 'import') {
                showToast('Настройки сохранены. Импортируем плейлист…','info');
                try {
                    if (!api.import_external_playlist) throw new Error('Импорт сейчас недоступен');
                    const imported = await api.import_external_playlist(draft.playlist.trim());
                    if (!imported?.success) throw new Error(imported?.error || 'Не удалось импортировать плейлист');
                    showToast(`Плейлист «${imported.playlist_name || imported.name || 'Импортированный'}» добавлен: ${imported.imported_count ?? imported.count ?? 0} треков`,'success');
                } catch (error) { showToast(`${error.message}. Повторить импорт можно в настройках медиатеки.`,'error'); }
            } else showToast(skip ? 'Можно настроить плеер позже в настройках' : 'Всё готово. Приятного прослушивания!','success');
        } catch (error) {
            $('ob-save-error').textContent=error.message || 'Не удалось сохранить настройки. Повторите попытку.';
            $('ob-save-error').hidden=false;
        } finally {
            session.signal.removeEventListener('abort', restoreControls);
            saving=false;
            if (activeSession === session) {
                wizard.setAttribute('aria-busy','false');
                disabled.forEach((value,control)=>control.disabled=value);
                if (!session.signal.aborted) paintPreferences();
                $('ob-btn-finish').textContent='Начать слушать';
            }
        }
    }
    function onSettingsApplied(event) {
        if (!saving && isComplete(event.detail)) {
            finished=true;outputGeneration++;rememberCompletion();closeModalFocusTrap(wizard);
            wizard.hidden=true;wizard.classList.add('hidden');session.abort();
        }
    }
    bind(document,'nedotify:settings_applied',onSettingsApplied);
    wizard.querySelectorAll('[data-ob-theme]').forEach(button=>bind(button,'click',()=>{draft.theme=button.dataset.value;paint();persistDraft();}));
    wizard.querySelectorAll('[data-ob-profile]').forEach(button=>bind(button,'click',()=>{draft.profile=button.dataset.value;paint();persistDraft();}));
    wizard.querySelectorAll('[data-ob-library]').forEach(button=>bind(button,'click',()=>{draft.library=button.dataset.value;paint();persistDraft();}));
    for (const [id,key] of [['ob-crossfade','crossfade'],['ob-volume-norm','normalization'],['ob-autostart','autostart']]) {
        $(id).checked=draft[key];bind($(id),'change',event=>{draft[key]=event.target.checked;paint();persistDraft();});
    }
    $('ob-playlist-url').value=draft.playlist;
    bind($('ob-playlist-url'),'input',event=>{draft.playlist=event.target.value;$('ob-playlist-error').textContent='';event.target.removeAttribute('aria-invalid');persistDraft();});
    bind($('ob-audio-device'),'change',event=>{draft.device=event.target.value;persistDraft();});
    bind($('ob-audio-refresh'),'click',()=>refreshOutputs());
    bind($('ob-audio-permission'),'click',()=>refreshOutputs(true));
    bind($('ob-btn-next'),'click',()=>{if(currentStep!==4 || validLibrary())showStep(currentStep+1);});
    bind($('ob-btn-back'),'click',()=>showStep(currentStep-1));
    wizard.querySelectorAll('[data-ob-step]').forEach(button=>bind(button,'click',()=>{const next=Number(button.dataset.obStep);if(next<=4 || validLibrary())showStep(next);}));
    bind($('ob-btn-finish'),'click',()=>finish());
    bind($('ob-btn-skip'),'click',()=>finish(true));
    bind($('ob-btn-close'),'click',()=>finish(true));
    showStep(1,false);wizard.hidden=false;wizard.classList.remove('hidden');
    renderIcons(wizard);openModalFocusTrap(wizard,{initialFocus:'[data-ob-theme][aria-pressed="true"]'});
    motion.enter();
}
