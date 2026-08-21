// NeDotify РІР‚" Artist Profile Module
import { createTrackElement, renderIcons, formatTime, filterVisibleTracks, escapeHtml } from './utils.js';
import { getCurrentTrack } from './player.js';

// Gradient seed backgrounds for fallback covers (visible ONLY if image loading fails)
const colors = [
    'linear-gradient(135deg, #f53d3d 0%, #ff803b 100%)', // Red/Orange
    'linear-gradient(135deg, #7b2cbf 0%, #e0aaff 100%)', // Purple
    'linear-gradient(135deg, #240b36 0%, #c31432 100%)', // Dark Red
    'linear-gradient(135deg, #0f2027 0%, #203a43 100%)', // Dark Slate
    'linear-gradient(135deg, #11998e 0%, #38ef7d 100%)', // Teal/Green
    'linear-gradient(135deg, #ff007f 0%, #ff80b3 100%)', // Pink
    'linear-gradient(135deg, #0052d4 0%, #4364f7 100%)', // Blue
    'linear-gradient(135deg, #fc4a1a 0%, #f7b733 100%)', // Orange/Yellow
    'linear-gradient(135deg, #1a2a6c 0%, #b21f1f 100%)', // Midnight Red
    'linear-gradient(135deg, #8a2387 0%, #e94057 100%)'  // Magenta
];

// SVG Note Icon for cover fallbacks (NO letter avatars)
const SVG_NOTE_FALLBACK = `
<svg class="fallback-note-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:50%;height:50%;opacity:0.6;position:relative;z-index:2;">
    <path d="M9 18V5l12-2v13"></path>
    <circle cx="6" cy="18" r="3"></circle>
    <circle cx="18" cy="16" r="3"></circle>
</svg>`;

// String hash function for picking gradient color seed
function hashString(str) {
    let hash = 0;
    if (!str || str.length === 0) return hash;
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash |= 0;
    }
    return hash;
}

// High Quality, Active Unsplash covers to guarantee loading on albums and tracks
const covers = [
    'https://images.unsplash.com/photo-1514525253161-7a46d19cd819?w=300', // Concert stage
    'https://images.unsplash.com/photo-1470225620780-dba8ba36b745?w=300', // DJ console
    'https://images.unsplash.com/photo-1498038432885-c6f3f1b912ee?w=300', // Neon performance
    'https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=300', // Studio Mic
    'https://images.unsplash.com/photo-1511735111819-9a3f7709049c?w=300', // Neon crowd
    'https://images.unsplash.com/photo-1506157786151-b8491531f063?w=300', // Band
    'https://images.unsplash.com/photo-1516450360452-9312f5e86fc7?w=300', // Concert fans
    'https://images.unsplash.com/photo-1487180142328-054b783fc471?w=300', // Vinyl spinner
    'https://images.unsplash.com/photo-1459749411175-04bf5292ceea?w=300', // Acoustic guitar
    'https://images.unsplash.com/photo-1507838153414-b4b713384a76?w=300'  // Headphones
];

// ─── Massive Predefined Mock Database (strictly YouTube & SoundCloud) ───

let profileGenerationId = 0;

const STATIC_TRACKS_PHARAOH = [
    { id: "g0XKrUoI5XA", title: "Дико, например", artist: "PHARAOH", playCount: "16 млн", year: 2017 },
    { id: "B4HYSzp6d_Q", title: "5 минут назад", artist: "PHARAOH", playCount: "31 млн", year: 2016 },
    { id: "mJTC4eu_Stw", title: "Black Siemens", artist: "PHARAOH", playCount: "10 млн", year: 2015 },
    { id: "UyIv7q8JSZE", title: "Лаллипап", artist: "PHARAOH", playCount: "24 млн", year: 2017 },
    { id: "_mFzdPFEbZE", title: "Фруктовый", artist: "PHARAOH", playCount: "5 млн", year: 2017 },
    { id: "YeGTEtdhHd0", title: "ИДОЛ", artist: "PHARAOH", playCount: "18 млн", year: 2017 },
    { id: "l_nK8tsNMvY", title: "Black Siemens (Remix)", artist: "PHARAOH", playCount: "1.5 млн", year: 2017 },
    { id: "X6-0P5N8C1I", title: "Champagne Squirt", artist: "PHARAOH", playCount: "33 млн", year: 2015 },
    { id: "c5i3Y4K0yT8", title: "На луне", artist: "PHARAOH", playCount: "38 млн", year: 2017 },
    { id: "K9s-n8zP2wA", title: "Одним целым", artist: "PHARAOH", playCount: "25 млн", year: 2020 },
    { id: "p0Z-8jK9uL1", title: "Smart", artist: "PHARAOH", playCount: "25 млн", year: 2018 }
];

