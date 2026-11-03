import { escapeHtml, getCoverUrl, coverImgHtml, renderIcons } from './utils.js';
import { openHomeDialog } from './home-shell.js';

let entries = [];
let generation = 0;
let refreshTimer = null;
let openArtist = null;
let initialized = false;
const photos = new Map();
const requestedPhotos = new Set();

function artistKey(name) {
    return String(name || '').normalize('NFKC').trim().replace(/\s+/g,' ').toLocaleLowerCase('ru');
}

export function historyToDiscovery(history) {
    const seen = new Set();
    const result = [];
    for (const track of history || []) {
        if (!track || typeof track !== 'object') continue;
        const name = String(track.artist || '').trim();
        const isArtist = name && !['unknown','unknown artist','неизвестный исполнитель','локальный файл','?','...'].includes(artistKey(name));
        const key = isArtist ? `artist:${artistKey(name)}` : `track:${track.source || ''}:${track.source_id || track.track_id || track.id || artistKey(track.title)}`;
        if (seen.has(key) || (!isArtist && !track.title)) continue;
        seen.add(key);
        result.push({key, name:isArtist ? name : track.title, isArtist:Boolean(isArtist), track});
    }
    return result;
}

function createHistoryCard(entry) {
    const card = document.createElement('button');
    card.className = 'search-listened-card';
    card.type = 'button';
    card.dataset.historyArtist = entry.isArtist ? entry.name : '';
    card.setAttribute('aria-label',`${entry.isArtist ? 'Открыть исполнителя' : 'Воспроизвести трек'}: ${entry.name}`);
    const photo = entry.isArtist && photos.get(entry.name);
    card.innerHTML = `${coverImgHtml({src:photo || getCoverUrl(entry.track),coverUrl:photo || entry.track.cover_url || '',sourceId:photo ? '' : entry.track.source_id || '',source:entry.track.source || '',alt:''})}<span class="search-listened-copy"><strong title="${escapeHtml(entry.name)}">${escapeHtml(entry.name)}</strong><span>${entry.isArtist ? 'Исполнитель' : 'Трек'}</span></span><span class="search-listened-arrow" aria-hidden="true"><i data-lucide="arrow-up-right"></i></span>`;
    card.addEventListener('click', async () => {
        document.getElementById('home-detail-dialog')?.close();
        if (entry.isArtist) openArtist(entry.name, entry.track);
        else {
            try { await window.pywebview.api.play_track({...entry.track,id:entry.track.track_id || entry.track.id}); }
            catch { window.dispatchEvent(new CustomEvent('nedotify:toast',{detail:{msg:'Не удалось включить трек. Повторите попытку.',type:'error'}})); }
        }
    });
    return card;
}

function renderHistoryCards() {
    const grid = document.getElementById('search-listened-grid');
    if (!grid) return;
    grid.replaceChildren();
    grid.setAttribute('aria-busy','false');
    if (!entries.length) {
        grid.innerHTML = '<div class="search-discovery-empty"><i data-lucide="headphones"></i><strong>Знакомая музыка появится здесь</strong><p>Найдите и послушайте первый трек — мы сохраним его в вашей истории.</p></div>';
    } else entries.slice(0,4).forEach(entry=>grid.appendChild(createHistoryCard(entry)));
    renderIcons(grid);
}

async function upgradeArtistPhotos() {
    const missing = entries.filter(e=>e.isArtist && !requestedPhotos.has(e.name)).map(e=>e.name);
    if (!missing.length || !window.pywebview?.api?.get_artists_avatars) return;
    missing.forEach(name=>requestedPhotos.add(name));
    try { await window.pywebview.api.get_artists_avatars(missing); }
    catch { missing.forEach(name=>requestedPhotos.delete(name)); }
}

export async function refreshSearchHistory() {
    const current = ++generation;
    await window.awaitBridge();
    try {
        const data = await window.pywebview.api.get_home_data();
        if (current !== generation) return;
        entries = historyToDiscovery(data?.history || []);
        renderHistoryCards();
        upgradeArtistPhotos();
    } catch {
        if (current !== generation) return;
        const grid = document.getElementById('search-listened-grid');
        if (!grid) return;
        grid.setAttribute('aria-busy','false');
        grid.innerHTML = '<div class="search-discovery-empty"><strong>Не удалось загрузить историю</strong><p>Поиск доступен. Историю можно запросить ещё раз.</p><button class="home-pill">Повторить</button></div>';
        grid.querySelector('button').onclick = refreshSearchHistory;
    }
}

export function setDiscoveryMode(mode = 'history') {
    document.getElementById('search-discovery')?.classList.toggle('hidden', mode !== 'history');
}

export function initSearchDiscovery(artistCallback) {
    if (initialized) return;
    initialized = true;
    openArtist = artistCallback;
    document.getElementById('search-history-all')?.addEventListener('click', () => {
        openHomeDialog('Уже прослушано Вами', container => {
            container.classList.add('search-history-dialog-grid');
            if (!entries.length) container.innerHTML = '<div class="search-discovery-empty">В истории пока нет прослушиваний.</div>';
            else entries.forEach(entry=>container.appendChild(createHistoryCard(entry)));
        });
    });
    document.getElementById('search-notices')?.addEventListener('click',()=>document.getElementById('home-notices')?.click());
    document.getElementById('search-profile')?.addEventListener('click',()=>document.getElementById('home-profile')?.click());
    const mirrorProfile = () => {
        const source = document.getElementById('home-avatar-img');
        const target = document.getElementById('search-avatar-img');
        if (source && target) { target.hidden = source.hidden; if (!source.hidden) target.src = source.src; }
        document.getElementById('search-profile')?.setAttribute('aria-label',document.getElementById('home-profile')?.getAttribute('aria-label') || 'Мой профиль');
        document.getElementById('search-notices')?.classList.toggle('has-notices',document.getElementById('home-notices')?.classList.contains('has-notices'));
    };
    const homeToolbar = document.querySelector('.home-toolbar');
    if (homeToolbar) new MutationObserver(mirrorProfile).observe(homeToolbar,{subtree:true,attributes:true,attributeFilter:['src','hidden','aria-label','class']});
    window.addEventListener('nedotify:app_ready',mirrorProfile);
    window.addEventListener('nedotify:page_changed',e=>{if(e.detail==='search') refreshSearchHistory();});
    const queueRefresh = () => {clearTimeout(refreshTimer);refreshTimer=setTimeout(refreshSearchHistory,1000);};
    document.addEventListener('nedotify:track_changed',queueRefresh);
    document.addEventListener('nedotify:state_changed',e=>{if(e.detail==='playing') queueRefresh();});
    window.addEventListener('app:artists_avatars_ready',e=>{
        for(const [name,url] of Object.entries(e.detail?.avatars || {})) { if(url) photos.set(name,url); else requestedPhotos.delete(name); }
        if(entries.some(entry=>photos.has(entry.name))) renderHistoryCards();
    });
    mirrorProfile();
    refreshSearchHistory();
}
