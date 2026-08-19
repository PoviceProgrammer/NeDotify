import { formatTime, formatListeningTime, renderIcons, getCoverUrl, escapeHtml, coverImgHtml } from './utils.js?v=20260817_3';

const feedTimeouts = new Map();
let trackChangeCount = 0;

function renderSkeletons(containerId, count = 4) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';
    for (let i = 0; i < count; i++) {
        const card = document.createElement('div');
        card.className = 'skeleton-card';
        card.innerHTML = `
            <div class="skeleton-cover"></div>
            <div class="skeleton-title"></div>
            <div class="skeleton-sub"></div>
        `;
        container.appendChild(card);
    }
}

export function clearFeedTimeout(sectionId) {
    if (feedTimeouts.has(sectionId)) {
        clearTimeout(feedTimeouts.get(sectionId));
        feedTimeouts.delete(sectionId);
    }
}

function renderRetryButton(containerId, retryFn) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '<div style="display:flex;justify-content:center;width:100%"><button class="retry-btn">Повторить</button></div>';
    container.querySelector('.retry-btn').addEventListener('click', () => {
        renderSkeletons(containerId);
        retryFn();
    });
}

export async function loadHome(isTrackChange = false) {
    await window.awaitBridge();
    if (!window.pywebview?.api) return;

    try {
        const data = await window.pywebview.api.get_home_data();

        setElText('stat-tracks', data.total_tracks || 0);
        setElText('stat-time', formatListeningTime(data.total_listening_ms || 0));
        setElText('stat-playlists', data.playlists?.length || 0);
        setElText('stat-favorites', data.favorites_count || 0);

        // History
        if (data.history && data.history.length > 0) {
            renderHistory(data.history);
        }

        // Analytics (Local Last.fm)
        if (data.analytics) {
            setElText('stat-time', formatListeningTime((data.analytics.total_time_seconds || 0) * 1000));
            renderTopTracks(data.analytics.top_tracks || []);
            renderTopArtists(data.analytics.top_artists || []);
        }

        // NeDotify Wrapped Analytics
        loadWrappedStats(currentWrappedPeriod);

        // Decide whether to refresh recommendations/mixes/etc.
        let shouldLoadFeeds = !isTrackChange;
        if (isTrackChange) {
            trackChangeCount++;
            if (trackChangeCount >= 10) {
                trackChangeCount = 0;
                shouldLoadFeeds = true;
            }
        }

        if (shouldLoadFeeds) {
            renderSkeletons('home-popular');
            renderSkeletons('home-recommended');
            renderSkeletons('home-releases');
            renderSkeletons('home-mixes');

            if (window.pywebview.api.get_popular_tracks) window.pywebview.api.get_popular_tracks();
            if (window.pywebview.api.get_feed) window.pywebview.api.get_feed(10);
            if (window.pywebview.api.get_home_releases) window.pywebview.api.get_home_releases(10);
            if (window.pywebview.api.get_home_mixes) window.pywebview.api.get_home_mixes(10);
            if (window.pywebview.api.get_authentic_home_feed) window.pywebview.api.get_authentic_home_feed(5);
        }

        // Artists
        if (window.pywebview.api.get_home_artists) {
            renderSkeletons('home-artists');
            window.pywebview.api.get_home_artists(15);
            feedTimeouts.set('home-artists', setTimeout(() => {
                renderRetryButton('home-artists', () => {
                    feedTimeouts.set('home-artists', setTimeout(() => renderRetryButton('home-artists', () => window.pywebview.api.get_home_artists(15)), 15000));
                    window.pywebview.api.get_home_artists(15);
                });
            }, 15000));
        }

        // Playlists
        if (window.pywebview.api.get_playlists) {
            const playlists = await window.pywebview.api.get_playlists();
            if (playlists && playlists.length > 0) renderHomePlaylists(playlists);
        }
    } catch (e) {
        console.error('Error loading home:', e);
    }
}