const STATIC_TRACKS_LANA = [
    { id: "TdrL3QxjyVw", title: "Summertime Sadness", artist: "Lana Del Rey", playCount: "900 млн", year: 2012 },
    { id: "cE6wxDqdOV0", title: "Video Games", artist: "Lana Del Rey", playCount: "350 млн", year: 2012 },
    { id: "Bag1gUcwU0g", title: "Born To Die", artist: "Lana Del Rey", playCount: "550 млн", year: 2012 },
    { id: "o_1aF54DO60", title: "Young and Beautiful", artist: "Lana Del Rey", playCount: "650 млн", year: 2013 },
    { id: "1", title: "Blue Jeans", artist: "Lana Del Rey", playCount: "200 млн", year: 2012 },
    { id: "2", title: "West Coast", artist: "Lana Del Rey", playCount: "150 млн", year: 2014 },
    { id: "3", title: "Cinnamon Girl", artist: "Lana Del Rey", playCount: "100 млн", year: 2019 },
    { id: "4", title: "Brooklyn Baby", artist: "Lana Del Rey", playCount: "120 млн", year: 2014 }
];

const STATIC_TRACKS_WEEKND = [
    { id: "4NRXx6U8ABQ", title: "Blinding Lights", artist: "The Weeknd", playCount: "3.9 млрд", year: 2020 },
    { id: "34Na4j8HLjc", title: "Starboy", artist: "The Weeknd", playCount: "2.5 млрд", year: 2016 },
    { id: "yzTuBuRdAyA", title: "The Hills", artist: "The Weeknd", playCount: "2.2 млрд", year: 2015 },
    { id: "1", title: "Save Your Tears", artist: "The Weeknd", playCount: "1.5 млрд", year: 2020 },
    { id: "2", title: "Die For You", artist: "The Weeknd", playCount: "1.2 млрд", year: 2016 },
    { id: "3", title: "Can't Feel My Face", artist: "The Weeknd", playCount: "1.4 млрд", year: 2015 },
    { id: "4", title: "Call Out My Name", artist: "The Weeknd", playCount: "1 млрд", year: 2018 },
    { id: "5", title: "Often", artist: "The Weeknd", playCount: "800 млн", year: 2015 }
];

function mapStaticTracks(staticArray, albumName) {
    return staticArray.map((t, index) => {
        const ytId = t.id && t.id.length > 5 ? t.id : '';
        const realCover = ytId ? `https://i.ytimg.com/vi/${ytId}/hqdefault.jpg` : null;
        return {
            id: t.id ? `ytsearch1: ${t.artist} - ${t.title}` : `track_${t.artist.replace(/\s+/g, '')}_${index}`,
            title: t.title,
            artist: t.artist,
            album: albumName,
            duration: 180000, 
            release_date: `${t.year}-01-01`,
            is_favorite: false,
            source: "youtube",
            source_id: `ytsearch1: ${t.artist} - ${t.title}`,
            playCount: t.playCount,
            cover_url: realCover,
            is_search_query: true
        };
    });
}

// TODO: Replace this mock data with backend API calls once the backend implements artist profiles
const MOCK_ARTISTS = {
    'pharaoh': {
        name: 'PHARAOH',
        genres: 'Исполнитель',
        avatarUrl: 'https://i.ytimg.com/vi/g0XKrUoI5XA/maxresdefault.jpg',
        bio: 'PHARAOH (Глеб Геннадьевич Голубин, род. 11 августа 1996, Москва) — российский рэп-исполнитель и продюсер. Бывший участник коллектива Grindhouse и лидер Dead Dynasty.',
        albums: [
            { title: 'Pink Phloyd', year: 2017, cover: 'https://i.ytimg.com/vi/g0XKrUoI5XA/hqdefault.jpg' },
            { title: 'Phlora', year: 2014, cover: 'https://i.ytimg.com/vi/mJTC4eu_Stw/hqdefault.jpg' }
        ],
        tracks: mapStaticTracks(STATIC_TRACKS_PHARAOH, 'Pink Phloyd')
    },
    'lana del rey': {
        name: 'Lana Del Rey',
        genres: 'Baroque Pop / Dream Pop',
        avatarUrl: 'https://i.ytimg.com/vi/TdrL3QxjyVw/hqdefault.jpg',
        bio: 'Lana Del Rey (Элизабет Вулридж Грант) — американская певица, автор песен и поэтесса. Её музыка известна своим меланхоличным звучанием.',
        albums: [
            { title: 'Born to Die', year: 2012, cover: 'https://i.ytimg.com/vi/TdrL3QxjyVw/hqdefault.jpg' }
        ],
        tracks: mapStaticTracks(STATIC_TRACKS_LANA, 'Born to Die')
    },
    'the weeknd': {
        name: 'The Weeknd',
        genres: 'R&B / Synthwave / Pop',
        avatarUrl: 'https://i.ytimg.com/vi/4NRXx6U8ABQ/hqdefault.jpg',
        bio: 'The Weeknd (Эйбел Макконен Тесфайе) — канадский певец, автор песен и продюсер. Известен своим темным R&B стилем.',
        albums: [
            { title: 'Starboy', year: 2016, cover: 'https://i.ytimg.com/vi/4NRXx6U8ABQ/hqdefault.jpg' }
        ],
        tracks: mapStaticTracks(STATIC_TRACKS_WEEKND, 'Starboy')
    }
};

