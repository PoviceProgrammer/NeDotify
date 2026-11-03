import { createTrackElement, renderIcons, escapeHtml, getCoverUrl, coverImgHtml, formatListeningTimeShort, renderPlaylistCoverCollage, showToast, openModalFocusTrap } from './utils.js';
import { getCurrentTrack } from './player.js';
import { getPlaylistCover } from './library-view.js';
import { selectSection, showLibraryOverview, createPlaylist, loadPlaylists } from './library.js';
import { openHomeDialog } from './home-shell.js';

let generation=0, topGeneration=0, refreshTimer=null, avatarPending=false;
let recent=[], profileData=null, playlists=[], selectedPeriod='all';
const number=new Intl.NumberFormat('ru');
const text=(id,value)=>{const el=document.getElementById(id);if(el)el.textContent=value;};
async function request(name,...args) {
    await window.awaitBridge();
    const method=window.pywebview?.api?.[name];if(typeof method!=='function')throw new Error('Profile method unavailable');
    // A native file chooser can stay open as long as the user needs.
    if(name==='select_avatar')return method(...args);
    let timer;
    try {return await Promise.race([method(...args),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Profile request timed out')),20000);})]);}
    finally {clearTimeout(timer);}
}
export function normalizeProfileTrack(track) {return {...track,id:track.track_id || track.id};}
export function profileTimestamp(raw) {
    if(!raw)return null;
    const value=String(raw).trim().replace(' ','T');
    if(!/^\d{4}-\d\d-\d\dT/.test(value))return null;
    const date=new Date(/(?:Z|[+-]\d\d:\d\d)$/.test(value)?value:`${value}Z`);
    return Number.isFinite(date.getTime())?date:null;
}
export function relativeProfileTime(raw,now=Date.now()) {
    const date=profileTimestamp(raw);if(!date)return '';
    const seconds=Math.round((date.getTime()-now)/1000);
    if(seconds>60)return new Intl.DateTimeFormat('ru',{day:'numeric',month:'short',year:'numeric'}).format(date);
    const format=new Intl.RelativeTimeFormat('ru',{numeric:'auto'});
    for(const [unit,size] of [['day',86400],['hour',3600],['minute',60]])if(Math.abs(seconds)>=size)return format.format(Math.round(seconds/size),unit);
    return 'Только что';
}
function state(container,message,retry) {
    container.replaceChildren();const box=document.createElement('div');box.className='profile-empty';
    const label=document.createElement('p');label.textContent=message;box.append(label);
    const button=document.createElement('button');button.className='home-pill';button.textContent=retry?'Повторить':'Найти музыку';button.onclick=retry || (()=>window.showPage('search'));box.append(button);container.append(box);
}
function decorateRow(track,index,list,metric) {
    const row=createTrackElement(normalizeProfileTrack(track),index,list.map(normalizeProfileTrack),getCurrentTrack());row.classList.add('profile-track-row');row.tabIndex=0;
    row.querySelector('.track-number')?.remove?.();
    const rank=document.createElement('span');rank.className='profile-track-rank';rank.textContent=index+1;row.prepend(rank);
    const duration=row.querySelector('.track-duration');if(duration){duration.className='profile-track-metric';duration.textContent=metric;}
    row.addEventListener('keydown',event=>{if(event.target===row && ['Enter',' '].includes(event.key)){event.preventDefault();row.click();}});
    row.querySelectorAll('button').forEach(button=>button.setAttribute('aria-label',button.title || 'Действие с треком'));
    return row;
}
function renderTop(tracks) {
    const container=document.getElementById('profile-top-tracks');container.replaceChildren();
    if(!tracks.length){state(container,selectedPeriod==='all'?'Здесь появятся ваши любимые треки':'За этот период прослушиваний пока нет');return;}
    tracks.slice(0,5).forEach((track,index)=>{
        const count=track.plays ?? track.play_count;
        const row=decorateRow(track,index,tracks,Number.isFinite(Number(count))?number.format(Number(count)):'—');
        row.querySelector('.profile-track-metric').title='Количество прослушиваний';container.appendChild(row);
    });renderIcons(container);
}
async function loadTop() {
    const current=++topGeneration,period=selectedPeriod;
    if(period==='all' && profileData){renderTop(profileData.most_played || []);return;}
    text('profile-top-tracks','Загружаем топ…');
    try {
        const data=await request('get_wrapped_stats',period);if(current!==topGeneration)return;
        if(!data || !Array.isArray(data.top_tracks))throw new Error('Invalid top response');renderTop(data.top_tracks);
    }catch{if(current===topGeneration)state(document.getElementById('profile-top-tracks'),'Не удалось загрузить топ',loadTop);}
}
function openHistory() {
    openHomeDialog('Последние прослушивания',content=>{
        content.className='profile-history-dialog';
        const note=document.createElement('p');note.className='profile-dialog-note';note.textContent='Последние доступные записи истории. Каждый трек показан один раз.';content.append(note);
        if(!recent.length){state(content,'История пока пуста');return;}
        recent.forEach((track,index)=>content.appendChild(decorateRow(track,index,recent,relativeProfileTime(track.played_at))));renderIcons(content);
    });
}
function renderRecent() {
    const container=document.getElementById('profile-recent');container.replaceChildren();
    const activity=document.getElementById('profile-activity');activity.replaceChildren();
    if(!recent.length){state(container,'Вы ещё ничего не слушали');state(activity,'Новые прослушивания появятся здесь');return;}
    recent.slice(0,5).forEach((track,index)=>{
        const card=document.createElement('article');card.className='profile-recent-card';
        card.innerHTML=`<button class="profile-cover-button" aria-label="Воспроизвести: ${escapeHtml(track.title || 'Трек')}">${coverImgHtml({src:getCoverUrl(track),alt:'',loading:'lazy'})}<span class="profile-cover-play"><i data-lucide="play"></i></span></button><strong title="${escapeHtml(track.title || '')}">${escapeHtml(track.title || 'Без названия')}</strong><button class="profile-card-artist">${escapeHtml(track.artist || 'Неизвестный исполнитель')}</button>`;
        card.querySelector('.profile-cover-button').onclick=()=>request('play_track',normalizeProfileTrack(track),recent.map(normalizeProfileTrack),index).catch(()=>showToast('Не удалось включить трек','error'));
        card.querySelector('.profile-card-artist').onclick=()=>{if(track.artist)window.searchArtistProfile?.(track.artist,normalizeProfileTrack(track));};container.appendChild(card);
    });
    recent.slice(0,3).forEach((track,index)=>activity.appendChild(decorateRow(track,index,recent,relativeProfileTime(track.played_at))));
    renderIcons(container);renderIcons(activity);
}
async function fillPlaylistCover(container,playlist,current) {
    const custom=getPlaylistCover(playlist.id);if(custom){container.innerHTML=coverImgHtml({src:custom,alt:''});return;}
    if(playlist.cover_url || playlist.cover_path){container.innerHTML=coverImgHtml({src:getCoverUrl(playlist),alt:''});return;}
    try {
        const data=await request('get_playlist_tracks',playlist.id);if(current!==generation || !container.isConnected)return;
        const tracks=Array.isArray(data)?data:data?.tracks;
        if(Array.isArray(tracks)&&tracks.length)container.innerHTML=renderPlaylistCoverCollage(tracks.slice(0,4).map(track=>({src:getCoverUrl(track),coverUrl:track.cover_url || '',sourceId:track.source_id || '',source:track.source || ''})));
    }catch{/* The local icon remains available. */}
}
function openCollection(type,playlist) {window.showPage('library');selectSection(type,playlist);}
function renderPlaylists(current) {
    const container=document.getElementById('profile-playlists');container.replaceChildren();
    const items=[{name:'Любимые',kind:'favorites',track_count:profileData?.favorite_count ?? 0},...playlists.slice(0,3).map(item=>({...item,kind:'playlist'}))];
    items.forEach(playlist=>{
        const card=document.createElement('article');card.className='profile-playlist-card';
        card.innerHTML=`<button class="profile-playlist-open" aria-label="Открыть: ${escapeHtml(playlist.name)}"><span class="profile-playlist-cover ${playlist.kind==='favorites'?'is-favorites':''}"><i data-lucide="${playlist.kind==='favorites'?'heart':'list-music'}"></i></span><strong title="${escapeHtml(playlist.name)}">${escapeHtml(playlist.name)}</strong><small>${number.format(Number(playlist.track_count)||0)} треков</small></button><button class="profile-playlist-play" aria-label="Воспроизвести: ${escapeHtml(playlist.name)}"><i data-lucide="play"></i></button>`;
        card.querySelector('.profile-playlist-open').onclick=()=>openCollection(playlist.kind,playlist);
        card.querySelector('.profile-playlist-play').onclick=async event=>{
            const button=event.currentTarget;button.disabled=true;
            try {
                const data=playlist.kind==='favorites'?await request('get_favorites'):await request('get_playlist_tracks',playlist.id);
                const tracks=Array.isArray(data)?data:data?.tracks;if(!Array.isArray(tracks))throw new Error('Invalid playlist');
                if(!tracks.length){showToast('В этой коллекции пока нет треков','info');return;}
                await request('play_track',tracks[0],tracks,0);
            }catch{showToast('Не удалось включить коллекцию','error');}finally{button.disabled=false;}
        };
        container.append(card);if(playlist.kind==='playlist')fillPlaylistCover(card.querySelector('.profile-playlist-cover'),playlist,current);
    });
    const create=document.createElement('button');create.className='profile-playlist-create';create.innerHTML='<i data-lucide="plus"></i><span>Создать плейлист</span>';create.onclick=()=>createPlaylist();container.append(create);renderIcons(container);
}
function refreshIdentity() {
    const settings=window.settings?.personalization || {};
    text('profile-display-name',settings.nickname || 'Пользователь NeDotify');
    const input=document.getElementById('profile-name-input');if(!document.getElementById('profile-edit-dialog').open)input.value=settings.nickname || '';
    text('profile-date-joined',settings.registration_date?`В NeDotify с ${settings.registration_date}`:'Ваш музыкальный профиль');
    const image=document.getElementById('profile-avatar-img'),icon=document.getElementById('profile-avatar-icon');
    const path=settings.avatar_path || window.settings?.app?.avatar_path;
    if(!path){image.style.display='none';icon.style.display='grid';return;}
    const url=`./api/avatar?path=${encodeURIComponent(path)}`;
    image.onload=()=>{image.style.display='block';icon.style.display='none';};image.onerror=()=>{image.style.display='none';icon.style.display='grid';};
    if(image.src!==url)image.src=url;
}
export async function loadProfile() {
    const current=++generation;refreshIdentity();
    const status=document.getElementById('profile-load-status');status.hidden=true;
    document.getElementById('view-profile').setAttribute('aria-busy','true');
    const [statsResult,playlistResult,wrappedResult]=await Promise.allSettled([request('get_profile_stats'),request('get_playlists'),request('get_wrapped_stats','all')]);
    if(current!==generation)return;
    document.getElementById('view-profile').setAttribute('aria-busy','false');
    const valid=statsResult.status==='fulfilled' && statsResult.value && typeof statsResult.value==='object' && !Array.isArray(statsResult.value) && 'total_tracks' in statsResult.value;
    if(!valid){status.hidden=false;return;}
    profileData=statsResult.value;recent=Array.isArray(profileData.recently_played)?profileData.recently_played:[];
    const wrapped=wrappedResult.status==='fulfilled'?wrappedResult.value:null;
    const plays=wrapped && typeof wrapped.total_plays==='number'?wrapped.total_plays:null;
    text('profile-stat-tracks',number.format(plays ?? profileData.total_tracks ?? 0));text('profile-stat-tracks-label',plays===null?'Треков в библиотеке':'Прослушиваний');
    text('profile-stat-time',formatListeningTimeShort(profileData.total_listening_time_ms || 0));text('profile-stat-favorites',number.format(profileData.favorite_count || 0));
    text('profile-stat-playlists',number.format(profileData.playlist_count || 0));
    if(playlistResult.status==='fulfilled' && Array.isArray(playlistResult.value)){playlists=playlistResult.value;renderPlaylists(current);}
    else state(document.getElementById('profile-playlists'),'Не удалось загрузить плейлисты',loadProfile);
    renderRecent();loadTop();
    const pinned=window.settings?.personalization?.pinned_track || window.settings?.app?.pinned_track;
    const section=document.getElementById('profile-pinned-section');section.hidden=!pinned;
    const pinnedList=document.getElementById('profile-pinned-track');pinnedList.replaceChildren();if(pinned)pinnedList.appendChild(decorateRow(pinned,0,[pinned],''));
    renderIcons(document.getElementById('view-profile'));
}
export function initProfile() {
    const dialog=document.getElementById('profile-edit-dialog');
    document.getElementById('profile-edit-button').onclick=()=>{refreshIdentity();dialog.showModal();openModalFocusTrap(dialog,{initialFocus:'#profile-name-input'});};
    const close=()=>dialog.close();document.getElementById('profile-edit-cancel').onclick=close;
    document.getElementById('profile-edit-form').onsubmit=async event=>{
        event.preventDefault();const name=document.getElementById('profile-name-input').value.trim();if(!name){document.getElementById('profile-name-input').focus();return;}
        const button=document.getElementById('btn-save-nickname');button.disabled=true;text('profile-edit-error','');
        try {const result=await request('save_setting','nickname',name,'personalization');if(result===false || result?.success===false)throw new Error('Profile save rejected');window.settings ??={};window.settings.personalization ??={};window.settings.personalization.nickname=name;refreshIdentity();dialog.close();window.dispatchEvent(new CustomEvent('nedotify:profile_updated'));showToast('Имя сохранено','success');}
        catch{text('profile-edit-error','Не удалось сохранить имя. Попробуйте ещё раз.');}finally{button.disabled=false;}
    };
    const chooseAvatar=async()=>{
        if(avatarPending)return;avatarPending=true;
        try {const path=await request('select_avatar');if(!path || typeof path!=='string')return;window.settings ??={};window.settings.personalization ??={};window.settings.personalization.avatar_path=path;refreshIdentity();window.dispatchEvent(new CustomEvent('nedotify:profile_updated'));showToast('Аватар обновлён','success');}
        catch{showToast('Не удалось изменить аватар','error');}finally{avatarPending=false;}
    };
    document.getElementById('btn-change-avatar').onclick=chooseAvatar;document.getElementById('profile-edit-avatar').onclick=chooseAvatar;
    document.getElementById('profile-top-period').onchange=event=>{selectedPeriod=event.target.value;loadTop();};
    document.querySelectorAll('[data-profile-history]').forEach(button=>button.onclick=openHistory);
    document.getElementById('profile-all-playlists').onclick=()=>{window.showPage('library');showLibraryOverview();};
    document.getElementById('profile-create-playlist').onclick=()=>createPlaylist();
    document.getElementById('profile-retry').onclick=loadProfile;
    document.getElementById('profile-stat-favorites-button').onclick=()=>openCollection('favorites');
    document.getElementById('profile-stat-playlists-button').onclick=()=>{window.showPage('library');showLibraryOverview();};
    document.getElementById('btn-create-local-playlist').onclick=async event=>{
        const button=event.currentTarget;button.disabled=true;
        try {const result=await request('create_local_playlist','Локальные');if(result===false || result?.success===false)throw new Error('Playlist creation failed');loadPlaylists();loadProfile();showToast('Плейлист из локальных треков создан','success');}
        catch{showToast('Не удалось создать локальный плейлист','error');}finally{button.disabled=false;}
    };
    const schedule=()=>{if(!document.getElementById('view-profile').classList.contains('active'))return;clearTimeout(refreshTimer);refreshTimer=setTimeout(loadProfile,450);};
    document.addEventListener('nedotify:track_changed',schedule);document.addEventListener('nedotify:state_changed',schedule);window.addEventListener('nedotify:playlists_changed',schedule);
    setInterval(()=>{if(!document.hidden)schedule();},30000);
    document.getElementById('view-profile').addEventListener('click',event=>{if(event.target.closest('.like-btn'))schedule();});
    window.addEventListener('nedotify:page_changed',event=>{if(event.detail!=='profile'){generation++;topGeneration++;clearTimeout(refreshTimer);}});
    refreshIdentity();
}
