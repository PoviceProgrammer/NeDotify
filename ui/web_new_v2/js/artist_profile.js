// NeDotify — Artist Profile Module
import { createTrackElement, renderIcons, formatTime, filterVisibleTracks, escapeHtml, getCoverFallbackGradient, SVG_NOTE_FALLBACK, extractDominantColor, openModalFocusTrap, closeModalFocusTrap, showToast } from './utils.js';
import { getCurrentTrack } from './player.js';

let profileGenerationId = 0;
let artistBioResizeObserver = null;
let artistCandidateView = null;
let currentArtistData = null;
let currentArtistTracks = [];
let artistTracksExpanded = false;
let activeBridgeCleanups = [];

const artistBioCache = new Map();

export function cancelActiveArtistRequests() {
    artistBioResizeObserver?.disconnect();
    artistBioResizeObserver = null;
    profileGenerationId++;
    artistCandidateView = null;
    while (activeBridgeCleanups.length > 0) {
        const cleanup = activeBridgeCleanups.pop();
        try { cleanup(); } catch (_) {}
    }
}
export const cancelArtistProfileRequests = cancelActiveArtistRequests;

const KNOWN_UNSPLITTABLE_ARTISTS = new Set([
    'tyler, the creator',
    'earth, wind & fire',
    'crosby, stills, nash & young',
    'crosby, stills & nash',
    'simon & garfunkel',
    'hall & oates',
    'daryl hall & john oates',
    'emerson, lake & palmer',
    'kool & the gang',
    'kc & the sunshine band',
    'blood, sweat & tears',
    'above & beyond',
    'florence + the machine',
    'florence and the machine',
    'huey lewis & the news',
    'tom petty and the heartbreakers',
    'bob marley & the wailers',
    'joan jett & the blackhearts',
    'marina and the diamonds'
]);

function splitArtistCredit(value, targetArtist = null) {
    const raw = String(value || '').trim();
    if (!raw) return [];
    if (targetArtist && raw.toLowerCase() === String(targetArtist).trim().toLowerCase()) {
        return [raw];
    }
    if (KNOWN_UNSPLITTABLE_ARTISTS.has(raw.toLowerCase())) {
        return [raw];
    }
    return raw.split(/\s*(?:,|&|\+|;|\bx\b|\bfeat\.?|\bft\.?|\bfeaturing\b)\s*/i)
        .map(name => name.trim()).filter(Boolean);
}

async function canonicalNames(names) {
    const api = window.pywebview?.api;
    if (!api?.get_canonical_artist_names) return [];
    const values = names.filter(name => typeof name === 'string' && name.trim()).map(name => name.trim()).slice(0, 500);
    if (!values.length) return [];
    try {
        const result = await api.get_canonical_artist_names(values);
        return Array.isArray(result) ? result : [];
    } catch (_) { return []; }
}

async function filterTracksByArtist(tracks, targetArtist) {
    const target = String(targetArtist || '').trim();
    const credits = tracks.map(track => splitArtistCredit(track?.artist, target));
    const names = [target, ...credits.flat()];
    const canonical = await canonicalNames(names);
    if (canonical.length < 1) return [];
    const targetKey = canonical[0];
    if (!targetKey) return [];
    let cursor = 1;
    const matches = credits.map(namesForTrack => {
        const identityKeys = canonical.slice(cursor, cursor + namesForTrack.length);
        cursor += namesForTrack.length;
        return identityKeys.includes(targetKey);
    });
    return tracks.filter((_, index) => matches[index]);
}

// export async function fetchArtistTracks( - removed dead code (ART-016)

