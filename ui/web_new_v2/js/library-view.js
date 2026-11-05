import { refreshFavoritesCovers } from './home-atmosphere.js';
import { escapeHtml, getCoverUrl, coverImgHtml, renderIcons, renderPlaylistCoverCollage, showToast, openModalFocusTrap } from './utils.js';

let commands = {};
let playlists = [];
let libraryTracks = [];
let favoriteCount = 0;
let overviewGeneration = 0;
let coverTarget = null;
let collectionFilter = '';
const collageRequests = new Map();
const COVER_KEY = 'nedotify_v2_playlist_covers';

let cachedCoverRaw = null;
let cachedCoverData = {};
function savedCovers() {
    try {
        const raw=localStorage.getItem(COVER_KEY) || '{}';
        if(raw!==cachedCoverRaw){const parsed=JSON.parse(raw);cachedCoverData=parsed && typeof parsed==='object' && !Array.isArray(parsed)?parsed:{};cachedCoverRaw=raw;}
        return {...cachedCoverData};
    } catch {return {};}
}
export function getPlaylistCover(id) { const cover=savedCovers()[String(id)];return typeof cover==='string'?cover:''; }

export function formatLibraryDate(raw) {
    if (!raw) return '';
    const normalized = String(raw).replace(' ','T');
    const date = new Date(/(?:Z|[+-]\d\d:\d\d)$/.test(normalized) ? normalized : `${normalized}Z`);
    if (!Number.isFinite(date.getTime())) return '';
    const format = new Intl.DateTimeFormat('ru',{day:'numeric',month:'short',year:'numeric'});
    return format.format(date) === format.format(new Date()) ? 'Сегодня' : format.format(date);
}

function setCollectionCover(container, playlist, tracks = null) {
    if (!container) return;
    const id = String(playlist?.id ?? playlist?.ID ?? 'library');
    container.dataset.coverId = id;
    container.dataset.collectionKind = playlist?.name === 'Локальные' ? 'local' : 'playlist';
    const custom = getPlaylistCover(id);
    if (custom) {container.innerHTML=coverImgHtml({src:custom,alt:''});return;}
    if (playlist?.cover_url) {container.innerHTML=coverImgHtml({src:getCoverUrl(playlist),coverUrl:playlist.cover_url,alt:''});return;}
    const render = list => {
        if (!container.isConnected || container.dataset.coverId !== id || getPlaylistCover(id)) return;
        const covers = list.slice(0,4).map(track=>({src:getCoverUrl(track),coverUrl:track.cover_url || '',sourceId:track.source_id || '',source:track.source || ''}));
        const collage = renderPlaylistCoverCollage(covers);
        container.innerHTML = collage || '<i data-lucide="list-music"></i>';
        renderIcons(container);
    };
    container.innerHTML = '<i data-lucide="list-music"></i>';renderIcons(container);
    if (tracks) {render(tracks);return;}
    if (!playlist?.id && !playlist?.ID) return;
    if (!collageRequests.has(id)) {
        const request=Promise.resolve().then(()=>window.pywebview.api.get_playlist_tracks(playlist.id ?? playlist.ID,'local',4)).then(data=>Array.isArray(data)?data:data?.tracks || []).catch(()=>{collageRequests.delete(id);return [];});
        collageRequests.set(id,request);
    }
    collageRequests.get(id).then(render);
}

function collectionCard(playlist, kind = 'playlist') {
    const card=document.createElement('article');card.className='lib-collection-card';
    const name=kind==='favorites'?'Любимые':playlist.name || 'Плейлист';
    card.dataset.collectionId=kind==='favorites'?'favorites':String(playlist.id ?? playlist.ID);
    card.innerHTML=`<button class="lib-collection-open" aria-label="Открыть: ${escapeHtml(name)}"><span class="lib-collection-cover"></span><strong title="${escapeHtml(name)}">${escapeHtml(name)}</strong><span>${kind==='favorites'?favoriteCount:Number(playlist.track_count)||0} треков</span></button>${kind==='playlist'?'<button class="lib-collection-menu icon-btn" aria-label="Действия с плейлистом"><i data-lucide="more-horizontal"></i></button>':''}`;
    const cover=card.querySelector('.lib-collection-cover');
    if(kind==='favorites'){cover.classList.add('is-favorites');cover.innerHTML='<i data-lucide="heart"></i>';queueMicrotask(refreshFavoritesCovers);}
    else queueMicrotask(()=>setCollectionCover(cover,playlist));
    card.querySelector('.lib-collection-open').onclick=()=>commands.select(kind,playlist);
    card.querySelector('.lib-collection-menu')?.addEventListener('click',e=>openPlaylistActions(playlist,e));
    return card;
}