MOCK_ARTISTS['pharaon'] = MOCK_ARTISTS['pharaoh'];

function generateFallbackArtist(name) {
    return {
        name: name,
        genres: 'Исполнитель',
        avatarUrl: null,
        bio: `Исполнитель ${name} — музыкальный артист.`,
        albums: [],
        tracks: []
    };
}

function transliterateText(text) {
    if (!text) return '';
    const ru_en = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
        'ы': 'y', 'э': 'e', 'ю': 'yu', 'я': 'ya', 'ь': '', 'ъ': ''
    };
    return text.toLowerCase().split('').map(c => ru_en[c] || c).join('');
}

function isTrackByArtist(track, targetArtist) {
    if (!track || !targetArtist) return false;
    const targetNorm = targetArtist.toLowerCase().trim();
    const artistNorm = (track.artist || '').toLowerCase().trim();
    const titleNorm = (track.title || '').toLowerCase().trim();

    if (!targetNorm) return false;

    const targetTrans = transliterateText(targetNorm);
    const artistTrans = transliterateText(artistNorm);

    // Direct artist field match
    if (artistNorm && (artistNorm.includes(targetNorm) || targetNorm.includes(artistNorm))) return true;
    if (artistTrans && (artistTrans.includes(targetTrans) || targetTrans.includes(artistTrans))) return true;

    // Title feat / artist prefix match (e.g. "Artist - Song Title" or "Song (feat. Artist)")
    if (titleNorm.startsWith(targetNorm + ' -') || titleNorm.startsWith(targetNorm + ' –')) return true;
    if (titleNorm.includes('feat. ' + targetNorm) || titleNorm.includes('ft. ' + targetNorm) || titleNorm.includes('x ' + targetNorm)) return true;

    return false;
}

export async function fetchArtistTracks(artistName) {
    if (window.pywebview?.api?.search) {
        return new Promise((resolve) => {
            let collectedTracks = [];
            let isResolved = false;
            let timerId = null;

            const cleanup = () => {
                window.removeEventListener('app:search_results', handleSearch);
                window.removeEventListener('python:search_results', handleSearch);
                if (timerId) {
                    clearTimeout(timerId);
                    timerId = null;
                }
            };

            const finish = () => {
                if (isResolved) return;
                isResolved = true;
                cleanup();

                if (collectedTracks.length > 0) {
                    collectedTracks.sort((a, b) => (b.views || b.play_count || 0) - (a.views || a.play_count || 0));
                    const uniqueTracks = [];
                    const seen = new Set();
                    for (const t of collectedTracks) {
                        const key = `${(t.title || '').toLowerCase()}_${(t.artist || '').toLowerCase()}`;
                        if (!seen.has(key)) {
                            seen.add(key);
                            uniqueTracks.push(t);
                        }
                    }
                    resolve(uniqueTracks);
                } else {
                    const queryKey = artistName.toLowerCase().trim();
                    let artistData = MOCK_ARTISTS[queryKey] ? JSON.parse(JSON.stringify(MOCK_ARTISTS[queryKey])) : generateFallbackArtist(artistName);
                    resolve(artistData.tracks || []);
                }
            };

            const handleSearch = (e) => {
                const data = e.detail;
                if (data) {
                    const raw = Array.isArray(data) ? data : (data.tracks || []);
                    const filtered = filterVisibleTracks(raw).filter(t => 
                        (t.title || '').length > 0 && 
                        isTrackByArtist(t, artistName)
                    );
                    if (filtered.length > 0) {
                        collectedTracks = collectedTracks.concat(filtered);
                    }
                }
            };

            window.addEventListener('app:search_results', handleSearch);
            window.addEventListener('python:search_results', handleSearch);

            try {
                window.pywebview.api.search(artistName, 'all');
            } catch (err) {
                console.warn('Failed to call api.search for artist tracks:', err);
                finish();
                return;
            }

            timerId = setTimeout(finish, 5000);
        });
    }

    return new Promise((resolve) => {
        const queryKey = artistName.toLowerCase().trim();
        let artistData = MOCK_ARTISTS[queryKey] ? JSON.parse(JSON.stringify(MOCK_ARTISTS[queryKey])) : generateFallbackArtist(artistName);
        resolve(artistData.tracks || []);
    });
}

