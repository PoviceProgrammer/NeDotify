// Presentation helpers; settings.js owns persistence and the existing controls.
import { renderIcons } from './utils.js';
import { mountRecommendationControls } from './recommendation-controls.js';

const THEME_IMAGES = {
    dark:'01_Dark', amoled:'02_AMOLED', midnight:'03_Midnight', sky:'04_Sky',
    mint:'05_Mint', violet:'06_Violet', blossom:'07_Blossom', sakura:'08_Sakura',
    terminal:'09_Terminal', sand:'10_Sand', aqua:'11_Aqua', sunset:'12_Sunset',
    slate:'13_Slate', neutral:'14_Neutral', crimson:'15_Crimson',
    lavender:'16_Lavender', ocean:'17_Ocean'
};
export function themePreviewPath(id) {
    return THEME_IMAGES[id] ? `assets/theme-previews/${THEME_IMAGES[id]}.png` : '';
}

export function syncThemeSelection() {
    const current=document.documentElement.dataset.theme;
    const backgroundButton=document.getElementById('appearance-theme-background');
    if(backgroundButton)backgroundButton.disabled=!window.NeDotifyAssets?.themeBackgroundPath(current);
    document.querySelectorAll('#theme-presets-grid .theme-card').forEach(card=>{
        const active=card.dataset.theme===current;
        card.classList.toggle('active',active);card.setAttribute('aria-pressed',String(active));
        const badge=card.querySelector('.theme-card-badge');if(badge)badge.hidden=!active;
    });
    document.querySelectorAll('.theme-mode-btn').forEach(button=>button.setAttribute('aria-pressed',String(button.classList.contains('active'))));
}

export function syncCustomColorFields() {
    document.querySelectorAll('.custom-color-row input[type="color"]').forEach(picker=>{
        const field=document.getElementById(`${picker.id}-hex`);if(field)field.value=picker.value.toUpperCase();
    });
}

// Small extensions use the same persistence/restore path as the original
// controls. Mount before indexing Settings search so these rows are searchable.
export function initAdditionalSettings({save, read, applyRadius}) {
    const player = document.getElementById('settings-player');
    if (player && !document.getElementById('settings-recommendation-controls')) {
        const section = document.createElement('section');
        section.className = 'settings-section';
        const heading = document.createElement('h2');
        heading.className = 'settings-section-title';
        heading.textContent = 'Рекомендации';
        const controls = document.createElement('div');
        controls.id = 'settings-recommendation-controls';
        section.append(heading, controls);
        player.prepend(section);
        mountRecommendationControls(controls);
    }
    const appearance = document.getElementById('settings-appearance');
    if (appearance && !document.getElementById('settings-radius')) {
        const section = document.createElement('section');
        section.id = 'settings-radius';section.className = 'settings-section';
        section.innerHTML = '<h2 class="settings-section-title">Закругления</h2><p class="settings-section-desc">Форма карточек и панелей в обоих интерфейсах.</p>'
            + '<div class="setting-row"><label class="setting-label" for="slider-border-radius">Радиус углов</label><output id="label-border-radius" for="slider-border-radius">12px</output></div>'
            + '<input id="slider-border-radius" type="range" class="settings-slider" min="0" max="24" step="1" aria-label="Радиус углов">';
        appearance.append(section);
        const slider = document.getElementById('slider-border-radius');
        applyRadius(read('interface', 'border_radius', 12));
        slider.addEventListener('input', () => applyRadius(slider.value));
        slider.addEventListener('change', async () => {
            const value = applyRadius(slider.value);
            slider.disabled = true;
            try { await save('border_radius', value, 'interface'); }
            finally { slider.disabled = false;applyRadius(read('interface', 'border_radius', 12)); }
        });
    }
    const services = document.getElementById('settings-auth');
    if (services && !document.getElementById('settings-music-sources')) {
        const section = document.createElement('section');
        section.id = 'settings-music-sources';section.className = 'settings-section';
        section.innerHTML = '<h2 class="settings-section-title">Источники музыки</h2><p class="settings-section-desc">Выбранные сервисы используются для поиска и рекомендаций. Музыка с компьютера доступна всегда; Last.fm подключается отдельно.</p>'
            + [['youtube','YouTube / YouTube Music'],['soundcloud','SoundCloud']].map(([name,label]) =>
                `<div class="setting-row"><span class="setting-label" id="source-${name}-label">${label}</span><button class="toggle-switch" type="button" id="toggle-source-${name}" role="switch" aria-labelledby="source-${name}-label"><span class="toggle-dot"></span></button></div>`).join('');
        services.prepend(section);
        for (const name of ['youtube','soundcloud']) {
            const button = document.getElementById(`toggle-source-${name}`), key = `${name}_enabled`;
            const sync = () => { const enabled = read('services', key, true) !== false;button.classList.toggle('on',enabled);button.setAttribute('aria-checked',String(enabled)); };
            sync();
            button.addEventListener('click', async () => {
                button.disabled = true;
                try { await save(key, read('services', key, true) === false, 'services'); }
                finally { sync();button.disabled = false; }
            });
        }
    }
}

