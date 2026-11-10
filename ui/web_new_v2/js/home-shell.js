import { initAudioTools } from './audio-tools.js';
// Home presentation uses the existing library and player commands.
import { showPage, setSidebarCollapsed } from './pages.js';
import { selectSection, showLibraryOverview } from './library.js';
import { getCurrentTrack, getIsPlaying, togglePlayPause } from './player.js';
import { escapeHtml, coverImgHtml, getCoverUrl, renderIcons, createTrackElement, openModalFocusTrap } from './utils.js';

let collections = { history: [], top: [] };
let notices = [];
let initialized = false;

export function updateHomeCollections(data) {
    collections = { history: data.history || [], top: data.analytics?.top_tracks || [] };
    renderContinueListening();
}

export function openHomeLibrary(section, playlist = null) {
    showPage('library');
    if (section === 'favorites' || section === 'offline' || section === 'playlist') selectSection(section, playlist);
    else {showLibraryOverview();document.getElementById('lib-playlist-filter')?.focus();}
}

export function renderContinueListening() {
    const container = document.getElementById('home-continue');
    if (!container) return;
    const track = getCurrentTrack() || collections.history[0];
    if (!track) {
        container.innerHTML = '<div class="continue-copy"><span class="continue-label">Ваша следующая находка</span><h2>С чего начнём сегодня?</h2><p>Найдите любимый трек — здесь появится музыка, к которой хочется вернуться.</p></div><button class="home-pill" data-start-search>Найти музыку <i data-lucide="search"></i></button>';
        container.querySelector('button').onclick = () => { showPage('search'); document.getElementById('search-input')?.focus(); };
    } else {
        container.innerHTML = `${coverImgHtml({src:getCoverUrl(track), alt:track.title || '', coverUrl:track.cover_url || '', sourceId:track.source_id || '', source:track.source || ''})}<div class="continue-copy"><span class="continue-label">Продолжить прослушивание</span><h2>${escapeHtml(track.title || 'Без названия')}</h2><p>${escapeHtml(track.artist || 'Из вашей истории')}</p></div><button class="home-pill continue-play"><i data-lucide="${getIsPlaying() ? 'audio-lines' : 'play'}"></i><span>${getIsPlaying() ? 'Сейчас играет' : 'Продолжить'}</span></button>`;
        container.querySelector('button').onclick = () => {
            if (getCurrentTrack()) { if (getIsPlaying()) showPage('player'); else togglePlayPause(); }
            else Promise.resolve(window.pywebview?.api?.play_track({...track, id:track.track_id || track.id}, collections.history, 0)).catch(() => window.dispatchEvent(new CustomEvent('nedotify:toast',{detail:{msg:'Не удалось включить трек. Повторите попытку.',type:'error'}})));
        };
    }
    renderIcons(container);
}

export function openHomeDialog(title, render) {
    const dialog = document.getElementById('home-detail-dialog');
    const content = document.getElementById('home-detail-content');
    document.getElementById('home-detail-title').textContent = title;
    content.replaceChildren();
    content.className = '';
    render(content);
    if (!dialog.open) dialog.showModal();
    openModalFocusTrap(dialog);
    renderIcons(dialog);
}

function showCollection(kind) {
    const list = kind === 'top' ? collections.top : collections.history;
    openHomeDialog(kind === 'top' ? 'Топ треков' : 'История прослушивания', content => {
        if (!list.length) {
            content.innerHTML = '<div class="home-empty"><i data-lucide="headphones"></i><h3>Здесь будет ваша музыка</h3><p>Включите трек — история и личный топ появятся после прослушивания.</p></div>';
        } else list.forEach((track, index) => content.appendChild(createTrackElement({...track,id:track.track_id || track.id}, index, list, getCurrentTrack())));
    });
}

function updateAvatar() {
    const source = document.getElementById('profile-avatar-img');
    const avatar = document.getElementById('home-avatar-img');
    if (source?.src && source.style.display !== 'none') { avatar.src = source.src; avatar.hidden = false; }
    else avatar.hidden = true;
    document.getElementById('home-profile')?.setAttribute('aria-label', `Профиль: ${window.settings?.personalization?.nickname || 'NeDotify'}`);
}

export function initHomeShell() {
    if (initialized) return;
    initialized = true;
    initAudioTools();
    document.getElementById('sidebar-collapse')?.addEventListener('click', () => setSidebarCollapsed());
    document.querySelectorAll('[data-home-library]').forEach(button => button.addEventListener('click', () => openHomeLibrary(button.dataset.homeLibrary)));
    document.querySelectorAll('[data-home-collection]').forEach(button => button.addEventListener('click', () => showCollection(button.dataset.homeCollection)));
    document.getElementById('home-search-form')?.addEventListener('submit', e => {
        e.preventDefault();
        const query = document.getElementById('home-search-input').value.trim();
        showPage('search');
        const input = document.getElementById('search-input');
        input.value = query;
        input.dispatchEvent(new Event('input', {bubbles:true}));
        input.focus();
    });
    document.getElementById('home-profile')?.addEventListener('click', () => showPage('profile'));
    document.getElementById('pb-btn-expand-view')?.addEventListener('click', () => showPage('player'));
    window.addEventListener('nedotify:toast', e => {
        const msg = e.detail?.msg;
        if (!msg) return;
        notices.unshift({msg:String(msg), time:new Date()});
        notices = notices.slice(0,30);
        document.getElementById('home-notices').classList.add('has-notices');
    });
    document.getElementById('home-notices')?.addEventListener('click', () => {
        openHomeDialog('Уведомления', content => {
            if (!notices.length) { content.innerHTML = '<div class="home-empty"><i data-lucide="bell"></i><h3>Пока нет уведомлений</h3><p>Здесь появятся сообщения приложения за текущий сеанс.</p></div>'; return; }
            notices.forEach(notice => {
                const row = document.createElement('div'); row.className = 'home-notice';
                const time = document.createElement('time'); time.textContent = new Intl.DateTimeFormat('ru',{hour:'2-digit',minute:'2-digit'}).format(notice.time);
                const message = document.createElement('p'); message.textContent = notice.msg;
                row.append(time,message); content.append(row);
            });
        });
        document.getElementById('home-notices').classList.remove('has-notices');
    });
    const dialog = document.getElementById('home-detail-dialog');
    document.getElementById('home-detail-close')?.addEventListener('click', () => dialog.close());
    document.addEventListener('nedotify:track_changed', renderContinueListening);
    document.addEventListener('nedotify:state_changed', renderContinueListening);
    window.addEventListener('nedotify:app_ready', updateAvatar);
    const profileImg = document.getElementById('profile-avatar-img');
    if (profileImg) new MutationObserver(updateAvatar).observe(profileImg,{attributes:true,attributeFilter:['src','style']});
    document.getElementById('home-retry')?.addEventListener('click', () => window.NeDotify?.loadHome());
    renderContinueListening();
}