// ─── Backend Bridge Artist Profile Fetcher ───
export async function fetchArtistProfileFromBridge(artistName, timeoutMs = 6000) {
    if (!window.pywebview?.api?.get_artist_profile) {
        return null;
    }
    return new Promise((resolve) => {
        let isResolved = false;
        let timer = null;

        const cleanup = () => {
            document.removeEventListener('nedotify:artist_profile_ready', onReady);
            document.removeEventListener('nedotify:artist_profile_error', onError);
            window.removeEventListener('app:artist_profile_ready', onReady);
            window.removeEventListener('app:artist_profile_error', onError);
            if (timer) clearTimeout(timer);
        };

        const onReady = (e) => {
            const data = e.detail;
            if (!data) return;
            if (data.name && artistName) {
                const a = data.name.toLowerCase().trim();
                const b = artistName.toLowerCase().trim();
                if (!a.includes(b) && !b.includes(a)) return;
            }
            if (isResolved) return;
            isResolved = true;
            cleanup();
            resolve(data);
        };

        const onError = (e) => {
            const data = e.detail;
            if (data?.artist && artistName) {
                const a = data.artist.toLowerCase().trim();
                const b = artistName.toLowerCase().trim();
                if (!a.includes(b) && !b.includes(a)) return;
            }
            if (isResolved) return;
            isResolved = true;
            cleanup();
            resolve(null);
        };

        document.addEventListener('nedotify:artist_profile_ready', onReady);
        document.addEventListener('nedotify:artist_profile_error', onError);
        window.addEventListener('app:artist_profile_ready', onReady);
        window.addEventListener('app:artist_profile_error', onError);

        timer = setTimeout(() => {
            if (isResolved) return;
            isResolved = true;
            cleanup();
            resolve(null);
        }, timeoutMs);

        try {
            const res = window.pywebview.api.get_artist_profile(artistName);
            if (res && typeof res.then === 'function') {
                res.then(val => {
                    if (val && val.status !== 'loading' && val.status !== 'error') {
                        if (isResolved) return;
                        isResolved = true;
                        cleanup();
                        resolve(val);
                    } else if (val && val.status === 'error') {
                        if (isResolved) return;
                        isResolved = true;
                        cleanup();
                        resolve(null);
                    }
                }).catch(() => {});
            } else if (res && typeof res === 'object' && res.status !== 'loading' && res.status !== 'error' && (res.name || res.tracks || res.albums)) {
                isResolved = true;
                cleanup();
                resolve(res);
            }
        } catch (err) {
            console.warn('Failed to call get_artist_profile bridge:', err);
            if (isResolved) return;
            isResolved = true;
            cleanup();
            resolve(null);
        }
    });
}

// ─── API Avatar Fetcher (YouTube/SoundCloud logic simulation) ───
export async function fetchArtistAvatarFromApi(artistName, source = 'youtube') {
    return new Promise((resolve) => {
        setTimeout(() => {
            const normalized = artistName.toLowerCase();
            if (normalized.includes('pharaoh') || normalized.includes('pharaon')) {
                resolve('https://i.ytimg.com/vi/g0XKrUoI5XA/hqdefault.jpg');
            } else if (normalized.includes('del rey') || normalized.includes('lana')) {
                resolve('https://i.ytimg.com/vi/TdrL3QxjyVw/hqdefault.jpg');
            } else if (normalized.includes('weeknd')) {
                resolve('https://i.ytimg.com/vi/4NRXx6U8ABQ/hqdefault.jpg');
            } else {
                resolve('https://images.unsplash.com/photo-1516450360452-9312f5e86fc7?w=600&auto=format&fit=crop');
            }
        }, 300);
    });
}

// ─── Component 1: Artist Photo (Block 1) with Silhouette Fallback ───
export class ArtistPhotoComponent {
    constructor(artistData) {
        this.artistData = artistData;
    }