function renderHistory(tracks) {
    const container = document.getElementById('home-history');
    if (!container) return;
    container.innerHTML = '';
    tracks.slice(0, 10).forEach((track, idx) => {
        container.appendChild(createFeedCard(track, tracks, idx));
    });
    renderIcons();
}

export function renderPopular(tracks) {
    clearFeedTimeout('home-popular');
    renderFeedSection('home-popular', tracks);
}

export function renderRecommendations(tracks) {
    clearFeedTimeout('home-recommended');
    const sec = document.getElementById('home-recommended-section');
    if (sec) sec.style.display = (tracks && tracks.length > 0) ? 'block' : 'none';
    renderFeedSection('home-recommended', tracks);
}

export function renderReleases(tracks) {
    clearFeedTimeout('home-releases');
    renderFeedSection('home-releases', tracks);
}

export function renderMixes(tracks) {
    clearFeedTimeout('home-mixes');
    renderFeedSection('home-mixes', tracks);
}

export function renderAuthenticHome(sections) {
    const container = document.getElementById('home-authentic-feed');
    if (!container) return;
    
    container.innerHTML = '';
    
    sections.forEach((section, index) => {
        const sectionId = `auth-section-${index}`;
        
        // Create section wrapper
        const sectionEl = document.createElement('div');
        sectionEl.className = 'feed-section';
        
        // Title
        const titleEl = document.createElement('div');
        titleEl.className = 'feed-title';
        titleEl.textContent = section.title || 'Рекомендуем';
        sectionEl.appendChild(titleEl);
        
        // Scroll container
        const scrollEl = document.createElement('div');
        scrollEl.className = 'feed-scroll';
        scrollEl.id = sectionId;
        
        section.items.forEach(item => {
            if (item.type === 'track') {
                const trackData = {
                    title: item.title,
                    artist: item.artist,
                    cover_url: item.cover_url,
                    source: item.source,
                    source_id: item.source_id,
                    source_url: item.source_url,
                    duration: item.duration || 0
                };
                
                const card = document.createElement('div');
                card.className = 'feed-card';
                card.innerHTML = `
                    <div class="feed-card-cover">
                        ${coverImgHtml({ src: item.cover_url || '', coverUrl: item.cover_url || '', sourceId: item.source_id || '', source: 'youtube' })}
                        <div class="feed-card-overlay">
                            <button class="feed-card-play"><i data-lucide="play" style="width:14px;height:14px;fill:currentColor"></i></button>
                        </div>
                    </div>
                    <div class="feed-card-title">${escapeHtml(item.title || 'Unknown')}</div>
                    <div class="feed-card-sub">${escapeHtml(item.artist || '')}</div>
                `;
                
                card.onclick = () => {
                    const allTracks = section.items
                        .filter(i => i.type === 'track')
                        .map(i => ({
                            title: i.title,
                            artist: i.artist,
                            cover_url: i.cover_url,
                            source: i.source,
                            source_id: i.source_id,
                            source_url: i.source_url,
                            duration: i.duration || 0
                        }));
                    if (window.pywebview && window.pywebview.api && window.pywebview.api.play_track) {
                        window.pywebview.api.play_track(trackData, allTracks);
                    }
                };
                scrollEl.appendChild(card);
            } else if (item.type === 'playlist' || item.type === 'album') {
                const card = document.createElement('div');
                card.className = 'feed-card';
                card.innerHTML = `
                    <div class="feed-card-cover" style="background-image: url('${escapeHtml(item.cover_url)}')">
                        <div class="feed-card-overlay">
                            <button class="feed-card-play"><i data-lucide="play" style="width:14px;height:14px"></i></button>
                        </div>
                    </div>
                    <div class="feed-card-title">${escapeHtml(item.title)}</div>
                    <div class="feed-card-sub">${escapeHtml(item.artist || (item.type === 'album' ? 'Альбом' : 'Микс'))}</div>
                `;
                card.onclick = async () => {
                    if (window.pywebview && window.pywebview.api && window.pywebview.api.get_playlist_tracks) {
                        window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: `Загрузка: ${item.title}...`, type: 'info' } }));
                        try {
                            const res = await window.pywebview.api.get_playlist_tracks(item.id, item.source || 'youtube', 50);
                            if (res && res.success && res.tracks && res.tracks.length > 0) {
                                if (window.pywebview.api.play_track) {
                                    window.pywebview.api.play_track(res.tracks[0], res.tracks, 0);
                                }
                            } else {
                                const errMsg = (res && res.error) || 'Не удалось загрузить треки';
                                window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: errMsg, type: 'error' } }));
                            }
                        } catch (err) {
                            window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: String(err), type: 'error' } }));
                        }
                    }
                };
                scrollEl.appendChild(card);
            } else if (item.type === 'custom_playlist') {
                const card = document.createElement('div');
                card.className = 'feed-card';
                card.innerHTML = `
                    <div class="feed-card-cover" style="background-image: url('${escapeHtml(item.cover_url)}')">
                        <div class="feed-card-overlay">
                            <button class="feed-card-play"><i data-lucide="play" style="width:14px;height:14px"></i></button>
                        </div>
                    </div>
                    <div class="feed-card-title">${escapeHtml(item.title)}</div>
                    <div class="feed-card-sub">${escapeHtml(item.artist || 'Специально для вас')}</div>
                `;
                card.onclick = () => {
                    if (window.pywebview && window.pywebview.api && window.pywebview.api.play_track) {
                        window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: `Включаю: ${item.title}...`, type: 'info' } }));
                        if (item.tracks && item.tracks.length > 0) {
                            window.pywebview.api.play_track(item.tracks[0], item.tracks);
                        }
                    }
                };
                scrollEl.appendChild(card);
            }
        });
        
        sectionEl.appendChild(scrollEl);
        container.appendChild(sectionEl);
    });
    
    renderIcons();
}