function renderCollectionGrids() {
    for(const id of ['lib-overview-collections','lib-active-collections']) {
        const grid=document.getElementById(id);if(!grid)continue;
        grid.replaceChildren();
        playlists.filter(playlist=>String(playlist.name || '').toLocaleLowerCase('ru').includes(collectionFilter))
            .forEach(playlist=>grid.appendChild(collectionCard(playlist)));
        const create=document.createElement('button');create.className='lib-collection-create';create.innerHTML='<span><i data-lucide="plus"></i></span><strong>Создать плейлист</strong><small>Соберите свою музыку</small>';create.onclick=()=>commands.create();grid.appendChild(create);
        renderIcons(grid);
    }
}

export function updateLibraryPlaylists(data) {
    playlists=Array.isArray(data)?data.map(pl=>({...pl,id:pl.id ?? pl.ID})):[];
    collageRequests.clear();
    renderCollectionGrids();
    const select=document.getElementById('lib-mobile-playlists');
    if(select) {
        select.innerHTML='<option value="">Обзор библиотеки</option>'+playlists.map(pl=>`<option value="${escapeHtml(String(pl.id))}">${escapeHtml(pl.name)}</option>`).join('');
        select.value=String(commands.selected()?.id || '');
    }
}

export function updateLibraryFavoriteCount(count) {favoriteCount=count;renderCollectionGrids();}

export function updateLibraryHero(type, playlist, tracks = []) {
    document.getElementById('lib-active-view')?.classList.toggle('is-empty',!tracks.length);
    const description=document.getElementById('lib-playlist-description');
    if(description)description.textContent=type==='playlist'?(playlist?.description || 'Плейлист без описания'):'';
    const kind=document.getElementById('lib-hero-kind');
    if(kind)kind.textContent=type==='playlist'?'Мой плейлист':type==='favorites'?'Любимые треки':type==='offline'?'На этом компьютере':'Вся музыка';
    const cover=document.getElementById('lib-hero-cover');
    if(cover)cover.dataset.collectionType=type;
    if(type==='playlist')setCollectionCover(cover,playlist,tracks);
    else if(cover){cover.dataset.coverId=type;cover.innerHTML=`<i data-lucide="${type==='favorites'?'heart':type==='offline'?'download':'library'}"></i>`;}
    const updated=document.getElementById('lib-hero-updated');
    if(updated){const date=type==='playlist'?formatLibraryDate(playlist?.updated_at):'';updated.textContent=date?`Обновлено: ${date.toLocaleLowerCase('ru')}`:'';}
    for(const id of ['lib-btn-play-all','lib-btn-shuffle']){const button=document.getElementById(id);if(button)button.disabled=!tracks.length;}
    const edit=document.getElementById('lib-edit-cover');if(edit)edit.hidden=type!=='playlist';
    const menu=document.getElementById('lib-btn-playlist-options');if(menu)menu.hidden=type!=='playlist' && type!=='favorites';
    document.getElementById('lib-mobile-playlists').value=String(type==='playlist'?playlist?.id || '':'');
    renderIcons(cover);
    if(type==='favorites')refreshFavoritesCovers(tracks);
}