export function initSettingsView({resetPalette, backgrounds, themeBackgrounds = [], chooseBackground}) {
    const root = document.getElementById('view-settings');
    // Older settings cards are divs. Give every choice the same keyboard behaviour as buttons.
    const syncControls = () => {
        root.querySelectorAll('.opt-card,.font-card').forEach(card => {
            card.setAttribute('role','button');card.tabIndex=0;
            card.setAttribute('aria-pressed',String(card.classList.contains('active')));
        });
        root.querySelectorAll('button.toggle-switch').forEach(button => {
            button.setAttribute('role','switch');button.setAttribute('aria-checked',String(button.classList.contains('on')));
        });
        root.querySelectorAll('.opt-toggle-btn,.opt-card-btn,.particle-shape-btn,.font-cat-btn,.tag-btn').forEach(button => button.setAttribute('aria-pressed',String(button.classList.contains('active'))));
    };
    root.addEventListener('keydown',event=>{
        if ((event.key==='Enter' || event.key===' ') && event.target.matches('.opt-card,.font-card')) {
            event.preventDefault();event.stopPropagation();event.target.click();
        }
    });
    new MutationObserver(syncControls).observe(root,{subtree:true,childList:true,attributes:true,attributeFilter:['class']});
    syncControls();
    const nav=document.querySelector('#view-settings .settings-nav');
    const heading=document.createElement('div');heading.className='settings-nav-heading';
    heading.innerHTML='<h1>Настройки</h1><p>Персонализируй свой NeDotify</p>';nav.prepend(heading);
    const title=document.getElementById('settings-current-title');
    const descriptions={appearance:'Цвета, шрифты и фон приложения',audio:'Звучание и переходы между треками',player:'Оформление и поведение плеера',background:'Ваше фоновое изображение',workshop:'Каталог фонов',icons:'Стиль значков и логотипа',atmosphere:'Погода и мягкая реакция на музыку',optimization:'Производительность и расход ресурсов',keybinds:'Управление с клавиатуры',storage:'Загрузки, место и кэш',import:'Перенос музыкальных коллекций',zapret:'Настройки обхода DPI',auth:'Подключение музыкальных сервисов',about:'Информация о приложении и обновления'};
    const updateHeading=button=>{
        title.textContent=button.textContent.trim();
        document.getElementById('settings-current-description').textContent=descriptions[button.dataset.panel] || '';
        document.querySelectorAll('.settings-nav-btn').forEach(item=>item.setAttribute('aria-current',item===button?'true':'false'));
        const bounds=button.getBoundingClientRect(),viewport=nav.getBoundingClientRect();
        if(bounds.left<viewport.left)nav.scrollLeft-=viewport.left-bounds.left;
        if(bounds.right>viewport.right)nav.scrollLeft+=bounds.right-viewport.right;
        if(bounds.top<viewport.top)nav.scrollTop-=viewport.top-bounds.top;
        if(bounds.bottom>viewport.bottom)nav.scrollTop+=bounds.bottom-viewport.bottom;
    };
    nav.querySelectorAll('.settings-nav-btn').forEach(button=>button.addEventListener('click',()=>updateHeading(button)));
    updateHeading(nav.querySelector('.settings-nav-btn.active'));
    document.querySelectorAll('.settings-nav-section-label').forEach(label=>label.textContent=label.textContent.toLocaleLowerCase('ru').replace(/^./,c=>c.toLocaleUpperCase('ru')));

    document.querySelectorAll('.custom-color-row').forEach(row=>{
        const picker=row.querySelector('input[type="color"]');if(!picker)return;
        const label=row.querySelector('.custom-color-label');label.id=`${picker.id}-label`;
        const field=document.createElement('input');field.id=`${picker.id}-hex`;field.className='custom-color-hex';field.type='text';
        field.maxLength=7;field.autocomplete='off';field.spellcheck=false;field.setAttribute('aria-labelledby',label.id);field.setAttribute('aria-label',`${label.textContent}: HEX`);
        row.appendChild(field);picker.addEventListener('input',()=>{field.value=picker.value.toUpperCase();field.removeAttribute('aria-invalid');});
        const commit=()=>{
            const hex=field.value.trim();
            if(!/^#[\da-f]{6}$/i.test(hex)){field.setAttribute('aria-invalid','true');return;}
            field.removeAttribute('aria-invalid');picker.value=hex;
            picker.dispatchEvent(new Event('input',{bubbles:true}));
            picker.dispatchEvent(new Event('change',{bubbles:true}));
        };
        field.addEventListener('change',commit);field.addEventListener('keydown',event=>{if(event.key==='Enter')commit();if(event.key==='Escape'){field.value=picker.value.toUpperCase();field.removeAttribute('aria-invalid');event.stopPropagation();}});
    });
    const custom=document.querySelector('.custom-theme-box');
    const paletteNote=document.createElement('p');paletteNote.id='macos-palette-note';paletteNote.className='settings-section-desc';paletteNote.hidden=true;
    paletteNote.textContent='В macOS пользовательская палитра меняет акцент. Цвета поверхностей и текста применяются в стиле «Текущее».';
    custom.prepend(paletteNote);
    const customTitle=document.createElement('div');customTitle.className='settings-block-heading';
    customTitle.innerHTML='<div><h2>Пользовательская тема</h2><p>Создайте свою цветовую схему</p></div><button id="btn-reset-custom-theme" class="home-pill"><i data-lucide="refresh-cw"></i>Сбросить цвета</button>';
    custom.prepend(customTitle);document.getElementById('btn-reset-custom-theme').onclick=resetPalette;
    const enabled=document.createElement('label');enabled.className='custom-palette-switch';enabled.innerHTML='<input id="custom-palette-enabled" type="checkbox"> Использовать пользовательские цвета';customTitle.after(enabled);
    enabled.querySelector('input').addEventListener('change',event=>{if(!event.target.checked)resetPalette();else{const picker=document.getElementById('picker-color-primary');picker.dispatchEvent(new Event('change',{bubbles:true}));}});
    syncCustomColorFields();

    const gallery=document.getElementById('settings-background-gallery');
    const createBackgroundChoice=item=>{
        const button=document.createElement('button');button.className='settings-bg-choice';button.type='button';button.title=item.title;button.dataset.backgroundUrl=item.url;button.setAttribute('aria-pressed','false');button.setAttribute('aria-label',`Выбрать фон: ${item.title}`);
        const image=document.createElement('img');image.src=item.preview;image.alt='';image.width=160;image.height=90;image.loading='lazy';image.onerror=()=>{image.hidden=true;};
        const text=document.createElement('span');text.textContent=item.title;button.append(image,text);button.onclick=()=>chooseBackground(item);return button;
    };
    backgrounds.forEach(item=>gallery.appendChild(createBackgroundChoice(item)));
    gallery.appendChild(document.getElementById('appearance-upload-background'));
    const builtins=document.createElement('section');builtins.className='settings-section settings-builtin-backgrounds';
    builtins.innerHTML='<h2 class="settings-section-title">Встроенные фоны</h2><p class="settings-section-desc">Все изображения доступны без интернета. Палитра и режим оформления сохраняются при выборе фона.</p><div class="settings-builtin-gallery" role="group" aria-label="Встроенные фоны приложения"></div>';
    themeBackgrounds.forEach(item=>builtins.lastElementChild.appendChild(createBackgroundChoice(item)));
    document.getElementById('settings-background').appendChild(builtins);
    document.getElementById('appearance-theme-background').onclick=()=>{
        const path=window.NeDotifyAssets?.themeBackgroundPath(document.documentElement.dataset.theme);
        if(path)chooseBackground({title:'Фон выбранной темы',url:path});
    };
    document.getElementById('appearance-upload-background').onclick=()=>document.getElementById('btn-upload-bg-image').click();
    document.getElementById('appearance-more-backgrounds').onclick=()=>document.querySelector('.settings-nav-btn[data-panel="workshop"]').click();
    document.getElementById('appearance-background-options').onclick=()=>document.querySelector('.settings-nav-btn[data-panel="background"]').click();
    const mirrorBackground=()=>{
        const source=document.getElementById('bg-image-preview'),target=document.getElementById('appearance-current-background');
        const url=source.style.backgroundImage;target.style.backgroundImage=url;target.hidden=!url || url==='none';
        root.querySelectorAll('[data-background-url]').forEach(button=>button.setAttribute('aria-pressed',String(url.includes(button.dataset.backgroundUrl))));
    };
    new MutationObserver(mirrorBackground).observe(document.getElementById('bg-image-preview'),{attributes:true,attributeFilter:['style']});mirrorBackground();
    renderIcons(document.getElementById('view-settings'));
}