export function renderHomePlaylists(playlists) {
    const container = document.getElementById('home-playlists');
    if (!container) return;
    container.innerHTML = '';

    playlists.forEach(pl => {
        const card = document.createElement('div');
        card.className = 'feed-card';
        card.innerHTML = `
            <div class="feed-card-cover" style="display:flex;align-items:center;justify-content:center">
                <i data-lucide="list-music" style="width:32px;height:32px;color:var(--text-sec)"></i>
                <div class="feed-card-overlay">
                    <button class="feed-card-play"><i data-lucide="play" style="width:14px;height:14px"></i></button>
                </div>
            </div>
            <div class="feed-card-title">${escapeHtml(pl.name)}</div>
            <div class="feed-card-sub">${pl.track_count || 0} треков</div>
        `;
        card.addEventListener('click', async () => {
            if (window.pywebview?.api?.get_playlist_tracks) {
                const res = await window.pywebview.api.get_playlist_tracks(pl.id);
                const tracks = Array.isArray(res) ? res : (res && Array.isArray(res.tracks) ? res.tracks : []);
                if (tracks && tracks.length > 0) {
                    window.pywebview.api.play_track(tracks[0], tracks);
                }
            }
        });
        container.appendChild(card);
    });
    renderIcons();
}

export function renderArtists(artists) {
    const container = document.getElementById('home-artists');
    if (!container) return;
    const sec = container.closest('.feed-section');
    if (sec) {
        sec.classList.remove('hidden');
        sec.style.display = '';
    }
    container.innerHTML = '';

    if (!artists || artists.length === 0) {
        container.innerHTML = '<div class="empty-state text-sm" style="padding:20px">Нет данных</div>';
        return;
    }

    artists.forEach(artist => {
        const card = document.createElement('div');
        card.className = 'feed-card artist-card';
        card.style.minWidth = '120px';
        card.style.maxWidth = '120px';
        const cover = getCoverUrl(artist);
        card.innerHTML = `
            <div class="feed-card-cover">
                ${coverImgHtml({ src: cover, coverUrl: artist.cover_url || '' })}
            </div>
            <div class="feed-card-title" style="text-align:center">${escapeHtml(artist.artist)}</div>
        `;
        card.addEventListener('click', () => {
            const input = document.getElementById('search-input');
            if (input) {
                input.value = artist.artist;
                if (window.showPage) window.showPage('search');
                input.dispatchEvent(new Event('input', { bubbles: true }));
            }
        });
        container.appendChild(card);
    });
    renderIcons();
}

