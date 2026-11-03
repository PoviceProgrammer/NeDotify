import { getCoverUrl, renderPlaylistCoverCollage, extractDominantColor, showToast } from './utils.js';

let favoriteRequest = null;
let favoriteCache = null;
let favoriteGeneration = 0;
let initialized = false;
let observer;
let timer;
let collageTracks = [];
let collageGeneration = 0;
let collageSignature = '';

function syncCollageVisibility() {
    const visible = enabled('decorations_enabled') &&
        document.getElementById('view-home')?.classList.contains('active') &&
        Boolean(document.getElementById('home-cover-collage')?.childElementCount);
    document.documentElement.classList.toggle('has-home-collage', Boolean(visible));
}

// Reuse history artwork, including local-cover proxy URLs. No canvas/CORS read,
// polling, colour extraction or continuously moving full-window blur is needed.
export async function updateHomeCoverCollage(tracks = collageTracks) {
    collageTracks = Array.isArray(tracks) ? tracks.slice(0, 20) : [];
    const urls = [...new Set(collageTracks.map(getCoverUrl).filter(Boolean))].slice(0, 6);
    const signature = JSON.stringify(urls);
    syncCollageVisibility();
    if (signature === collageSignature) return;
    collageSignature = signature;
    const generation = ++collageGeneration;
    const app = document.getElementById('app-container');
    if (!app) { collageSignature = ''; return; }
    let host = document.getElementById('home-cover-collage');
    if (!host) {
        host = document.createElement('div');
        host.id = 'home-cover-collage';
        host.setAttribute('aria-hidden', 'true');
        host.inert = true;
        app.prepend(host);
    }
    if (!urls.length) { host.replaceChildren(); syncCollageVisibility(); return; }
    const images = await Promise.all(urls.map(src => new Promise(resolve => {
        const image = new Image();
        image.alt = ''; image.decoding = 'async';
        const timeout = setTimeout(() => finish(null), 6000);
        function finish(result) {
            clearTimeout(timeout); image.onload = image.onerror = null; resolve(result);
        }
        image.onload = () => finish(image);
        image.onerror = () => finish(null);
        image.src = src;
    })));
    if (generation !== collageGeneration) return;
    const loaded = images.filter(Boolean);
    if (!loaded.length) { collageSignature = ''; return; }
    const layer = document.createElement('div');
    layer.className = 'home-cover-collage-frame';
    // Fill the entire composition even when only one or two covers are available.
    for (let i = 0; i < 6; i++) layer.append(loaded[i % loaded.length].cloneNode());
    while (host.children.length > 1) host.firstElementChild.remove();
    const previous = host.lastElementChild;
    host.append(layer);
    layer.animate?.([{opacity: 0}, {opacity: 1}], {duration: 900, easing: 'ease-out'});
    if (previous) setTimeout(() => previous.remove(), 950);
    syncCollageVisibility();
}
const colors = new Map();
const colorRequests = new Map();
function wallpaperEnabled() {
    return enabled('decorations_enabled') && enabled('resource_bg', 'optimization');
}

export async function refreshFavoritesCovers(providedTracks = null) {
    if (Array.isArray(providedTracks)) favoriteCache = providedTracks.slice(0,4);
    const targets = document.querySelectorAll('.qa-favorites .qa-cover, .lib-collection-cover.is-favorites, #lib-card-favorites .lib-card-icon, #lib-hero-cover[data-collection-type="favorites"]');
    if (!targets.length || !window.pywebview?.api?.get_favorites) return;
    const generation = favoriteGeneration;
    favoriteRequest ||= Promise.resolve().then(() => favoriteCache || window.pywebview.api.get_favorites(4)).finally(() => { favoriteRequest = null; });
    let tracks;
    try { tracks = await favoriteRequest; } catch { return; }
    if (generation !== favoriteGeneration || !Array.isArray(tracks)) return;
    favoriteCache = tracks.slice(0,4);
    const covers = favoriteCache.map(getCoverUrl).filter(Boolean);
    const markup = renderPlaylistCoverCollage(covers.map(src => ({src})));
    targets.forEach(target => {
        if (!target.isConnected) return;
        target.innerHTML = markup || '<span aria-hidden="true">♥</span>';
        target.classList.toggle('has-collage', Boolean(markup));
    });
}

function enabled(key, category = 'theme') {
    if (window.settings?.[category]?.[key] !== undefined) return window.settings[category][key] !== false;
    try { return JSON.parse(localStorage.getItem(`nedotify_${category}_${key}`)) !== false; } catch { return true; }
}