export function decorateLibraryRow(row, track, index) {
    row.classList.add('lib-table-row');row.tabIndex=0;
    row.querySelector('.track-number')?.remove?.();
    row.addEventListener('keydown',event=>{if(event.target===row && (event.key==='Enter'||event.key===' ')){event.preventDefault();row.click();}});
    const number=document.createElement('span');number.className='lib-row-number';number.textContent=index+1;row.prepend(number);
    const artist=document.createElement('button');artist.className='lib-row-artist';artist.textContent=track.artist || '—';artist.title=track.artist || '';artist.setAttribute('aria-label',`Исполнитель: ${track.artist || 'Неизвестен'}`);artist.onclick=e=>{e.stopPropagation();if(track.artist)window.searchArtistProfile?.(track.artist,track);};
    const album=document.createElement('span');album.className='lib-row-album';album.textContent=track.album || '—';album.title=track.album || '';
    const rawDate=track.added_to_playlist_at || track.added_at;
    const date=document.createElement('span');date.className='lib-row-date';date.textContent=formatLibraryDate(rawDate) || '—';date.title=rawDate || '';
    const actions=row.querySelector('.track-actions');row.insertBefore(artist,actions);row.insertBefore(album,actions);row.insertBefore(date,actions);
    const playlist = commands.selected?.();
    if (actions && playlist && commands.section?.() === 'playlist' && !playlist.is_system && track.id) {
        const remove = document.createElement('button');
        remove.className = 'icon-btn lib-remove-track';
        remove.type = 'button';
        remove.title = 'Удалить из плейлиста';
        remove.setAttribute('aria-label', 'Удалить из плейлиста');
        remove.innerHTML = '<i data-lucide="list-minus"></i>';
        remove.onclick = async event => {
            event.stopPropagation();
            remove.disabled = true;
            try {
                const result = await window.pywebview.api.remove_from_playlist(playlist.id, track.id);
                if (!result?.success) throw new Error('Remove failed');
                if (commands.selected?.()?.id === playlist.id) await commands.select('playlist', playlist);
            } catch { showToast('Не удалось удалить трек из плейлиста', 'error'); }
            finally { remove.disabled = false; }
        };
        actions.appendChild(remove);
    }
    if(!Number.isFinite(Number(track.duration)) || Number(track.duration)<=0){const duration=row.querySelector('.track-duration');if(duration)duration.textContent='—';}
    row.querySelectorAll('button').forEach(button=>{if(!button.getAttribute('aria-label'))button.setAttribute('aria-label',button.title || 'Действие с треком');});
    return row;
}

export function renderLibraryEmpty(container, message) {
    container.innerHTML=`<div class="lib-collection-empty"><i data-lucide="music-2"></i><h3>${escapeHtml(message)}</h3><p>Найдите музыку и добавьте её через меню трека.</p><button class="home-pill">Найти музыку</button></div>`;
    container.querySelector('button').onclick=()=>window.showPage?.('search');renderIcons(container);
}
export function renderLibraryFailure(container,retry) {
    container.innerHTML='<div class="lib-collection-empty"><i data-lucide="alert-circle"></i><h3>Не удалось загрузить коллекцию</h3><p>Повторите запрос. Ваши сохранённые треки остаются в библиотеке.</p><button class="home-pill">Повторить</button></div>';
    container.querySelector('button').onclick=retry;renderIcons(container);
}

export async function loadLibraryOverview() {
    const current=++overviewGeneration;
    const container=document.getElementById('lib-recent-tracks');if(!container)return;
    try {
        await window.awaitBridge();
        const data=await window.pywebview.api.get_library(8,0,true);
        if(current!==overviewGeneration)return;
        const tracks=Array.isArray(data)?data:data?.tracks;
        if(!Array.isArray(tracks))throw new Error('Invalid library response');
        libraryTracks=tracks;
        const total=data?.total!=null && Number.isFinite(Number(data.total))?Math.max(0,Number(data.total)):tracks.length;
        document.getElementById('lib-overview-count').textContent=`${total} треков в коллекции`;
        container.replaceChildren();
        const recent=libraryTracks.slice(0,8);
        if(!recent.length)renderLibraryEmpty(container,'Начните свою коллекцию');
        else recent.forEach((track,index)=>container.appendChild(decorateLibraryRow(commands.row(track,index,recent),track,index)));
        renderIcons(container);
    } catch {if(current===overviewGeneration)renderLibraryFailure(container,loadLibraryOverview);}
}

