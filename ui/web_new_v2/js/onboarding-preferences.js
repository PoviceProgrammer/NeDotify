import { mountArtistPicker } from './onboarding-artists.js';
// Riff's welcome flow keeps a preview draft, then hands one preference payload
// to the main app. Adapted for NeDotify's existing Python persistence boundary.
// Reference and attribution: docs/riff-onboarding.md (MIT, rootscripts 2026).
const FORMATS = ['source', 'mp3', 'm4a', 'opus', 'flac', 'wav'];
const QUALITIES = ['best', '320', '256', '192', '128'];
const SOURCE_NAMES = {youtube: 'YouTube / YouTube Music', soundcloud: 'SoundCloud'};
export const ONBOARDING_ARTISTS = ['королевский XVII','тёмный принц','madk1d','VILLIAN','zombiqe','KAI ANGEL','9mice','Heronwater','LOVV66','FORTUNA 812','uglystephan','BUSHIDO ZHO','Lildrughill','Toxi$','FRIENDLY THUG 52 NGG','dekma','xxxmanera','kantaa','STED.D','nkeeei'];

export function preferenceDraft(settings = {}, saved = {}) {
    const source = saved.sources && typeof saved.sources === 'object' ? saved.sources : {};
    const style = saved.uiStyle ?? settings.interface?.ui_style;
    const format = saved.format ?? settings.downloads?.format;
    const quality = String(saved.quality ?? settings.downloads?.quality ?? 'best');
    return {
        artists: [...new Set((Array.isArray(saved.artists) ? saved.artists : settings.personalization?.favorite_artists || []).filter(name => typeof name === 'string' && name.trim()).map(name => name.trim()))],
        uiStyle: style === 'macos' ? 'macos' : 'current',
        sources: Object.fromEntries(Object.keys(SOURCE_NAMES).map(name => [name,
            typeof source[name] === 'boolean' ? source[name] : settings.services?.[`${name}_enabled`] !== false])),
        format: FORMATS.includes(format) ? format : 'source',
        quality: QUALITIES.includes(quality) ? quality : 'best',
    };
}

export function preferencePayload(draft) {
    return {ui_style: draft.uiStyle, sources: {...draft.sources},
        favorite_artists: [...(draft.artists || [])],
        download_format: draft.format, download_quality: draft.quality};
}