function renderFeedSection(containerId, tracks) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';

    if (!tracks || tracks.length === 0) {
        container.innerHTML = '<div class="empty-state text-sm" style="padding:20px">Нет данных</div>';
        return;
    }

    tracks.forEach((track, idx) => {
        container.appendChild(createFeedCard(track, tracks, idx));
    });
    renderIcons();
}

function createFeedCard(track, trackList = null, trackIndex = 0) {
    const card = document.createElement('div');
    card.className = 'feed-card';

    if (track.type === 'custom_playlist') {
        // Generate consistent vibrant colors based on title
        let hash = 0;
        const safeTitle = track.title || '';
        for (let i = 0; i < safeTitle.length; i++) hash = safeTitle.charCodeAt(i) + ((hash << 5) - hash);
        const hue1 = Math.abs(hash % 360);
        const hue2 = (hue1 + 40 + Math.abs((hash >> 2) % 60)) % 360;
        
        card.innerHTML = `
            <div class="feed-card-cover" style="background: linear-gradient(135deg, hsl(${hue1}, 85%, 55%), hsl(${hue2}, 85%, 45%)); overflow: hidden; position: relative;">
                <!-- Decorative wave pattern -->
                <div style="position: absolute; bottom: -20%; right: -20%; width: 140%; height: 100%; background: linear-gradient(to top right, rgba(0,0,0,0.4), transparent); border-top-left-radius: 50%; transform: rotate(-15deg);"></div>
                
                <!-- If there's a cover_url, show it subtly or as a small badge. Otherwise just colors. -->
                ${track.cover_url && !track.cover_url.includes('hqdefault') ? `<div style="position:absolute; bottom: -10px; right: -10px; width: 60%; height: 60%; border-radius: 12px; background-image: url('${escapeHtml(track.cover_url)}'); background-size: cover; box-shadow: 0 8px 16px rgba(0,0,0,0.4); transform: rotate(-10deg); opacity: 0.8;"></div>` : ''}
                
                <!-- YT Music style persistent play icon ring -->
                <div style="position: absolute; top: 12px; left: 12px; width: 32px; height: 32px; border-radius: 50%; background: #000; border: 2px solid hsl(${hue1}, 80%, 70%); display:flex; align-items:center; justify-content:center; box-shadow: 0 4px 8px rgba(0,0,0,0.3);">
                    <i data-lucide="play" style="width:12px;height:12px;fill:hsl(${hue1}, 80%, 70%); color:hsl(${hue1}, 80%, 70%); margin-left: 2px;"></i>
                </div>
                
                <div class="feed-card-overlay">
                    <button class="feed-card-play" style="background: rgba(0,0,0,0.6);"><i data-lucide="play" style="width:16px;height:16px;fill:#fff;color:#fff"></i></button>
                </div>
            </div>
            <div class="feed-card-title">${escapeHtml(track.title)}</div>
            <div class="feed-card-sub">${escapeHtml(track.artist || 'Микс')}</div>
        `;
        card.addEventListener('click', () => {
            if (window.pywebview?.api?.play_track && track.tracks && track.tracks.length > 0) {
                window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: `Включаю: ${track.title}...`, type: 'info' } }));
                window.pywebview.api.play_track(track.tracks[0], track.tracks, 0);
            }
        });
        return card;
    }

    const cover = getCoverUrl(track);
    card.innerHTML = `
        <div class="feed-card-cover">
            ${coverImgHtml({ src: cover, coverUrl: track.cover_url || '', sourceId: track.source_id || '', source: track.source || '' })}
            <div class="feed-card-overlay">
                <button class="feed-card-play"><i data-lucide="play" style="width:14px;height:14px;fill:currentColor"></i></button>
            </div>
        </div>
        <div class="feed-card-title">${escapeHtml(track.title || 'Unknown')}</div>
        <div class="feed-card-sub">${escapeHtml(track.artist || '')}</div>
    `;
    card.addEventListener('click', () => {
        if (window.pywebview?.api) {
            const trackObj = { ...track };
            if (trackObj.track_id) trackObj.id = trackObj.track_id;
            if (trackList && trackList.length > 0) {
                window.pywebview.api.play_track(trackObj, trackList, trackIndex);
            } else {
                window.pywebview.api.play_track(trackObj);
            }
        }
    });
    return card;
}

