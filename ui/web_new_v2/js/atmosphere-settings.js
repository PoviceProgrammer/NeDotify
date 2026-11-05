// One settings surface for both presentation packs and the shared renderer.
import { ATMOSPHERE_DEFAULTS, configureAtmosphere, armAtmosphereAudio } from './atmosphere-engine.js';
import { renderIcons } from './utils.js';

export { ATMOSPHERE_DEFAULTS };
let savePreference = null;
let initialized = false;
const previews = new Map();
const clone = (value) => JSON.parse(JSON.stringify(value));

function readConfig(settings = window.settings) {
    const config = clone(ATMOSPHERE_DEFAULTS);
    for (const key of Object.keys(config)) {
        let value = settings?.atmosphere?.[key];
        if (value === undefined) {
            try {
                value = JSON.parse(localStorage.getItem(`nedotify_atmosphere_${key}`) || 'null');
            } catch {}
        }
        if (value === undefined || value === null) continue;
        config[key] =
            typeof config[key] === 'object' && typeof value === 'object' && !Array.isArray(value)
                ? { ...config[key], ...value }
                : value;
    }
    return config;
}

const get = (config, path) => path.split('.').reduce((value, key) => value?.[key], config);
const percent = (value) => `${Math.round(value * 100)}%`;
function displayValue(input) {
    const value = Number(input.value);
    return input.dataset.unit === 'percent'
        ? percent(value)
        : input.dataset.unit === 'seconds'
          ? `${value} с`
          : input.dataset.unit === 'degrees'
            ? `${value}°`
            : input.step === '1'
              ? String(value)
              : `${value.toFixed(2)}×`;
}

function slider(path, label, min, max, step = '.05', unit = '') {
    return `<label class="atmosphere-control"><span>${label}<output data-atmosphere-output="${path}"></output></span><input type="range" class="slider-input" data-atmosphere-key="${path}" data-unit="${unit}" min="${min}" max="${max}" step="${step}" aria-label="${label}"></label>`;
}
function toggle(path, label, note = '') {
    return `<label class="atmosphere-check"><span><strong>${label}</strong>${note ? `<small>${note}</small>` : ''}</span><input type="checkbox" data-atmosphere-key="${path}"></label>`;
}
const detail = (title, body) =>
    `<details class="atmosphere-details"><summary>${title}</summary><div class="atmosphere-detail-grid">${body}</div></details>`;

export function restoreAtmosphereSettings(settings = window.settings) {
    const config = readConfig(settings);
    window.settings ||= {};
    window.settings.atmosphere = config;
    configureAtmosphere(config);
    const mount = document.getElementById('atmosphere-settings-controls');
    if (!mount) return config;
    mount.querySelectorAll('[data-atmosphere-key]').forEach((input) => {
        const value = get(config, input.dataset.atmosphereKey);
        if (input.type === 'checkbox') input.checked = !!value;
        else input.value = String(value);
        if (input.type === 'range') {
            input.style.setProperty(
                '--value-percent',
                `${(100 * (Number(input.value) - Number(input.min))) / (Number(input.max) - Number(input.min))}%`,
            );
            const output = mount.querySelector(`[data-atmosphere-output="${input.dataset.atmosphereKey}"]`);
            if (output) output.textContent = displayValue(input);
        }
    });
    mount.querySelectorAll('[data-atmosphere-effect]').forEach((button) => {
        const active = !!config.effects[button.dataset.atmosphereEffect];
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', String(active));
    });
    const master = mount.querySelector('#toggle-atmosphere');
    master?.classList.toggle('on', !!config.enabled);
    master?.setAttribute('aria-checked', String(!!config.enabled));
    mount.classList.toggle('atmosphere-disabled', !config.enabled);
    return config;
}