function actionDialogHeader(title, subtitle = 'Управление плейлистом') {
    return `<header class="lib-dialog-header"><span class="lib-dialog-badge" aria-hidden="true"><i data-lucide="list-music"></i></span><div><p>${escapeHtml(subtitle)}</p><h3 id="lib-actions-title">${escapeHtml(title)}</h3></div><button type="button" class="lib-dialog-close" data-modal-close aria-label="Закрыть"><i data-lucide="x"></i></button></header>`;
}
function prepareActionDialog(menu, event) {
    menu.setAttribute('aria-labelledby','lib-actions-title');
    menu.querySelector('[data-modal-close]').onclick=()=>menu.close();
    renderIcons(menu);
    if (!menu.open) menu.showModal();
    openModalFocusTrap(menu, {returnFocusTo:event?.currentTarget,initialFocus:'[data-action], [data-trigger], input'});
}
export function openPlaylistActions(playlist,event) {
    const menu=document.getElementById('lib-playlist-actions');
    const isLocked=playlist.is_system || playlist.name==='Скачанное';
    menu.innerHTML=actionDialogHeader(playlist.name || 'Плейлист')+`<div class="lib-dialog-actions"><button data-action="cover"><i data-lucide="image"></i><span>Изменить обложку</span><i data-lucide="chevron-right"></i></button><button data-action="reset"><i data-lucide="rotate-ccw"></i><span>Сбросить обложку</span></button><button data-action="export"><i data-lucide="download"></i><span>Экспорт в M3U8</span></button>${isLocked?'':'<button data-action="rename"><i data-lucide="pencil"></i><span>Переименовать</span></button><button data-action="delete" class="lib-danger"><i data-lucide="trash-2"></i><span>Удалить плейлист</span></button>'}</div>`;
    menu.querySelectorAll('[data-action]').forEach(button=>button.onclick=async()=>{
        if (button.dataset.action === 'rename') {
            menu.innerHTML = actionDialogHeader('Новое название', 'Переименовать плейлист')+`<form class="lib-rename-form"><label for="lib-rename-name">Название плейлиста</label><input id="lib-rename-name" value="${escapeHtml(playlist.name)}" maxlength="200" required><p role="status"></p><div class="lib-dialog-footer"><button type="button">Отмена</button><button type="submit">Сохранить</button></div></form>`;
            const form = menu.querySelector('form');
            form.querySelector('[type="button"]').onclick = () => menu.close();
            form.onsubmit = async event => {
                event.preventDefault();
                const name = form.querySelector('input').value.trim();
                if (!name) return;
                const save = form.querySelector('[type="submit"]'); save.disabled = true;
                try {
                    const result = await window.pywebview.api.rename_playlist(playlist.id, name);
                    if (!result?.success) throw new Error('Rename failed');
                    playlist.name = name; renderCollectionGrids();
                    if (commands.selected()?.id === playlist.id) updateLibraryHero('playlist', playlist, commands.tracks());
                    const title = document.getElementById('lib-active-title');
                    if (title && commands.selected()?.id === playlist.id) title.textContent = name;
                    menu.close();
                } catch { form.querySelector('[role="status"]').textContent = 'Не удалось сохранить название'; }
                finally { save.disabled = false; }
            };
            menu.querySelector('[data-modal-close]').onclick=()=>menu.close();renderIcons(menu);form.querySelector('input').focus();
            return;
        }
        menu.close();
        if(button.dataset.action==='cover'){coverTarget=playlist;document.getElementById('lib-cover-file').click();}
        else if(button.dataset.action==='reset'){try{const data=savedCovers();delete data[String(playlist.id)];localStorage.setItem(COVER_KEY,JSON.stringify(data));renderCollectionGrids();if(String(commands.selected()?.id)===String(playlist.id))updateLibraryHero('playlist',playlist,commands.tracks());}catch{showToast('Не удалось сбросить обложку','error');}}
        else if(button.dataset.action==='delete')commands.remove(playlist);
        else {
            try {const result=await window.pywebview.api.export_playlist(playlist.id,'m3u8');showToast(result?.success?`Плейлист экспортирован: ${result.file_path}`:result?.error || 'Не удалось экспортировать плейлист',result?.success?'success':'error');}
            catch{showToast('Не удалось экспортировать плейлист','error');}
        }
    });
    prepareActionDialog(menu,event);
}