function setElText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

window.addEventListener('app:mood_playlists_ready', (e) => {
    const data = e.detail;
    renderFeedSection('home-mood', data);
});

window.addEventListener('app:artists_ready', (e) => {
    clearFeedTimeout('home-artists');
    renderArtists(e.detail);
});

window.addEventListener('app:refresh_home', () => {
    loadHome(false);
});

export function renderTopTracks(tracks) {
    const container = document.getElementById('home-top-tracks');
    if (!container) return;
    container.innerHTML = '';
    
    if (!tracks || tracks.length === 0) {
        container.innerHTML = '<div class="empty-state text-sm" style="padding:18px 24px; color:rgba(255,255,255,0.85); font-weight:600; background:rgba(255,255,255,0.04); border-radius:12px; border:1px dashed rgba(255,255,255,0.15); width:100%;">🎵 Слушайте любимую музыку, чтобы сформировать личный Топ!</div>';
        return;
    }

    tracks.forEach((track, i) => {
        const cover = getCoverUrl(track);
        const card = document.createElement('div');
        card.className = 'feed-card';
        card.innerHTML = `
            <div class="feed-card-cover">
                ${coverImgHtml({ src: cover, coverUrl: track.cover_url || '', sourceId: track.source_id || '', source: track.source || '' })}
                <div class="feed-card-overlay">
                    <button class="feed-card-play"><i data-lucide="play" style="width:14px;height:14px;fill:currentColor"></i></button>
                </div>
            </div>
            <div class="feed-card-title">${escapeHtml(track.title || 'Unknown Title')}</div>
            <div class="feed-card-sub">${escapeHtml(track.artist || 'Unknown')} (${track.plays || 0})</div>
        `;
        card.onclick = () => {
            if (window.pywebview?.api) window.pywebview.api.play_track(track, tracks, i);
        };
        container.appendChild(card);
    });
    renderIcons();
}

export function renderTopArtists(artists) {
    const container = document.getElementById('home-top-artists');
    if (!container) return;
    container.innerHTML = '';
    
    if (!artists || artists.length === 0) {
        container.innerHTML = '<div class="empty-state text-sm" style="padding:16px;color:var(--text-sec)">Пока нет данных</div>';
        return;
    }

    artists.forEach(artist => {
        const card = document.createElement('div');
        card.className = 'feed-card artist-card';
        card.innerHTML = `
            <div class="feed-card-cover" style="border-radius: 50%; overflow: hidden; background: linear-gradient(135deg, var(--accent), var(--bg-surface)); display: flex; align-items: center; justify-content: center;">
                <i data-lucide="user" style="width:48px;height:48px;color:rgba(255,255,255,0.5)"></i>
            </div>
            <div class="feed-card-title" style="text-align: center;">${escapeHtml(artist.artist || 'Unknown')}</div>
            <div class="feed-card-sub" style="text-align: center;">${artist.plays || 0} раз</div>
        `;
        card.onclick = () => {
            window.appConfig = window.appConfig || {};
            window.appConfig.searchQuery = artist.artist;
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            const searchNav = document.querySelector('[data-page="search"]');
            if (searchNav) searchNav.classList.add('active');
            if (window.NeDotify && window.NeDotify.showPage) {
                window.NeDotify.showPage('search');
            } else {
                const searchTab = document.getElementById('tab-search');
                if (searchTab) searchTab.click();
            }
        };
        container.appendChild(card);
    });
    renderIcons();
}