function sync() {
    syncCollageVisibility();
    const decorations = enabled('decorations_enabled');
    document.documentElement.dataset.decorations = String(decorations);
    for (const [id,key] of [['background-decoration-enabled','decorations_enabled']]) {
        const input = document.getElementById(id);
        if (input) input.checked = enabled(key);
    }
    const automatic = document.getElementById('home-dynamic-background');
    if (automatic) { automatic.checked = !wallpaperEnabled(); automatic.disabled = true; }
    const home = document.getElementById('view-home');
    let layer = document.getElementById('home-color-atmosphere');
    if (wallpaperEnabled()) {
        layer?.remove();
        observer?.disconnect();
        clearTimeout(timer);
        return;
    }
    if (!layer && home) {
        layer = document.createElement('div');
        layer.id = 'home-color-atmosphere';
        layer.setAttribute('aria-hidden','true');
        layer.innerHTML = '<span></span><span></span><span></span>';
        home.prepend(layer);
    }
    if (home && !observer) observer = new MutationObserver(schedule);
    if (home) observer?.observe(home, {childList:true,subtree:true,attributes:true,attributeFilter:['src']});
    schedule();
}

function schedule() { clearTimeout(timer); timer = setTimeout(sample, 250); }
function sample() {
    const home = document.getElementById('view-home');
    const layer = document.getElementById('home-color-atmosphere');
    if (!layer || document.hidden || !home?.classList.contains('active')) return;
    const bounds = home.getBoundingClientRect();
    const images = [...home.querySelectorAll('img')].filter(img => {
        if (img.id === 'home-avatar-img' || img.closest('#home-top-artists')) return false;
        const rect = img.getBoundingClientRect();
        return img.complete && img.naturalWidth && rect.width > 0 && rect.bottom > bounds.top && rect.top < bounds.bottom && rect.right > bounds.left && rect.left < bounds.right;
    });
    const unique = [...new Map(images.map(img => [img.currentSrc || img.src, img])).values()].slice(0, 3);
    [...layer.children].forEach((orb,index) => {
        const img = unique[index % unique.length];
        const src = img?.currentSrc || img?.src;
        const color = src ? coverColor(src, img) : null;
        orb.style.backgroundColor = color ? `rgb(${color.r},${color.g},${color.b})` : 'transparent';
        // Covers without CORS permission retain their colors as a blurred image.
        orb.style.backgroundImage = src && !color ? `url(${JSON.stringify(src)})` : 'none';
    });
}

function coverColor(src, original) {
    if (colors.has(src)) return colors.get(src);
    if (colorRequests.has(src)) return null;
    const sameOrigin = new URL(src, location.href).origin === location.origin || src.startsWith('data:');
    if (sameOrigin) {
        const color = extractDominantColor(original);
        if (color) colors.set(src, color);
        if (colors.size > 80) colors.delete(colors.keys().next().value);
        return color;
    }
    const image = new Image();
    image.crossOrigin = 'anonymous';
    colorRequests.set(src, image);
    const timeout = setTimeout(() => finish(false), 8000);
    const finish = loaded => {
        clearTimeout(timeout);
        colors.set(src, loaded ? extractDominantColor(image) : null);
        if (colors.size > 80) colors.delete(colors.keys().next().value);
        colorRequests.delete(src);
        image.onload = image.onerror = null;
        schedule();
    };
    image.onload = () => finish(true);
    image.onerror = () => finish(false);
    image.src = src;
    return null;
}

export function initHomeAtmosphere() {
    if (!initialized) {
        initialized = true;
        document.addEventListener('change', async event => {
            const key = {'background-decoration-enabled':'decorations_enabled'}[event.target.id];
            if (!key) return;
            const input = event.target;
            const previous = enabled(key);
            input.disabled = true;
            try {
                const result = await window.pywebview.api.save_setting(key,input.checked,'theme');
                if (result === false || result?.success === false) throw new Error('Rejected');
                window.settings ||= {}; window.settings.theme ||= {};
                window.settings.theme[key] = input.checked;
                localStorage.setItem(`nedotify_theme_${key}`,JSON.stringify(input.checked));
            } catch { input.checked = previous; showToast('Не удалось сохранить фон','error'); }
            finally { input.disabled = false; sync(); window.dispatchEvent(new Event('nedotify:background_decoration_changed')); }
        });
        document.addEventListener('nedotify:settings_applied',sync);
        window.addEventListener('nedotify:appearance_changed',sync);
        window.addEventListener('nedotify:background_decoration_changed',sync);
        window.addEventListener('nedotify:page_changed',schedule);
        window.addEventListener('nedotify:page_changed',syncCollageVisibility);
        document.addEventListener('visibilitychange',schedule);
        window.addEventListener('nedotify:favorites_updated',()=>{ favoriteGeneration++; favoriteRequest = null; favoriteCache = null; refreshFavoritesCovers(); });
        document.addEventListener('load',schedule,true);
        document.addEventListener('scroll',schedule,{passive:true,capture:true});
        window.addEventListener('resize',schedule,{passive:true});
    }
    sync();
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',initHomeAtmosphere,{once:true});
else initHomeAtmosphere();