export function initAtmosphereSettings({ save } = {}) {
    if (save) savePreference = save;
    const mount = document.getElementById('atmosphere-settings-controls');
    if (!mount || initialized) {
        restoreAtmosphereSettings();
        return;
    }
    initialized = true;
    mount.classList.add('settings-section');
    mount.innerHTML = `
        <div class="atmosphere-hero"><span class="atmosphere-wordmark">ATMOSPHERE ENGINE</span><p>Погода, которая чувствует вашу музыку</p><div class="atmosphere-master"><span>Атмосферные эффекты</span><button id="toggle-atmosphere" type="button" class="toggle-switch" role="switch" aria-checked="false" aria-label="ATMOSPHERE ENGINE"><span class="toggle-dot"></span></button></div></div>
        <div class="atmosphere-effect-grid">${[
            ['rain', 'cloud-rain', 'Дождь', 'Глубина и мягкие капли'],
            ['thunderstorm', 'cloud-lightning', 'Гроза', 'Локальные вспышки'],
            ['fog', 'cloud-fog', 'Туман', 'Медленная дымка'],
            ['snow', 'snowflake', 'Снег', 'Лёгкое зимнее движение'],
        ]
            .map(
                ([key, icon, title, note]) =>
                    `<button type="button" class="atmosphere-effect" data-atmosphere-effect="${key}" aria-pressed="false"><span aria-hidden="true"><i data-lucide="${icon}"></i></span><strong>${title}</strong><small>${note}</small></button>`,
            )
            .join('')}</div>
        <p class="settings-section-desc">Сочетайте несколько эффектов. При сворачивании рендеринг приостанавливается автоматически.</p>
        ${slider('intensity', 'Общая интенсивность', 0, 1, '.01', 'percent')}
        ${toggle('reactive', 'Реакция на музыку', 'Бас, движение и блики следуют за звучанием')}
        <label class="atmosphere-select"><span>Качество</span><select data-atmosphere-key="quality" aria-label="Качество атмосферы"><option value="auto">Автоматически</option><option value="high">Высокое</option><option value="balanced">Сбалансированное</option><option value="low">Экономия ресурсов</option></select></label>
        ${detail('Музыкальная реакция', slider('sensitivity', 'Общая чувствительность', 0, 2) + slider('bass', 'Басы', 0, 2) + slider('mid', 'Средние частоты', 0, 2) + slider('treble', 'Высокие частоты', 0, 2) + slider('smoothing', 'Плавность', 0, 1, '.01', 'percent') + slider('max_reaction', 'Максимальная реакция', 0, 1, '.01', 'percent'))}
        ${detail('Параметры дождя', slider('rain.speed', 'Скорость дождя', 0.2, 2.5) + slider('rain.size', 'Размер капель', 0.4, 2.5) + slider('rain.opacity', 'Прозрачность дождя', 0, 1, '.01', 'percent') + slider('rain.depth', 'Глубина дождя', 1, 4, '1') + slider('rain.direction', 'Направление дождя', -45, 45, '1', 'degrees') + toggle('rain.highlights', 'Блики дождя') + toggle('rain.reactive', 'Дождь реагирует на музыку'))}
        ${detail('Параметры грозы', toggle('storm.flashes', 'Световые вспышки', 'Учитывают системное уменьшение движения') + slider('storm.interval', 'Интервал молний', 8, 60, '1', 'seconds') + slider('storm.brightness', 'Яркость молний', 0, 0.3, '.01', 'percent') + toggle('storm.thunder', 'Звук грома', 'Выключен по умолчанию; запускается только после вашего нажатия') + slider('storm.volume', 'Громкость грома', 0, 0.4, '.01', 'percent'))}
        ${detail('Параметры тумана', slider('fog.density', 'Плотность тумана', 0, 1, '.01', 'percent') + slider('fog.speed', 'Скорость тумана', 0.1, 2) + slider('fog.opacity', 'Прозрачность тумана', 0, 0.6, '.01', 'percent') + slider('fog.depth', 'Глубина тумана', 1, 4, '1') + '<label class="atmosphere-select"><span>Оттенок тумана</span><select data-atmosphere-key="fog.tint" aria-label="Оттенок тумана"><option value="theme">Из темы</option><option value="#c8d9ef">Прохладный</option><option value="#ead9c6">Тёплый</option></select></label>' + toggle('fog.reactive', 'Туман реагирует на музыку'))}
        ${detail('Параметры снега', slider('snow.speed', 'Скорость снега', 0.2, 2.5) + slider('snow.size', 'Размер снежинок', 0.4, 2.5) + slider('snow.density', 'Плотность снега', 0, 1, '.01', 'percent') + slider('snow.opacity', 'Прозрачность снега', 0, 1, '.01', 'percent') + slider('snow.depth', 'Глубина снега', 1, 4, '1') + slider('snow.direction', 'Направление снега', -45, 45, '1', 'degrees') + toggle('snow.reactive', 'Снег реагирует на музыку'))}`;

    const change = async (path, value, persist, gesture) => {
        const config = readConfig();
        const [key, child] = path.split('.');
        const previous = previews.has(key) ? previews.get(key) : clone(config[key]);
        if (!persist && !previews.has(key)) previews.set(key, previous);
        if (persist) previews.delete(key);
        const previousRows = [['atmosphere', key, previous]];
        if (key === 'enabled')
            previousRows.push(
                ['ui', 'particles_enabled', window.settings?.ui?.particles_enabled],
                ['optimization', 'resource_particles', window.settings?.optimization?.resource_particles],
            );
        if (child) config[key] = { ...config[key], [child]: value };
        else config[key] = value;
        window.settings.atmosphere = config;
        restoreAtmosphereSettings(window.settings);
        if (persist && value && ['storm.thunder', 'enabled', 'effects.thunderstorm'].includes(path))
            armAtmosphereAudio(gesture);
        if (!persist || !savePreference) return;
        const saved = await savePreference(key, config[key], 'atmosphere', { previous: previousRows });
        if (!saved) restoreAtmosphereSettings(window.settings);
    };
    mount.addEventListener('input', (event) => {
        const input = event.target.closest('input[type="range"][data-atmosphere-key]');
        if (input) change(input.dataset.atmosphereKey, Number(input.value), false);
    });
    mount.addEventListener('change', (event) => {
        const input = event.target.closest('[data-atmosphere-key]');
        if (!input) return;
        change(
            input.dataset.atmosphereKey,
            input.type === 'checkbox'
                ? input.checked
                : input.type === 'range'
                  ? Number(input.value)
                  : input.value,
            true,
            event,
        );
    });
    mount.addEventListener('click', (event) => {
        if (event.target.closest('#toggle-atmosphere')) change('enabled', !readConfig().enabled, true, event);
        const effect = event.target.closest('[data-atmosphere-effect]');
        if (effect)
            change(
                `effects.${effect.dataset.atmosphereEffect}`,
                !readConfig().effects[effect.dataset.atmosphereEffect],
                true,
                event,
            );
    });
    restoreAtmosphereSettings();
    renderIcons(mount);
}