let currentWrappedPeriod = 'week';

export async function loadWrappedStats(period = 'week') {
    currentWrappedPeriod = period;
    await window.awaitBridge();
    if (!window.pywebview?.api || !window.pywebview.api.get_wrapped_stats) return;

    try {
        const stats = await window.pywebview.api.get_wrapped_stats(period);
        renderWrappedUI(stats);
    } catch (e) {
        console.error("Error loading wrapped stats:", e);
    }
}

function renderWrappedUI(stats) {
    if (!stats) return;
    const badge = document.getElementById('wrapped-total-time-badge');
    if (badge) badge.textContent = `${stats.total_minutes || 0} мин (${stats.total_plays || 0} треков)`;

    // Render Canvas Activity Chart
    renderActivityChart(stats.daily_activity || []);

    // Render Top 5
    const list = document.getElementById('wrapped-top-list');
    if (!list) return;

    if (!stats.top_tracks || stats.top_tracks.length === 0) {
        list.innerHTML = '<div class="empty-state text-sm" style="padding:12px; opacity:0.6;">Нет слушательских данных за этот период</div>';
        return;
    }

    list.innerHTML = '';
    stats.top_tracks.forEach((track, i) => {
        const row = document.createElement('div');
        row.style.cssText = 'display:flex; justify-content:space-between; align-items:center; padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.05);';
        row.innerHTML = `
            <div style="display:flex; align-items:center; gap:8px; overflow:hidden;">
                <span style="font-weight:700; color:var(--primary); width:14px; text-align:center;">${i+1}</span>
                <div style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                    <span style="color:#fff; font-weight:600;">${escapeHtml(track.title || 'Unknown')}</span>
                    <span style="color:var(--text-sec); font-size:11px; margin-left:4px;">• ${escapeHtml(track.artist || 'Unknown')}</span>
                </div>
            </div>
            <span style="color:var(--primary); font-size:11px; font-weight:600; white-space:nowrap;">${track.plays} прослушиваний</span>
        `;
        list.appendChild(row);
    });
}

function renderActivityChart(activity) {
    const canvas = document.getElementById('wrapped-activity-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width = canvas.parentElement.clientWidth || 300;
    const h = canvas.height = 140;

    ctx.clearRect(0, 0, w, h);

    if (!activity || activity.length === 0) return;

    const maxVal = Math.max(...activity.map(a => a.minutes), 10);
    const barWidth = Math.max(12, Math.floor((w - 40) / activity.length));
    const spacing = 6;

    activity.forEach((item, i) => {
        const barH = Math.max(4, Math.floor((item.minutes / maxVal) * (h - 35)));
        const x = 20 + i * (barWidth + spacing);
        const y = h - 25 - barH;

        // Gradient bar
        const grad = ctx.createLinearGradient(0, y, 0, h - 25);
        grad.addColorStop(0, '#1DB954');
        grad.addColorStop(1, 'rgba(29, 185, 84, 0.15)');

        ctx.fillStyle = grad;
        ctx.beginPath();
        if (ctx.roundRect) {
            ctx.roundRect(x, y, barWidth, barH, 4);
        } else {
            ctx.rect(x, y, barWidth, barH);
        }
        ctx.fill();

        // Day Label
        ctx.fillStyle = 'rgba(255,255,255,0.6)';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(item.day, x + barWidth / 2, h - 8);
    });
}

// Bind period buttons
document.addEventListener('DOMContentLoaded', () => {
    const periodContainer = document.getElementById('wrapped-period-btns');
    if (periodContainer) {
        periodContainer.querySelectorAll('.wrapped-period-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                periodContainer.querySelectorAll('.wrapped-period-btn').forEach(b => {
                    b.classList.remove('active');
                    b.style.background = 'transparent';
                    b.style.color = 'var(--text-sec)';
                });
                btn.classList.add('active');
                btn.style.background = 'var(--primary)';
                btn.style.color = '#fff';
                const period = btn.dataset.period || 'week';
                loadWrappedStats(period);
            });
        });
    }
});