export function initLibraryView(callbacks) {
    commands=callbacks;
    document.getElementById('lib-btn-overview').onclick=()=>commands.overview();
    document.getElementById('lib-btn-back-overview').onclick=()=>commands.overview();
    document.querySelectorAll('[data-library-all-playlists]').forEach(button=>button.onclick=()=>{
        commands.overview();
        document.getElementById('lib-collection-filter')?.focus();
    });
    document.getElementById('lib-collection-filter')?.addEventListener('input', event => {
        collectionFilter = event.target.value.trim().toLocaleLowerCase('ru'); renderCollectionGrids();
    });
    document.querySelectorAll('[data-library-trigger]').forEach(button => button.onclick = () => {
        document.getElementById(button.dataset.libraryTrigger)?.click();
    });
    document.getElementById('lib-btn-all-tracks').onclick=()=>commands.select('all');
    document.getElementById('lib-btn-shuffle').onclick=async()=>{
        const tracks=commands.tracks();if(!tracks.length)return;
        try {if(!document.getElementById('pb-btn-shuffle').classList.contains('active')){const active=await window.pywebview.api.toggle_shuffle();document.querySelectorAll('#pb-btn-shuffle,#pp-btn-shuffle').forEach(button=>button.classList.toggle('active',Boolean(active)));}await window.pywebview.api.play_track(tracks[0],tracks,0);}
        catch{showToast('Не удалось включить плейлист','error');}
    };
    document.getElementById('lib-btn-playlist-options').onclick=event=>{
        const pl=commands.selected();if(pl){openPlaylistActions(pl,event);return;}
        const menu=document.getElementById('lib-playlist-actions');
        menu.innerHTML=actionDialogHeader('Любимые треки','Действия с коллекцией')+'<div class="lib-dialog-actions"><button data-trigger="lib-btn-play-all"><i data-lucide="play"></i><span>Воспроизвести</span></button><button data-trigger="lib-btn-shuffle"><i data-lucide="shuffle"></i><span>Перемешать</span></button><button data-trigger="lib-btn-download-all"><i data-lucide="download"></i><span>Скачать всё</span></button><button data-trigger="lib-btn-back-overview"><i data-lucide="library"></i><span>Обзор библиотеки</span></button></div>';
        menu.querySelectorAll('[data-trigger]').forEach(button=>button.onclick=()=>{menu.close();document.getElementById(button.dataset.trigger).click();});
        prepareActionDialog(menu,event);
    };
    document.querySelectorAll('.lib-sidebar-actions .lib-action-btn,#lib-btn-overview').forEach(button=>{
        const arrow=document.createElement('i');arrow.dataset.lucide='chevron-right';arrow.className='macos-library-chevron';arrow.setAttribute('aria-hidden','true');button.appendChild(arrow);
    });
    document.getElementById('lib-edit-cover').onclick=()=>{coverTarget=commands.selected();if(coverTarget)document.getElementById('lib-cover-file').click();};
    document.getElementById('lib-cover-file').onchange=async event=>{
        const file=event.target.files?.[0], playlist=coverTarget;event.target.value='';
        if(!file || !playlist)return;
        if(!['image/png','image/jpeg','image/webp'].includes(file.type) || file.size>2*1024*1024){showToast('Выберите PNG, JPEG или WebP размером до 2 МБ','warning');return;}
        try {const image=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});const data=savedCovers();data[String(playlist.id)]=image;localStorage.setItem(COVER_KEY,JSON.stringify(data));renderCollectionGrids();if(String(commands.selected()?.id)===String(playlist.id))updateLibraryHero('playlist',playlist,commands.tracks());showToast('Обложка сохранена в оформлении v2','success');}
        catch{showToast('Не удалось сохранить обложку. Попробуйте изображение меньшего размера.','error');}
    };
    document.getElementById('lib-playlist-filter').oninput=event=>{
        const query=event.target.value.trim().toLocaleLowerCase('ru');
        document.querySelectorAll('#lib-sidebar-playlists .lib-playlist-item').forEach(item=>item.hidden=!item.dataset.playlistName.includes(query));
    };
    document.getElementById('lib-mobile-playlists').onchange=event=>{const playlist=playlists.find(p=>String(p.id)===event.target.value);if(playlist)commands.select('playlist',playlist);else commands.overview();};
    document.getElementById('library-notices').onclick=()=>document.getElementById('home-notices').click();
    document.getElementById('library-profile').onclick=()=>document.getElementById('home-profile').click();
    const mirror=()=>{const source=document.getElementById('home-avatar-img'),target=document.getElementById('library-avatar-img');target.hidden=source.hidden;if(!source.hidden)target.src=source.src;};
    const profile=document.getElementById('home-profile');new MutationObserver(mirror).observe(profile,{subtree:true,attributes:true});mirror();
    renderCollectionGrids();
    renderIcons(document.getElementById('view-library'));
}


window.NeDotify = window.NeDotify || {};
window.NeDotify.openPlaylistActions = openPlaylistActions;
window.openPlaylistActions = openPlaylistActions;