// ─── Backend Bridge Artist Profile Fetcher ───
export async function fetchArtistProfileFromBridge(artistName, timeoutMs = 10000, artistRef = null) {
    if (!window.pywebview?.api?.get_artist_profile) return { status: 'unavailable' };
    const requestId = `artist-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    return new Promise(resolve => {
        let timer = null;
        let isResolved = false;

        const cleanup = () => {
            if (timer) {
                clearTimeout(timer);
                timer = null;
            }
            document.removeEventListener('nedotify:artist_profile_ready', receive);
            document.removeEventListener('nedotify:artist_profile_error', receive);
            const idx = activeBridgeCleanups.indexOf(cancel);
            if (idx !== -1) activeBridgeCleanups.splice(idx, 1);
        };

        const cancel = () => {
            if (isResolved) return;
            isResolved = true;
            cleanup();
            resolve({ status: 'cancelled', request_id: requestId });
        };

        const finish = data => {
            if (isResolved) return;
            isResolved = true;
            cleanup();
            resolve(data);
        };

        const receive = event => {
            if (event.detail?.request_id !== requestId) return;
            finish(event.detail);
        };

        activeBridgeCleanups.push(cancel);
        document.addEventListener('nedotify:artist_profile_ready', receive);
        document.addEventListener('nedotify:artist_profile_error', receive);

        timer = setTimeout(() => {
            finish({ status: 'unavailable', request_id: requestId });
        }, timeoutMs);

        try {
            Promise.resolve(window.pywebview.api.get_artist_profile(artistName, artistRef, requestId))
                .then(data => {
                    if (data?.status !== 'loading') finish(data || { status: 'unavailable' });
                })
                .catch(() => finish({ status: 'unavailable', request_id: requestId }));
        } catch (_) {
            finish({ status: 'unavailable', request_id: requestId });
        }
    });
}

function renderArtistCandidates(name, data, container, generation) {
    const candidates = data.candidates || [];
    artistCandidateView = { name, data, container, generation };
    container.innerHTML = `
        <div class="catalog-message" style="text-align:center; padding: 32px 16px;">
            <h2 style="font-size:24px; font-weight:700; margin-bottom:8px; color:var(--text-main);">Выберите исполнителя</h2>
            <p style="font-size:14px; color:var(--text-sec); margin-bottom:24px;">Найдено несколько вариантов. Ваш выбор будет сохранён.</p>
            <div class="catalog-candidates" style="display:grid; grid-template-columns:repeat(auto-fill, minmax(200px, 1fr)); gap:16px; max-width:800px; margin:0 auto;"></div>
        </div>
    `;
    const grid = container.querySelector('.catalog-candidates');
    for (const candidate of candidates) {
        const card = document.createElement('button');
        card.className = 'catalog-candidate';
        card.style.cssText = 'display:flex; flex-direction:column; align-items:center; gap:10px; padding:16px; border-radius:12px; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.04); color:#fff; cursor:pointer; transition:transform 0.2s, background-color 0.2s;';
        const source = ({youtube: 'YouTube Music', deezer: 'Deezer', itunes: 'iTunes'})[candidate.source] || candidate.source || '';
        card.innerHTML = `
            ${candidate.avatar_url ? `<img src="${escapeHtml(candidate.avatar_url)}" alt="" style="width:80px;height:80px;border-radius:50%;object-fit:cover;">` : '<span class="catalog-candidate-avatar" style="width:80px;height:80px;border-radius:50%;background:rgba(255,255,255,0.1);display:flex;align-items:center;justify-content:center;font-size:24px;">♪</span>'}
            <strong style="font-size:15px; text-align:center;">${escapeHtml(candidate.name)}</strong>
            <span style="font-size:12px; color:var(--text-sec);">${source}</span>
            ${candidate.preview_track ? `<span style="font-size:12px; color:var(--text-sec);">Трек: ${escapeHtml(candidate.preview_track)}</span>` : ''}
            ${candidate.matching_track ? `<span style="font-size:12px; color:var(--text-main);">Совпадает трек: ${escapeHtml(candidate.matching_track)}</span>` : ''}
            ${candidate.subscribers || candidate.genres ? `<span style="font-size:12px; color:var(--text-sec);">${escapeHtml(candidate.subscribers || candidate.genres)}</span>` : ''}
        `;
        card.addEventListener('click', () => {
            loadArtistProfile(name, container, {...candidate, context: data.context || null});
        });
        grid.appendChild(card);
    }
    if (data.require_candidates) {
        appendRealSearchResults(name, container, generation);
    }
}

document.addEventListener('nedotify:artist_candidates_ready', event => {
    const current = artistCandidateView;
    if (!current || current.generation !== profileGenerationId || event.detail?.request_id !== current.data.request_id) return;
    renderArtistCandidates(current.name, {...current.data, candidates: event.detail.candidates}, current.container, current.generation);
});

// S4-001: a free-text query is not an artist. Under the candidate list (and the
// "not found" status) show the REAL search results for the same text.
const REAL_SEARCH_WINDOW_MS = 8000;
function appendRealSearchResults(query, container, generation) {
    if (!query || generation !== profileGenerationId) return;
    if (!window.pywebview?.api?.search) return; // browser preview: no bridge

    let section = container.querySelector('.artist-real-search');
    if (section) return;
    section = document.createElement('div');
    section.className = 'artist-real-search';
    const heading = document.createElement('h3');
    heading.textContent = `Результаты поиска «${query}»`;
    section.appendChild(heading);
    container.appendChild(section);

    const collected = [];
    let closed = false;
    const render = () => {
        if (closed || generation !== profileGenerationId) return;
        if (!collected.length) return;
        if (!container.contains(section)) { cleanup(); return; } // view replaced

        // ART-012: remove blocking _rendered flag so tracks display from all incoming sources
        if (typeof section.querySelectorAll === 'function') {
            const oldTracks = section.querySelectorAll('.track-row, .track-item');
            oldTracks.forEach(el => el.remove());
        } else if (Array.isArray(section.children)) {
            section.children = section.children.filter(c => c.tagName === 'h3');
        }

        collected.forEach((track, index) => section.appendChild(createTrackElement(track, index, collected, getCurrentTrack())));
        renderIcons();
    };

    const handleResults = (event) => {
        if (closed || generation !== profileGenerationId) { cleanup(); return; }
        const data = event.detail || {};
        if (data.query && data.query !== query) return;
        const incoming = Array.isArray(data) ? data : (data.tracks || []);
        for (const track of incoming) {
            const key = `${track.source || ''}::${track.source_id || track.id || ''}`;
            if (collected.some(t => `${t.source || ''}::${t.source_id || t.id || ''}` === key)) continue;
            collected.push(track);
        }
        render();
    };

    const cleanup = () => {
        closed = true;
        window.removeEventListener('app:search_results', handleResults);
        window.removeEventListener('python:search_results', handleResults);
        if (timer) { clearTimeout(timer); timer = null; }
    };

    const timer = setTimeout(cleanup, REAL_SEARCH_WINDOW_MS);
    window.addEventListener('app:search_results', handleResults);
    window.addEventListener('python:search_results', handleResults);
    try {
        window.pywebview.api.search(query, 'all');
    } catch (_) {
        cleanup();
    }
}

async function renderArtistStatus(name, data, container, generation) {
    const unavailable = data?.status === 'unavailable';
    container.innerHTML = `
        <div class="catalog-message" style="text-align:center; padding: 48px 16px;">
            <h2 style="font-size:22px; font-weight:700; margin-bottom:8px; color:var(--text-main);">${unavailable ? 'Не удалось проверить исполнителя' : 'Исполнитель не найден в каталоге'}</h2>
            <p style="font-size:14px; color:var(--text-sec); margin-bottom:20px;">${unavailable ? 'Каталог временно недоступен. Попробуйте ещё раз.' : 'Проверьте имя или выберите другое название.'}</p>
            <button class="btn btn-secondary" style="padding:8px 20px; border-radius:9999px; background:rgba(255,255,255,0.1); border:1px solid rgba(255,255,255,0.2); color:#fff; cursor:pointer;">Повторить поиск</button>
        </div>
    `;
    container.querySelector('button')?.addEventListener('click', () => loadArtistProfile(name, container));
    appendRealSearchResults(name, container, generation);
    if (window.pywebview?.api?.get_library) {
        try {
            const library = await window.pywebview.api.get_library();
            if (generation !== profileGenerationId) return;
            const tracks = await filterTracksByArtist(library || [], name);
            if (tracks.length) {
                const title = document.createElement('h3');
                title.textContent = 'Треки из вашей библиотеки';
                container.appendChild(title);
                tracks.forEach((track, index) => container.appendChild(createTrackElement(track, index, tracks, getCurrentTrack())));
            }
        } catch (_) {}
    }
}

// ─── Primary Loader: Mounts inside #view-artist (Riff v44.0.0 Architecture) ───
export async function loadArtistProfile(artistName, targetContainer = null, artistRef = null) {
    const viewArtist = document.getElementById('view-artist');
    const container = viewArtist || targetContainer;
    if (!container) return;

    cancelActiveArtistRequests();
    const currentGen = ++profileGenerationId;
    artistCandidateView = null;
    artistTracksExpanded = false;

    // Riff elements inside #view-artist
    const hero = document.getElementById('artist-hero');
    const heroImg = document.getElementById('artist-hero-img');
    const nameEl = document.getElementById('artist-profile-name');
    const verifiedBadge = document.getElementById('artist-verified-badge');
    const btnPlayAll = document.getElementById('btn-artist-play-all');
    const btnShuffle = document.getElementById('btn-artist-shuffle');
    const fansLine = document.getElementById('artist-fans-line');
    const aboutCard = document.getElementById('artist-about-card');
    const bioEl = document.getElementById('artist-profile-bio');
    const btnBioMore = document.getElementById('btn-artist-bio-more');
    const horizTabs = document.getElementById('artist-horiz-tabs');
    const tabTracks = document.getElementById('artist-tab-tracks');
    const tabAlbums = document.getElementById('artist-tab-albums');
    const paneTracks = document.getElementById('artist-pane-tracks');
    const paneAlbums = document.getElementById('artist-pane-albums');
    const btnTracksToggle = document.getElementById('btn-artist-tracks-toggle');
    const tracksList = document.getElementById('artist-tracks-list');
    const albumsGrid = document.getElementById('artist-albums-grid');
    const fallbackContainer = document.getElementById('artist-fallback-container');
    const heroWrap = container.querySelector('.artist-hero-wrap');
    const contentSection = container.querySelector('.artist-content-section');
    const syncBioOverflow = () => {
        if (currentGen !== profileGenerationId || !bioEl?.getClientRects().length) return;
        const overflowing = bioEl.scrollHeight > bioEl.clientHeight + 1;
        bioEl.classList.toggle('fade-end', overflowing);
        btnBioMore?.classList.toggle('hidden', !overflowing);
    };
    if (bioEl && typeof ResizeObserver === 'function') {
        artistBioResizeObserver = new ResizeObserver(syncBioOverflow);
        artistBioResizeObserver.observe(bioEl);
    }

    // 1. Reset state and styles
    if (hero) {
        hero.style.removeProperty('--artist-accent-color');
        document.documentElement.style.removeProperty('--artist-accent-color');
    }
    if (heroWrap) heroWrap.style.display = '';
    if (contentSection) contentSection.style.display = '';
    if (fallbackContainer) {
        fallbackContainer.style.display = 'none';
        fallbackContainer.innerHTML = '';
    }

    if (nameEl) nameEl.textContent = artistName;
    if (verifiedBadge) verifiedBadge.classList.add('hidden');
    if (fansLine) {
        fansLine.textContent = '';
        fansLine.style.display = 'none';
    }
    if (heroImg) {
        heroImg.src = '';
        heroImg.style.display = 'none';
    }
    if (aboutCard) aboutCard.classList.add('hidden');
    if (bioEl) {
        bioEl.textContent = '';
        bioEl.classList.remove('fade-end');
    }
    if (btnBioMore) btnBioMore.classList.add('hidden');
    if (horizTabs) horizTabs.style.display = 'none';

    // Tabs reset
    if (tabTracks && tabAlbums && paneTracks && paneAlbums) {
        tabTracks.classList.add('active');
        tabAlbums.classList.remove('active');
        paneTracks.classList.remove('hidden');
        paneTracks.classList.add('active');
        paneAlbums.classList.add('hidden');
        paneAlbums.classList.remove('active');

        tabTracks.onclick = () => {
            tabTracks.classList.add('active');
            tabAlbums.classList.remove('active');
            paneTracks.classList.remove('hidden');
            paneTracks.classList.add('active');
            paneAlbums.classList.add('hidden');
            paneAlbums.classList.remove('active');
        };
        tabAlbums.onclick = () => {
            tabAlbums.classList.add('active');
            tabTracks.classList.remove('active');
            paneAlbums.classList.remove('hidden');
            paneAlbums.classList.add('active');
            paneTracks.classList.add('hidden');
            paneTracks.classList.remove('active');
        };
    }

    if (btnTracksToggle) {
        btnTracksToggle.disabled=false;
        btnTracksToggle.classList.add('hidden');
        btnTracksToggle.textContent = 'Показать все';
    }

    // 2. Render track skeletons
    if (tracksList) {
        tracksList.innerHTML = Array.from({ length: 5 }, () => `
            <div style="display:flex; align-items:center; gap:12px; padding: 10px 16px; border-bottom: 1px solid rgba(255,255,255,0.03); border-radius:10px;">
                <div class="shimmer-bg" style="width:48px; height:48px; border-radius:8px; flex-shrink:0;"></div>
                <div style="flex:1">
                    <div class="skeleton-text medium shimmer-bg" style="height:12px; margin-bottom:6px"></div>
                    <div class="skeleton-text short shimmer-bg" style="height:10px; margin-bottom:0"></div>
                </div>
                <div class="shimmer-bg" style="width:40px; height:12px; border-radius:4px"></div>
            </div>
        `).join('');
    }
    if (albumsGrid) albumsGrid.innerHTML = '';

    // 3. Bio from cache check
    const bioCacheKey = (artistName || '').toLowerCase();
    let bioFromCache = false;
    if (artistBioCache.has(bioCacheKey)) {
        const cachedBio = artistBioCache.get(bioCacheKey);
        if (cachedBio && bioEl) {
            bioFromCache = true;
            bioEl.textContent = cachedBio;
            if (aboutCard) aboutCard.classList.remove('hidden');
            requestAnimationFrame(syncBioOverflow);
        }
    }

    // Allow delivery after the backend's 8s catalogue budget expires.
    try {
        const bridgeProfile = await fetchArtistProfileFromBridge(artistName, 10000, artistRef);
        if (currentGen !== profileGenerationId) return;

        if (bridgeProfile?.status === 'ambiguous') {
            if (fallbackContainer) {
                renderArtistCandidates(artistName, bridgeProfile, fallbackContainer, currentGen);
                if (heroWrap) heroWrap.style.display = 'none';
                if (contentSection) contentSection.style.display = 'none';
                fallbackContainer.style.display = 'block';
            }
            return;
        }

        if (bridgeProfile?.status !== 'found') {
            if (fallbackContainer) {
                await renderArtistStatus(artistName, bridgeProfile, fallbackContainer, currentGen);
                if (heroWrap) heroWrap.style.display = 'none';
                if (contentSection) contentSection.style.display = 'none';
                fallbackContainer.style.display = 'block';
            }
            return;
        }

        currentArtistData = bridgeProfile;
        if (nameEl) nameEl.textContent = bridgeProfile.name || artistName;

        // Verified badge (ART-001)
        const isVerified = Boolean(bridgeProfile.verified === true || bridgeProfile.isVerified === true);
        if (verifiedBadge) verifiedBadge.classList.toggle('hidden', !isVerified);

        // Fans / listeners line (ART-001)
        const fans = bridgeProfile.fans || bridgeProfile.nb_fan || bridgeProfile.subscribers || 0;
        const listenersText = bridgeProfile.monthlyListeners || (fans > 0 ? `${Number(fans).toLocaleString()} слушателей` : '');
        if (fansLine) {
            if (listenersText) {
                fansLine.textContent = listenersText;
                fansLine.style.display = 'block';
            } else {
                fansLine.textContent = '';
                fansLine.style.display = 'none';
            }
        }

        // Avatar & Banner + dominant color (ART-001)
        const banner = bridgeProfile.banner || bridgeProfile.banner_url || bridgeProfile.avatar || bridgeProfile.avatar_url || '';
        const avatar = bridgeProfile.avatar || bridgeProfile.avatar_url || '';
        if (heroImg) {
            if (banner || avatar) {
                heroImg.src = banner || avatar;
                heroImg.style.display = 'block';
                heroImg.onload = () => {
                    try {
                        const rgb = extractDominantColor(heroImg);
                        if (rgb && hero) {
                            const c = `rgb(${rgb.r}, ${rgb.g}, ${rgb.b})`;
                            hero.style.setProperty('--artist-accent-color', c);
                            document.documentElement.style.setProperty('--artist-accent-color', c);
                        }
                    } catch (_) {}
                };
                heroImg.onerror = () => {
                    if (avatar && heroImg.src !== avatar) {
                        heroImg.src = avatar;
                    } else {
                        heroImg.style.display = 'none';
                    }
                };
            } else {
                heroImg.src = '';
                heroImg.style.display = 'none';
            }
        }

        // Bio handling
        if (!bioFromCache) {
            const rawBio = bridgeProfile.bio_ru || bridgeProfile.bio || bridgeProfile.bio_original || '';
            const cleanBio = rawBio.replace(/<[^>]*>/g, '').trim();
            if (cleanBio) {
                artistBioCache.set(bioCacheKey, cleanBio);
                if (bioEl) {
                    bioEl.textContent = cleanBio;
                    if (aboutCard) aboutCard.classList.remove('hidden');
                    requestAnimationFrame(syncBioOverflow);
                }
            } else {
                artistBioCache.set(bioCacheKey, '');
                if (aboutCard) aboutCard.classList.add('hidden');
                if (bioEl) {
                    bioEl.textContent = '';
                    bioEl.classList.remove('fade-end');
                }
            }
        }

        // Bio Modal wiring
        const bioModal = document.getElementById('artist-bio-modal');
        const btnCloseBio = document.getElementById('btn-close-artist-bio');
        const btnDismissBio = document.getElementById('btn-dismiss-artist-bio');
        if (bioModal && !bioModal._hasCloseWired) {
            bioModal._hasCloseWired = true;
            const closeBio = () => {
                bioModal.style.display = 'none';
                closeModalFocusTrap(bioModal);
            };
            if (btnCloseBio) btnCloseBio.onclick = closeBio;
            if (btnDismissBio) btnDismissBio.onclick = closeBio;
            bioModal.addEventListener('click', (e) => {
                if (e.target === bioModal) closeBio();
            });
        }

        if (btnBioMore) {
            btnBioMore.onclick = () => {
                if (!bioModal) return;
                const modalTitle = document.getElementById('artist-bio-modal-title');
                const modalBody = document.getElementById('artist-bio-modal-body');
                if (modalTitle) modalTitle.textContent = bridgeProfile.name || artistName;
                if (modalBody) modalBody.textContent = bioEl ? bioEl.textContent : '';
                bioModal.style.display = 'flex';
                openModalFocusTrap(bioModal, {
                    onClose: () => {
                        bioModal.style.display = 'none';
                        closeModalFocusTrap(bioModal);
                    }
                });
            };
        }

        // Popular tracks (Top 5 default with Show all / Show less toggle)
        const trackKey = track => `${track.source}:${track.id || track.source_id}`;
        const allTracks = [...new Map((bridgeProfile.tracks || []).map(track => [trackKey(track), track])).values()];
        allTracks.sort((a, b) => (b.playCount || b.views || b.play_count || 0) - (a.playCount || a.views || a.play_count || 0));
        currentArtistTracks = allTracks;

        let visibleArtistCount = 5;
        let albumOffset = 0;
        let hasCatalogPages = bridgeProfile.tracks_has_more === true && Boolean(window.pywebview?.api?.get_artist_tracks_page);
        let catalogPartial = bridgeProfile.catalog_partial === true;
        let catalogLimited = bridgeProfile.catalog_source_limited === true;
        function renderArtistTracks() {
            if (!tracksList) return;
            if (tracksList.parentElement) {
                let note = tracksList.parentElement.querySelector('.artist-catalog-status');
                if (!note) {
                    note = document.createElement('p');
                    note.className = 'artist-catalog-status';
                    note.setAttribute('role', 'status');
                    tracksList.parentElement.insertBefore(note, tracksList);
                }
                note.textContent = catalogPartial ? 'Каталог загружен частично. «Показать больше» продолжит загрузку.'
                    : catalogLimited ? 'iTunes вернул предельное число релизов. Полнота каталога не подтверждена.' : '';
                note.hidden = !note.textContent;
            }
            if (allTracks.length === 0) {
                tracksList.innerHTML = '<div class="empty-state" style="padding:24px;">Нет доступных треков</div>';
                return;
            }
            const count = Math.min(visibleArtistCount, allTracks.length);
            const visibleTracks = allTracks.slice(0, count);
            tracksList.innerHTML = '';
            visibleTracks.forEach((track, idx) => {
                tracksList.appendChild(createTrackElement(track, idx, allTracks, getCurrentTrack()));
            });
            renderIcons();
        }

        if (btnTracksToggle) {
            const syncMore = () => {
                btnTracksToggle.textContent = visibleArtistCount >= allTracks.length && !hasCatalogPages ? 'Свернуть' : 'Показать больше';
                btnTracksToggle.classList.toggle('hidden', allTracks.length <= 5 && !hasCatalogPages);
            };
            syncMore();
            btnTracksToggle.onclick = async () => {
                if (btnTracksToggle.disabled) return;
                if (visibleArtistCount >= allTracks.length && hasCatalogPages) {
                    btnTracksToggle.disabled = true;
                    btnTracksToggle.textContent = 'Загрузка каталога…';
                    try {
                        const page = await window.pywebview.api.get_artist_tracks_page({source:bridgeProfile.source,source_id:bridgeProfile.source_id,name:bridgeProfile.name},albumOffset);
                        if (currentGen !== profileGenerationId || page?.cancelled) return;
                        if (!page || page.success === false) throw new Error('Catalogue unavailable');
                        const seen = new Set(allTracks.map(trackKey));
                        for (const track of page.tracks || []) {
                            const key=trackKey(track);
                            if (!seen.has(key)) {seen.add(key);allTracks.push(track);}
                        }
                        if (Number.isInteger(page.next_offset) && page.next_offset >= albumOffset) albumOffset=page.next_offset;
                        hasCatalogPages = page.has_more === true;
                        catalogPartial = page.catalog_partial === true;
                        catalogLimited = page.catalog_source_limited === true;
                        if (Array.isArray(page.albums)) {
                            bridgeProfile.albums = page.albums;
                            renderArtistAlbums();
                        }
                        visibleArtistCount = Math.min(visibleArtistCount+30,allTracks.length);
                        if (page.retryable) showToast('Часть каталога недоступна. Повторите загрузку.', 'warning');
                    } catch {
                        if (currentGen === profileGenerationId) showToast('Не удалось загрузить каталог. Повторите попытку.', 'error');
                    } finally {
                        if (currentGen === profileGenerationId) {btnTracksToggle.disabled=false;syncMore();renderArtistTracks();}
                    }
                    return;
                }
                visibleArtistCount = visibleArtistCount >= allTracks.length ? 5 : visibleArtistCount + 30;
                artistTracksExpanded = visibleArtistCount > 5;
                syncMore();renderArtistTracks();
            };
        }

        renderArtistTracks();

        // Play All and Shuffle actions
        if (btnPlayAll) {
            btnPlayAll.onclick = () => {
                if (!allTracks.length) return;
                if (window.pywebview?.api?.play_track) {
                    window.pywebview.api.play_track(allTracks[0], allTracks, 0);
                } else if (window.NeDotify?.playTrack) {
                    window.NeDotify.playTrack(allTracks[0], allTracks);
                }
            };
        }
        if (btnShuffle) {
            btnShuffle.onclick = () => {
                if (!allTracks.length) return;
                const shuffled = [...allTracks].sort(() => Math.random() - 0.5);
                if (window.pywebview?.api?.play_track) {
                    window.pywebview.api.play_track(shuffled[0], shuffled, 0);
                } else if (window.NeDotify?.playTrack) {
                    window.NeDotify.playTrack(shuffled[0], shuffled);
                }
            };
        }

        // Albums Grid (ART-001)
        function renderArtistAlbums() {
        const albums = bridgeProfile.albums || [];
        if (albums.length === 0) {
            if (horizTabs) horizTabs.style.display = 'none';
            if (paneTracks) paneTracks.classList.remove('hidden');
            if (paneAlbums) paneAlbums.classList.add('hidden');
            if (albumsGrid) albumsGrid.innerHTML = '';
        } else {
            if (horizTabs) horizTabs.style.display = 'flex';
            if (albumsGrid) {
                albumsGrid.innerHTML = albums.map((alb, idx) => {
                    const coverSrc = alb.cover || alb.cover_url || '';
                    const yearStr = alb.year ? `${escapeHtml(alb.year)} г.` : '';
                    return `
                        <div class="artist-album-card" data-album-index="${idx}" role="button" tabindex="0">
                            <div class="artist-album-cover-wrap fallback-gradient">
                                ${coverSrc ? `<img src="${escapeHtml(coverSrc)}" alt="${escapeHtml(alb.title || '')}" loading="lazy">` : SVG_NOTE_FALLBACK}
                            </div>
                            <div class="artist-album-info">
                                <span class="artist-album-title" title="${escapeHtml(alb.title || '')}">${escapeHtml(alb.title || '')}</span>
                                <span class="artist-album-sub">${yearStr || escapeHtml(alb.artist || artistName)}</span>
                            </div>
                        </div>
                    `;
                }).join('');

                albumsGrid.querySelectorAll('.artist-album-card').forEach(card => {
                    const idx = Number(card.dataset.albumIndex);
                    const alb = albums[idx];
                    if (!alb) return;
                    const openAlb = () => {
                        if (window.openAlbumModal) {
                            window.openAlbumModal(alb);
                        } else if (window.playAlbum) {
                            window.playAlbum(alb);
                        }
                    };
                    card.onclick = openAlb;
                    card.onkeydown = (e) => {
                        if (e.key === 'Enter') {
                            e.preventDefault();
                            openAlb();
                        }
                    };
                });
            }
        }
        }
        renderArtistAlbums();

        renderIcons();
    } catch (e) {
        if (currentGen !== profileGenerationId) return;
        console.error('Failed to load artist profile:', e);
        if (fallbackContainer) {
            fallbackContainer.innerHTML = `<div class="empty-state">Ошибка загрузки профиля: ${escapeHtml(e.message)}</div>`;
            if (heroWrap) heroWrap.style.display = 'none';
            if (contentSection) contentSection.style.display = 'none';
            fallbackContainer.style.display = 'block';
        }
    }
}

// ─── Backward compatibility classes (for existing components & tests) ───
export class ArtistPhotoComponent {
    constructor(artistData) { this.artistData = artistData; }
    render() {
        const div = document.createElement('div');
        div.className = 'artist-photo-card';
        return div;
    }
    static renderSkeleton() {
        const div = document.createElement('div');
        div.className = 'artist-photo-card shimmer-bg';
        return div;
    }
}

const BIO_CACHE_TTL_MS = 7 * 24 * 60 * 60 * 1000;

export class ArtistBioComponent {
    constructor(artistData) {
        this.artistData = artistData || {};
        this.currentLang = 'ru';
    }
    render() {
        const div = document.createElement('div');
        div.className = 'artist-bio-card';
        const d = this.artistData;
        const source = (d.source || 'youtube').toLowerCase();
        const sid = d.source_id || d.id || '';
        const original = d.bio_original || d.bio || '';
        if (typeof localStorage !== 'undefined' && sid) {
            const key = `artist_bio_${source}_${sid}_ru`;
            if (d.bio_ru) {
                try {
                    localStorage.setItem(key, JSON.stringify({ v: d.bio_ru, o: original, t: Date.now() }));
                } catch (_) {}
            } else {
                try {
                    const raw = localStorage.getItem(key);
                    if (raw) {
                        const entry = JSON.parse(raw);
                        if (Date.now() - (entry.t || 0) > BIO_CACHE_TTL_MS) {
                            localStorage.removeItem(key);
                        } else if (entry.o && entry.o === original) {
                            d.bio_ru = entry.v;
                        } else {
                            localStorage.removeItem(key);
                        }
                    }
                } catch (_) {}
            }
        }
        return div;
    }
    static renderSkeleton() {
        const div = document.createElement('div');
        div.className = 'artist-bio-card';
        return div;
    }
}

export function fetchArtistAvatarFallback(name) {
    if (!name || !window.pywebview?.api?.get_artists_avatars) return Promise.resolve(null);
    return new Promise(resolve => {
        const handler = (e) => {
            window.removeEventListener('app:artists_avatars_ready', handler);
            resolve(e.detail?.avatars?.[name] || null);
        };
        window.addEventListener('app:artists_avatars_ready', handler, { once: true });
        try {
            window.pywebview.api.get_artists_avatars([name]);
        } catch (_) {
            window.removeEventListener('app:artists_avatars_ready', handler);
            resolve(null);
        }
    });
}

export class ArtistAlbumsComponent {
    constructor(albums, onPlayAlbum, onOpenAlbum) {
        this.albums = albums;
        this.onPlayAlbum = onPlayAlbum;
        this.onOpenAlbum = onOpenAlbum;
    }
    render() {
        const div = document.createElement('div');
        div.className = 'artist-albums-card';
        return div;
    }
    static renderSkeleton() {
        const div = document.createElement('div');
        div.className = 'artist-albums-card';
        return div;
    }
}

export class ArtistTracksComponent {
    constructor(tracks) { this.tracks = tracks; }
    render() {
        const div = document.createElement('div');
        div.className = 'artist-tracks-card';
        return div;
    }
    static renderSkeleton() {
        const div = document.createElement('div');
        div.className = 'artist-tracks-card';
        return div;
    }
}