    render() {
        const container = document.createElement('div');
        container.className = 'artist-photo-card';
        
        const avatarUrl = this.artistData.avatarUrl || 'https://i.ytimg.com/vi/g0XKrUoI5XA/hqdefault.jpg';
        const img = document.createElement('img');
        img.src = avatarUrl;
        img.alt = this.artistData.name;
        img.style.width = '100%';
        img.style.height = '100%';
        img.style.objectFit = 'cover';
        
        img.onerror = () => {
            img.style.display = 'none';
            const silhouette = document.createElement('div');
            silhouette.className = 'fallback-silhouette';
            silhouette.style.cssText = 'position:absolute;inset:0;background:linear-gradient(135deg,#2a1b4e,#0f0c1b);display:flex;align-items:center;justify-content:center;';
            silhouette.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="width:48px;height:48px;opacity:0.4;color:white;">
                    <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>
                </svg>`;
            container.appendChild(silhouette);
        };
        
        container.appendChild(img);
        
        const overlay = document.createElement('div');
        overlay.className = 'artist-photo-overlay';
        const isMock = this.artistData.isMock !== false;
        const isDebug = window.APP_DEBUG || document.body.classList.contains('debug');
        const mockBadge = (isMock && isDebug) ? `<span style="background:rgba(239, 68, 68, 0.8);color:white;padding:2px 6px;border-radius:4px;font-size:10px;margin-left:6px;vertical-align:middle;text-transform:uppercase;letter-spacing:1px;font-weight:bold;" title="Данные артиста пока загружены из заглушки">MOCK (DEV)</span>` : '';
        
        overlay.innerHTML = `
            <div style="display:flex;align-items:center;">
                <span class="artist-genres-badge">${escapeHtml(this.artistData.genres)}</span>
                ${mockBadge}
            </div>
            <h2 class="artist-name-title">${escapeHtml(this.artistData.name)}</h2>
        `;
        container.appendChild(overlay);
        
        return container;
    }

    static renderSkeleton() {
        const container = document.createElement('div');
        container.className = 'artist-photo-card shimmer-bg';
        container.innerHTML = `
            <div class="artist-photo-overlay" style="background:none;">
                <div class="skeleton-text" style="width: 100px; height: 10px; background: rgba(255,255,255,0.15)"></div>
                <div class="skeleton-text" style="width: 180px; height: 24px; background: rgba(255,255,255,0.15)"></div>
            </div>
        `;
        return container;
    }
}

// ─── Component 2: Biography (Block 2) ───
export class ArtistBioComponent {
    constructor(artistData) {
        this.artistData = artistData;
    }

    render() {
        const container = document.createElement('div');
        container.className = 'artist-bio-card';
        
        container.innerHTML = `
            <h3 class="artist-card-title">
                <i data-lucide="info" style="width:16px;height:16px;color:var(--primary)"></i>
                Биография
            </h3>
            <div class="artist-bio-content">
                <p>${escapeHtml(this.artistData.bio)}</p>
            </div>
        `;
        
        return container;
    }

    static renderSkeleton() {
        const container = document.createElement('div');
        container.className = 'artist-bio-card';
        container.innerHTML = `
            <div class="skeleton-text heading shimmer-bg"></div>
            <div class="artist-bio-content" style="overflow:hidden">
                <div class="skeleton-text medium shimmer-bg"></div>
                <div class="skeleton-text shimmer-bg"></div>
                <div class="skeleton-text medium shimmer-bg"></div>
                <div class="skeleton-text short shimmer-bg"></div>
            </div>
        `;
        return container;
    }
}

// ─── Component 3: Albums Carousel (Block 3) with Fallback Gradients ───
export class ArtistAlbumsComponent {
    constructor(albums, onPlayAlbum) {
        // Sort albums strictly by year DESC
        this.albums = [...albums].sort((a, b) => b.year - a.year);
        this.onPlayAlbum = onPlayAlbum;
    }

    render() {
        const container = document.createElement('div');
        container.className = 'artist-albums-card';
        
        container.innerHTML = `
            <h3 class="artist-card-title">
                <i data-lucide="disc" style="width:16px;height:16px;color:var(--primary)"></i>
                Альбомы (${this.albums.length})
            </h3>
            <div class="artist-albums-carousel feed-scroll">
                ${this.albums.map((album, index) => {
                    const title = album.title || 'Unknown';
                    const gradIndex = Math.abs(hashString(title)) % colors.length;
                    const grad = colors[gradIndex];
                    const coverSrc = (album.cover && album.cover !== 'null') ? escapeHtml(album.cover) : ((album.cover_url && album.cover_url !== 'null') ? escapeHtml(album.cover_url) : '');
                    const imgTag = coverSrc ? `<img src="${coverSrc}" alt="${escapeHtml(album.title)}" onerror="this.onerror=null;this.style.display='none'" loading="lazy">` : '';
                    
                    return `
                    <div class="album-item-card" data-album-index="${index}">
                        <div class="album-cover-wrap fallback-gradient" style="background: ${grad}">
                            ${SVG_NOTE_FALLBACK}
                            ${imgTag}
                            <div class="album-play-overlay">
                                <button class="album-play-btn" title="Воспроизвести альбом">
                                    <i data-lucide="play" style="width:18px;height:18px;fill:currentColor"></i>
                                </button>
                            </div>
                        </div>
                        <div class="album-title" title="${escapeHtml(album.title)}">${escapeHtml(album.title)}</div>
                        <div class="album-year">${album.year ? album.year + ' г.' : ''}</div>
                    </div>
                `}).join('')}
            </div>
        `;

        container.querySelectorAll('.album-item-card').forEach(card => {
            card.style.cursor = 'pointer';
            const playBtn = card.querySelector('.album-play-btn');
            if (playBtn) {
                playBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const idx = card.dataset.albumIndex;
                    if (this.onPlayAlbum) this.onPlayAlbum(this.albums[idx]);
                });
            }
            card.addEventListener('click', () => {
                const idx = card.dataset.albumIndex;
                if (this.onPlayAlbum) this.onPlayAlbum(this.albums[idx]);
            });
        });
        
        return container;
    }

    static renderSkeleton() {
        const container = document.createElement('div');
        container.className = 'artist-albums-card';
        
        let albumSkeletons = '';
        for (let i = 0; i < 4; i++) {
            albumSkeletons += `
                <div class="album-item-card">
                    <div class="album-cover-wrap shimmer-bg" style="border:none"></div>
                    <div class="skeleton-text short shimmer-bg" style="margin-top:6px;margin-bottom:2px"></div>
                    <div class="skeleton-text shimmer-bg" style="width:40px;height:8px"></div>
                </div>
            `;
        }
        
        container.innerHTML = `
            <div class="skeleton-text heading shimmer-bg"></div>
            <div class="artist-albums-carousel" style="overflow:hidden">
                ${albumSkeletons}
            </div>
        `;
        return container;
    }
}

// ─── Component 4: Dynamic Scroll Track List (Block 4) Sorted strictly by playCount DESC ───
export class ArtistTracksComponent {
    constructor(tracks) {
        // Critical requirement: Sort tracks strictly by playCount DESC (popularity)
        this.tracks = [...tracks].sort((a, b) => (b.playCount || b.views || b.play_count || 0) - (a.playCount || a.views || a.play_count || 0));
        this.loadedCount = 20; // Load 20 tracks initially
    }

    render() {
        const container = document.createElement('div');
        container.className = 'artist-tracks-card';
        
        container.innerHTML = `
            <div class="artist-tracks-header">
                <h3 class="artist-card-title" style="margin-bottom:0">
                    <i data-lucide="sparkles" style="width:16px;height:16px;color:var(--primary)"></i>
                    Популярные треки (сортировка по прослушиваниям)
                </h3>
            </div>
            <div class="artist-tracks-list" id="artist-tracks-list-scroll">
                <!-- Tracks will be appended here -->
            </div>
        `;

        const listContainer = container.querySelector('#artist-tracks-list-scroll');
        const currentTrack = getCurrentTrack();

        const renderBatch = (start, count) => {
            const batch = this.tracks.slice(start, start + count);
            
            batch.forEach((track, i) => {
                const globalIndex = start + i;
                
                // Color gradient and fallback icon
                const title = track.title || 'Unknown';
                const gradIndex = Math.abs(hashString(title)) % colors.length;
                const grad = colors[gradIndex];
                
                // Track item element
                const trackEl = createTrackElement(track, globalIndex, this.tracks, currentTrack);
                
                // Format cover wrap to support fallback gradients
                const coverWrap = trackEl.querySelector('.track-cover-wrap');
                if (coverWrap) {
                    coverWrap.classList.add('fallback-gradient');
                    coverWrap.style.background = grad;
                    
                    const noteDiv = document.createElement('div');
                    noteDiv.style.cssText = 'position:absolute;inset:0;display:flex;align-items:center;justify-content:center;z-index:1;';
                    noteDiv.innerHTML = SVG_NOTE_FALLBACK;
                    coverWrap.insertBefore(noteDiv, coverWrap.firstChild);
                    
                    const img = coverWrap.querySelector('img');
                    if (img) {
                        img.onerror = () => {
                            img.style.display = 'none';
                        };
                    }
                }

                // Add formatted playCount (e.g. "129.0 млн прослушиваний") and release year
                const durationEl = trackEl.querySelector('.track-duration');
                if (durationEl) {
                    let playCountText = '';
                    const pc = track.playCount || track.views || track.play_count || 0;
                    if (pc >= 1000000) {
                        playCountText = `${(pc / 1000000).toFixed(pc >= 10000000 ? 0 : 1)} млн`;
                    } else if (pc >= 1000) {
                        playCountText = `${(pc / 1000).toFixed(0)} тыс.`;
                    } else if (pc > 0) {
                        playCountText = `${pc}`;
                    }

                    const year = track.release_date ? new Date(track.release_date).getFullYear() : (track.year || null);
                    
                    if (playCountText) {
                        const metaText = document.createElement('span');
                        metaText.style.fontSize = '11px';
                        metaText.style.color = 'var(--text-sec)';
                        metaText.style.marginRight = '16px';
                        metaText.textContent = `${playCountText} прослушиваний`;
                        durationEl.parentNode.insertBefore(metaText, durationEl);
                    }
                    
                    if (year && !isNaN(year)) {
                        const yearText = document.createElement('span');
                        yearText.style.fontSize = '11px';
                        yearText.style.color = 'var(--text-sec)';
                        yearText.style.marginRight = '12px';
                        yearText.textContent = `${year}`;
                        durationEl.parentNode.insertBefore(yearText, durationEl);
                    }
                }
                
                listContainer.appendChild(trackEl);
            });
            
            renderIcons();
        };

        // Render initial portion (20 tracks)
        renderBatch(0, this.loadedCount);

        // Infinite Scroll Event Listener
        listContainer.addEventListener('scroll', () => {
            const scrollTop = listContainer.scrollTop;
            const clientHeight = listContainer.clientHeight;
            const scrollHeight = listContainer.scrollHeight;

            // Load more if scrolled within 20px of the bottom
            if (scrollTop + clientHeight >= scrollHeight - 20) {
                if (this.loadedCount < this.tracks.length) {
                    const nextBatchSize = 20;
                    renderBatch(this.loadedCount, nextBatchSize);
                    this.loadedCount += nextBatchSize;
                }
            }
        });
        
        return container;
    }

    static renderSkeleton() {
        const container = document.createElement('div');
        container.className = 'artist-tracks-card';
        
        let trackSkeletons = '';
        for (let i = 0; i < 5; i++) {
            trackSkeletons += `
                <div style="display:flex; align-items:center; gap:12px; padding: 8px 12px; border-bottom: 1px solid rgba(255,255,255,0.02)">
                    <div class="shimmer-bg" style="width:48px; height:48px; border-radius:8px; flex-shrink:0;"></div>
                    <div style="flex:1">
                        <div class="skeleton-text medium shimmer-bg" style="height:10px; margin-bottom:6px"></div>
                        <div class="skeleton-text short shimmer-bg" style="height:8px; margin-bottom:0"></div>
                    </div>
                    <div class="shimmer-bg" style="width:30px; height:10px; border-radius:4px"></div>
                </div>
            `;
        }
        
        container.innerHTML = `
            <div class="skeleton-text heading shimmer-bg"></div>
            <div class="artist-tracks-list" style="overflow:hidden">
                ${trackSkeletons}
            </div>
        `;
        return container;
    }
}

// ─── Primary Loader: Combines Skeletons, Backend Bridge / API fetch and Components ───
export async function loadArtistProfile(artistName, targetContainer) {
    if (!targetContainer) return;
    const currentGen = ++profileGenerationId;
    
    // Clear and render layout shells
    targetContainer.innerHTML = '';
    const wrapper = document.createElement('div');
    wrapper.className = 'artist-profile-layout';
    
    const leftCol = document.createElement('div');
    leftCol.className = 'artist-col-left skeleton-active';
    
    const rightCol = document.createElement('div');
    rightCol.className = 'artist-col-right skeleton-active';
    
    wrapper.appendChild(leftCol);
    wrapper.appendChild(rightCol);
    targetContainer.appendChild(wrapper);
    
    // 1. Show skeletons
    leftCol.appendChild(ArtistPhotoComponent.renderSkeleton());
    leftCol.appendChild(ArtistBioComponent.renderSkeleton());
    rightCol.appendChild(ArtistAlbumsComponent.renderSkeleton());
    rightCol.appendChild(ArtistTracksComponent.renderSkeleton());
    renderIcons();

    const queryKey = artistName.toLowerCase().trim();
    let artistData = null;

    try {
        // Step 1: Attempt to fetch real artist profile from backend bridge
        const bridgeProfile = await fetchArtistProfileFromBridge(artistName);
        if (currentGen !== profileGenerationId) return; // Stale render protection

        if (bridgeProfile && (bridgeProfile.tracks?.length > 0 || bridgeProfile.albums?.length > 0 || bridgeProfile.bio || bridgeProfile.avatar_url)) {
            artistData = {
                name: bridgeProfile.name || artistName,
                genres: bridgeProfile.genres || (bridgeProfile.subscribers ? `${bridgeProfile.subscribers} подписчиков` : 'Исполнитель'),
                avatarUrl: bridgeProfile.avatar_url || bridgeProfile.avatarUrl || null,
                bio: bridgeProfile.bio || `Исполнитель ${bridgeProfile.name || artistName} — музыкальный артист.`,
                albums: bridgeProfile.albums || [],
                tracks: bridgeProfile.tracks || [],
                isMock: false
            };

            // If backend didn't provide avatar or tracks, fallback gracefully
            if (!artistData.avatarUrl) {
                artistData.avatarUrl = await fetchArtistAvatarFromApi(artistData.name, 'youtube');
            }
            if (currentGen !== profileGenerationId) return;

            if (!artistData.tracks || artistData.tracks.length === 0) {
                artistData.tracks = await fetchArtistTracks(artistData.name);
            }
            if (currentGen !== profileGenerationId) return;
        } else {
            // Step 2: Fallback to mock data or generated artist if bridge call returns empty/fails
            const fallback = MOCK_ARTISTS[queryKey] ? JSON.parse(JSON.stringify(MOCK_ARTISTS[queryKey])) : generateFallbackArtist(artistName);
            fallback.isMock = true;

            const [resolvedAvatar, tracks] = await Promise.all([
                fetchArtistAvatarFromApi(fallback.name, 'youtube'),
                fetchArtistTracks(fallback.name)
            ]);
            if (currentGen !== profileGenerationId) return;

            fallback.avatarUrl = fallback.avatarUrl || resolvedAvatar;
            if (tracks && tracks.length > 0) {
                fallback.tracks = tracks;
            }
            artistData = fallback;
        }

        // 3. Clear skeletons and render real components (with smooth fadeIn transitions)
        leftCol.innerHTML = '';
        leftCol.classList.remove('skeleton-active');
        
        rightCol.innerHTML = '';
        rightCol.classList.remove('skeleton-active');
        
        const photoComp = new ArtistPhotoComponent(artistData);
        leftCol.appendChild(photoComp.render());
        
        const bioComp = new ArtistBioComponent(artistData);
        leftCol.appendChild(bioComp.render());
        
        const onPlayAlbum = async (album) => {
            if (!album) return;
            const albumTracks = (artistData.tracks || []).filter(t => t.album && t.album.toLowerCase() === (album.title || '').toLowerCase());
            if (albumTracks.length > 0) {
                if (window.pywebview?.api?.play_track) {
                    window.pywebview.api.play_track(albumTracks[0], albumTracks, 0);
                }
                return;
            }

            // If not found in already loaded artist tracks, fetch via get_album_tracks
            if (window.pywebview?.api?.get_album_tracks) {
                try {
                    const fetched = await window.pywebview.api.get_album_tracks({
                        title: album.title,
                        artist: artistData.name,
                        source: album.source || 'youtube',
                        source_id: album.source_id || ''
                    });
                    if (fetched && fetched.length > 0) {
                        window.pywebview.api.play_track(fetched[0], fetched, 0);
                        return;
                    }
                } catch (e) {
                    console.error("Error playing album via get_album_tracks:", e);
                }
            }

            // Fallback: play available tracks
            const playList = artistData.tracks || [];
            if (window.pywebview?.api?.play_track && playList.length > 0) {
                window.pywebview.api.play_track(playList[0], playList, 0);
            }
        };
        
        if (artistData.albums && artistData.albums.length > 0) {
            const albumsComp = new ArtistAlbumsComponent(artistData.albums, onPlayAlbum);
            rightCol.appendChild(albumsComp.render());
        }
        
        const tracksComp = new ArtistTracksComponent(artistData.tracks || []);
        rightCol.appendChild(tracksComp.render());
        
        renderIcons();
    } catch (e) {
        if (currentGen !== profileGenerationId) return;
        console.error('Failed to load artist profile:', e);
        targetContainer.innerHTML = `<div class="empty-state">Ошибка загрузки профиля: ${escapeHtml(e.message)}</div>`;
    }
}