export function mountOnboardingPreferences(wizard, draft, {signal, onChange}) {
    wizard.querySelectorAll('[data-ob-preferences]').forEach(node => node.remove());
    function section(step, html) {
        const node = document.createElement('div');
        node.dataset.obPreferences = '';
        node.innerHTML = html;
        wizard.querySelector(`.onboarding-step[data-step="${step}"]`).append(node);
        return node;
    }
    const appearance = section(1, `<fieldset class="ob-fieldset"><legend>Интерфейс</legend><div class="ob-style-choices">
        <button type="button" class="ob-secondary" data-ob-style="current">NeDotify</button>
        <button type="button" class="ob-secondary" data-ob-style="macos">macOS</button></div>
        <p class="ob-hint">Выбранный интерфейс появится после сохранения.</p></fieldset>`);
    const library = section(5, `<fieldset class="ob-fieldset ob-source-options"><legend>Источники поиска и рекомендаций</legend>
        <label><input type="checkbox" data-ob-source="youtube">YouTube / YouTube Music</label>
        <label><input type="checkbox" data-ob-source="soundcloud">SoundCloud</label>
        <p class="ob-hint">Можно оставить только музыку с компьютера. Подключение Last.fm необязательно.</p></fieldset>
        <fieldset class="ob-fieldset"><legend>Скачивание</legend><div class="ob-download-options">
        <label>Формат<select id="ob-download-format"><option value="source">Исходный файл · быстрее</option><option value="mp3">MP3</option><option value="m4a">M4A</option><option value="opus">Opus</option><option value="flac">FLAC</option><option value="wav">WAV</option></select></label>
        <label>Качество<select id="ob-download-quality"><option value="best">Лучшее доступное</option><option value="320">320 кбит/с</option><option value="256">256 кбит/с</option><option value="192">192 кбит/с</option><option value="128">128 кбит/с</option></select></label></div>
        <p class="ob-hint">Конвертация не повышает качество источника. Для исходного файла и lossless битрейт не меняется.</p></fieldset>`);
    section(4, `<fieldset class="ob-fieldset"><legend>Музыка с компьютера</legend><button type="button" id="ob-import-folder" class="ob-secondary">Выбрать и добавить папку…</button>
        <p class="ob-hint" id="ob-folder-status" role="status">Файлы останутся на своём месте; папка появится в медиатеке.</p></fieldset>`);
    const artists = section(5, '<div class="ob-artist-picker"></div>');
    // Put taste selection before optional source/download controls.
    artists.parentElement.querySelector('.ob-lead').after(artists);
    const paintArtists = mountArtistPicker(artists.firstElementChild, draft, ONBOARDING_ARTISTS, {signal,onChange});
    const summary = wizard.querySelector('.ob-summary');
    const rows = document.createElement('div');
    rows.dataset.obPreferences = '';
    // A separate definition list keeps valid dt/dd semantics, without wrappers
    // around existing rows whose layout belongs to onboarding.css.
    rows.className = 'ob-summary';
    rows.innerHTML = '<div><dt>Интерфейс</dt><dd data-ob-summary="style"></dd></div><div><dt>Источники</dt><dd data-ob-summary="sources"></dd></div><div><dt>Скачивание</dt><dd data-ob-summary="downloads"></dd></div>';
    if (summary) { const list = document.createElement('dl'); list.dataset.obPreferences = '';list.className = rows.className;list.innerHTML = rows.innerHTML;summary.after(list); }
    const $ = selector => wizard.querySelector(selector);
    const bind = (node, event, callback) => node.addEventListener(event, callback, {signal});
    appearance.querySelectorAll('[data-ob-style]').forEach(button => bind(button, 'click', () => {
        draft.uiStyle = button.dataset.obStyle;onChange();
    }));
    library.querySelectorAll('[data-ob-source]').forEach(input => bind(input, 'change', () => {
        draft.sources[input.dataset.obSource] = input.checked;onChange();
    }));
    for (const [id, key] of [['ob-download-format','format'], ['ob-download-quality','quality']]) {
        bind($(`#${id}`), 'change', event => {draft[key] = event.target.value;onChange();});
    }
    let importing = false;
    const folderStatus = $('#ob-folder-status');
    bind($('#ob-import-folder'), 'click', async event => {
        if (importing) return;
        importing = true;event.currentTarget.disabled = true;
        folderStatus.textContent = 'Выберите папку с музыкой…';
        try {
            const api = window.pywebview?.api;
            if (!api?.import_music_folder) throw new Error('Добавление папки сейчас недоступно. Повторите в настройках.');
            const result = await api.import_music_folder();
            if (signal.aborted) return;
            if (result?.cancelled) { folderStatus.textContent = 'Папка не выбрана. Её можно добавить позже.'; return; }
            if (!result?.success) throw new Error(result?.error || 'Не удалось добавить папку');
            folderStatus.textContent = result.pending ? `Добавляем музыку: ${result.path || 'выбранная папка'}` : `Добавлено треков: ${result.count || 0}`;
        } catch (error) { if (!signal.aborted) folderStatus.textContent = error.message; }
        finally { importing = false;if (!signal.aborted) $('#ob-import-folder').disabled = false; }
    });
    bind(window, 'nedotify:scan_complete', event => {
        if (event.detail?.success !== false) folderStatus.textContent = `Добавлено треков: ${event.detail?.count || 0}. Папка сохранена в медиатеке.`;
    });
    return () => {
        paintArtists();
        appearance.querySelectorAll('[data-ob-style]').forEach(button => {
            const active = button.dataset.obStyle === draft.uiStyle;
            button.classList.toggle('active', active);button.setAttribute('aria-pressed', String(active));
        });
        library.querySelectorAll('[data-ob-source]').forEach(input => { input.checked = draft.sources[input.dataset.obSource]; });
        $('#ob-download-format').value = draft.format;
        $('#ob-download-quality').value = draft.quality;
        $('#ob-download-quality').disabled = ['source','flac','wav'].includes(draft.format);
        $('[data-ob-summary="style"]').textContent = draft.uiStyle === 'macos' ? 'macOS' : 'NeDotify';
        $('[data-ob-summary="sources"]').textContent = Object.keys(SOURCE_NAMES).filter(key => draft.sources[key]).map(key => SOURCE_NAMES[key]).join(', ') || 'Музыка с компьютера';
        $('[data-ob-summary="downloads"]').textContent = draft.format === 'source' ? 'Исходный файл' : `${draft.format.toUpperCase()} · ${draft.quality === 'best' ? 'лучшее доступное' : `${draft.quality} кбит/с`}`;
    };
}
