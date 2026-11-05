// NeDotify — Audio-Reactive Visualizer (GPU-Optimized)
import { getIsPlaying, getVolume, getCurrentTrack, getAudioFrequencyData } from './player.js';
import { sizeCanvasForDpr, registerCanvasDprListener } from './utils.js';
import { saveSetting } from './settings.js';

let animFrameId = null;
let bars = [];
const BAR_COUNT = 48;
const SMOOTHING = 0.18;
let visualizerStyle = 'bars';
let isEnabled = true;
let beatInterval = 0.45;
let currentVolumeSampled = 70;
const freqData = new Uint8Array(64);
const drawData = new Float64Array(BAR_COUNT);
const gradientCache = new WeakMap();
let initialized = false;
let efficiencyPaused = false;
let efficiencyFps = null;
let resizeHandler = null;
let visibilityObserver = null;
let cachedTitle = null;
let cachedSeed = 0;

// FPS throttle
let lastFrameTime = 0;
let targetFps = 24;
let frameInterval = 1000 / targetFps;
let hasDrawnIdle = false;

export function setVisualizerFps(fps) {
    targetFps = Math.max(5, Math.min(60, parseInt(fps) || 24));
    frameInterval = 1000 / Math.min(targetFps, efficiencyFps || targetFps);
}

// Single source of truth for #toggle-visualizer (settings.js must NOT bind it).
// options.silent skips persistence (used when restoring backend state).
export function setVisualizerEnabled(enabled, options = {}) {
    isEnabled = !!enabled;
    const toggle = document.getElementById('toggle-visualizer');
    if (toggle) toggle.classList.toggle('on', isEnabled);
    document.querySelector('#opt-active-resources [data-resource="visualizers"]')?.classList.toggle('active', isEnabled);
    const canvas = document.getElementById('visualizer-canvas');
    if (canvas) canvas.style.display = isEnabled ? '' : 'none';
    if (!isEnabled) {
        if (animFrameId) {
            cancelAnimationFrame(animFrameId);
            animFrameId = null;
        }
        targets.forEach(t => {
            if (t.ctx && t.canvas) t.ctx.clearRect(0, 0, t.canvas.width, t.canvas.height);
        });
    }
    syncVisualizerAnimation();
    if (!options.silent) persistVisualizerEnabled();
}

function persistVisualizerEnabled() {
    return saveSetting('cover_visualizer', isEnabled, 'ui');
}

export function isVisualizerEnabled() { return isEnabled; }

// Cached gradient colors
let cachedPrimaryRgb = '255, 159, 28';
let gradientCacheTime = 0;
const GRADIENT_CACHE_DURATION = 5000;

// cssW/cssH are the drawable size in CSS pixels; canvas.width/height are the
// device-pixel backing store (cssW * devicePixelRatio). Every draw*() below
// works in CSS pixels through the context's dpr scale, so no geometry, colour,
// gradient or line width changes - only the resolution bookkeeping.
const targets = [
    { id: 'visualizer-canvas', canvas: null, ctx: null, primary: true, cssW: 0, cssH: 0 },
    { id: 'home-visualizer-canvas', canvas: null, ctx: null, primary: false, cssW: 0, cssH: 0 }
];

let unsubscribeDpr = null;

function isWindowHidden() {
    return document.hidden || document.documentElement.classList.contains('window-hidden');
}

let documentVisible = !isWindowHidden();
const onVisibilityChanged = () => {
    documentVisible = !isWindowHidden();
    syncVisualizerAnimation();
};
document.addEventListener('visibilitychange', onVisibilityChanged);
document.addEventListener('nedotify:window_visibility_changed', onVisibilityChanged);

export function notifyPlaybackState(playing) {
    if (playing) {
        hasDrawnIdle = false;
        startDrawLoop();
    }
}

document.addEventListener('nedotify:state_changed', (e) => {
    notifyPlaybackState(e.detail === 'playing');
});

window.addEventListener('nedotify:page_changed', startDrawLoop);

export function initVisualizer() {
    if (initialized) {
        startDrawLoop();
        return;
    }
    initialized = true;
    targets.forEach(t => {
        t.canvas = document.getElementById(t.id);
        t.inViewport = true;
        t.parentPage = t.canvas?.closest('.view-page') || null;
        if (t.canvas) t.ctx = t.canvas.getContext('2d', { alpha: true, desynchronized: true });
    });

    if ('IntersectionObserver' in window) {
        visibilityObserver = new IntersectionObserver(entries => {
            entries.forEach(entry => {
                const target = targets.find(item => item.canvas === entry.target);
                if (target) target.inViewport = entry.isIntersecting;
            });
            startDrawLoop();
        });
        targets.forEach(target => {
            if (target.canvas) visibilityObserver.observe(target.canvas);
        });
    }

    const resizeCanvas = () => {
        targets.forEach(t => {
            if (t.canvas && t.canvas.parentElement) {
                const sized = sizeCanvasForDpr(
                    t.canvas, t.ctx,
                    t.canvas.parentElement.offsetWidth || 380,
                    t.canvas.parentElement.offsetHeight || 380
                );
                t.cssW = sized.cssW;
                t.cssH = sized.cssH;
                gradientCache.delete(t.ctx);
            }
        });
        startDrawLoop();
    };
    resizeCanvas();
    resizeHandler = resizeCanvas;
    window.addEventListener('resize', resizeCanvas);
    // Dragging the window between a 100% and a 150% monitor changes
    // devicePixelRatio without firing resize, so re-run the same bookkeeping.
    if (unsubscribeDpr) unsubscribeDpr();
    unsubscribeDpr = registerCanvasDprListener(resizeCanvas);

    bars = [];
    for (let i = 0; i < BAR_COUNT; i++) {
        bars.push({
            current: 0,
            target: 0,
            velocity: 0,
            phase: Math.random() * Math.PI * 2,
            freq: 0.5 + Math.random() * 2,
        });
    }

    const styleSelect = document.getElementById('select-visualizer-style');
    if (styleSelect && !styleSelect._boundVisualizerStyle) {
        styleSelect._boundVisualizerStyle = true;
        styleSelect.addEventListener('change', (e) => {
            visualizerStyle = e.target.value;
            saveSetting('visualizer_style', visualizerStyle, 'audio');
        });
    }

    const toggleEnabled = document.getElementById('toggle-visualizer');
    if (toggleEnabled && !toggleEnabled._boundVisualizerClick) {
        toggleEnabled._boundVisualizerClick = true;
        // Initial state: DOM toggle class wins if present, else stored setting.
        try {
            const stored = localStorage.getItem('nedotify_ui_cover_visualizer');
            const fromStore = stored !== null ? JSON.parse(stored) : null;
            const fromDom = toggleEnabled.classList.contains('on');
            const initial = window.settings?.ui?.cover_visualizer ?? fromStore ?? (fromDom || isEnabled);
            setVisualizerEnabled(initial, { silent: true });
        } catch(e) {}
        toggleEnabled.addEventListener('click', () => {
            setVisualizerEnabled(!isEnabled);
        });
    }

    // Volume is dynamically fetched from player module (getVolume()) to avoid pywebview RPC polling

    syncVisualizerStyle(window.settings);

    startDrawLoop();
}

function syncVisualizerStyle(settings) {
    const style = settings?.audio?.visualizer_style;
    if (!style) return;
    const select = document.getElementById('select-visualizer-style');
    if (select && [...select.options].some(option => option.value === style)) {
        visualizerStyle = style;
        select.value = style;
    }
}
document.addEventListener('nedotify:settings_applied', event => syncVisualizerStyle(event.detail));

function startDrawLoop() {
    if (initialized && !animFrameId && isEnabled && documentVisible && !efficiencyPaused) {
        hasDrawnIdle = false;
        animFrameId = requestAnimationFrame(draw);
    }
}

function syncVisualizerAnimation() {
    if (!isEnabled || !documentVisible || efficiencyPaused || !initialized) {
        if (animFrameId) cancelAnimationFrame(animFrameId);
        animFrameId = null;
        return;
    }
    startDrawLoop();
}

function getCachedPrimaryRgb() {
    const now = performance.now();
    if (now - gradientCacheTime > GRADIENT_CACHE_DURATION) {
        const val = window.getComputedStyle(document.documentElement)
            .getPropertyValue('--primary-rgb').trim();
        if (val) cachedPrimaryRgb = val;
        gradientCacheTime = now;
    }
    return cachedPrimaryRgb;
}

function updateSimulation(playing, now, volScale, track) {
    const title = track?.title || '';
    if (title !== cachedTitle) {
        cachedTitle = title;
        cachedSeed = 0;
        for (let i = 0; i < title.length; i++) {
            cachedSeed = (cachedSeed + title.charCodeAt(i)) % 100000;
        }
    }
    const effectiveVol = volScale;

    const freqAdjust = 0.5 + (cachedSeed % 50) / 25.0;
    const beatPhase = (now % beatInterval) / beatInterval;
    const isBeat = beatPhase < 0.12;

    let hasRealData = false;
    if (playing) {
        hasRealData = getAudioFrequencyData(freqData);
    }

    for (let i = 0; i < BAR_COUNT; i++) {
        const bar = bars[i];
        if (playing) {
            let target = 0;
            if (hasRealData) {
                const freqIdx = Math.floor(i * 64 / BAR_COUNT);
                const val = freqData[freqIdx] || 0;
                target = (val / 255.0) * Math.max(0.3, volScale);
            } else {
                const speedScale = 0.6 + effectiveVol * 1.4;
                const bassBump = Math.sin(now * 2.5 * freqAdjust * speedScale + bar.phase) * 0.35 * effectiveVol;
                const midFreq  = Math.sin(now * bar.freq * 3.2 * freqAdjust * speedScale + bar.phase) * 0.28 * effectiveVol;
                const highFreq = Math.sin(now * bar.freq * 7.5 * freqAdjust * speedScale + i * 0.5) * 0.18 * effectiveVol;
                const noise    = (Math.random() - 0.5) * 0.08 * effectiveVol;

                const bassWeight = Math.max(0, 1 - (i / BAR_COUNT) * 1.5);
                const highWeight = Math.max(0, (i / BAR_COUNT) * 1.5 - 0.5);

                target = (0.08 + 0.25 * effectiveVol)
                    + bassBump * bassWeight * 1.6
                    + midFreq
                    + highFreq * highWeight * 1.5
                    + noise;

                if (isBeat && i < BAR_COUNT * 0.25) {
                    target = Math.min(1, target + 0.45 * effectiveVol * (1 - beatPhase / 0.12));
                }
                if (isBeat && i >= BAR_COUNT * 0.25 && i < BAR_COUNT * 0.55) {
                    target = Math.min(1, target + 0.2 * effectiveVol * (1 - beatPhase / 0.12));
                }
            }
            bar.target = Math.max(0.04, Math.min(1, target));
        } else {
            bar.target = 0.05 + Math.sin(now * 0.4 + bar.phase) * 0.035;
        }

        const diff = bar.target - bar.current;
        bar.velocity += diff * (playing ? SMOOTHING : 0.04);
        bar.velocity *= 0.78;
        bar.current += bar.velocity;
        bar.current = Math.max(0, Math.min(1, bar.current));
    }

    if (isBeat && beatPhase < 0.02) {
        beatInterval = 0.35 + Math.random() * 0.25;
    }
}

function draw(timestamp) {
    if (!initialized || !isEnabled || !documentVisible || efficiencyPaused) {
        animFrameId = null;
        return;
    }

    const playing = getIsPlaying();

    let hasVisibleCanvas = false;
    targets.forEach(t => {
        if (t.canvas && t.inViewport && t.canvas.offsetParent !== null && t.canvas.width > 0 && t.canvas.height > 0) {
            const parentPage = t.parentPage;
            if (!parentPage || parentPage.classList.contains('active')) {
                hasVisibleCanvas = true;
            }
        }
    });

    if (!hasVisibleCanvas) {
        animFrameId = null;
        return;
    }

    if (!playing) {
        if (hasDrawnIdle) { animFrameId = null; return; }
        hasDrawnIdle = true;
        animFrameId = null;
    } else {
        hasDrawnIdle = false;
        animFrameId = requestAnimationFrame(draw);
    }

    const elapsed = timestamp - lastFrameTime;
    if (elapsed < frameInterval) return;
    lastFrameTime = timestamp - (elapsed % frameInterval);

    const now = performance.now() / 1000;
    const volScale = getVolume() / 100;
    const track = getCurrentTrack();

    updateSimulation(playing, now, volScale, track);

    const rgb = getCachedPrimaryRgb();
    for (let i = 0; i < BAR_COUNT; i++) {
        drawData[i] = playing ? bars[i].current * volScale : bars[i].current;
    }

    targets.forEach(target => {
        if (!target.ctx || !target.canvas) return;
        if (target.canvas.width === 0 || target.canvas.height === 0) return;
        if (!target.inViewport || target.canvas.offsetParent === null) return;

        // Optimization for laptops: skip drawing if parent view page is not active
        const parentPage = target.parentPage;
        if (parentPage && !parentPage.classList.contains('active')) return;

        const ctx = target.ctx;
        // Draw in CSS pixels. The `|| canvas.width` fallback only kicks in for a
        // canvas that never got a parentElement at init, where the old code
        // used the backing store directly - identical at devicePixelRatio 1.
        const w = target.cssW || target.canvas.width;
        const h = target.cssH || target.canvas.height;
        ctx.clearRect(0, 0, w, h);

        if (visualizerStyle === 'wave') {
            drawWave(ctx, w, h, drawData, playing, target.primary, rgb);
        } else if (visualizerStyle === 'circle') {
            drawCircle(ctx, w, h, drawData, playing, target.primary, rgb);
        } else {
            drawBars(ctx, w, h, drawData, playing, target.primary, rgb);
        }
    });
}

function makeGradient(ctx, x1, y1, x2, y2, playing, primary, rgb) {
    const alpha = playing ? (primary ? 0.7 : 0.55) : 0.34;
    const cached = gradientCache.get(ctx);
    if (cached && cached.x1 === x1 && cached.y1 === y1 && cached.x2 === x2 && cached.y2 === y2 && cached.alpha === alpha && cached.rgb === rgb) {
        return cached.gradient;
    }
    const grad = ctx.createLinearGradient(x1, y1, x2, y2);
    grad.addColorStop(0, `rgba(${rgb}, ${alpha * 0.3})`);
    grad.addColorStop(0.5, `rgba(${rgb}, ${alpha * 0.6})`);
    grad.addColorStop(1, `rgba(${rgb}, ${alpha})`);
    gradientCache.set(ctx, { x1, y1, x2, y2, alpha, rgb, gradient: grad });
    return grad;
}

function drawBars(ctx, w, h, data, playing, primary, rgb) {
    const barWidth = w / BAR_COUNT;
    const maxHeight = h * 0.85;
    const grad = makeGradient(ctx, 0, h, 0, 0, playing, primary, rgb);
    ctx.fillStyle = grad;

    for (let i = 0; i < BAR_COUNT; i++) {
        const barHeight = data[i] * maxHeight;
        const x = i * barWidth;
        const y = h - barHeight;
        ctx.fillRect(x + 1, y, barWidth - 2, barHeight);
    }
}

function drawWave(ctx, w, h, data, playing, primary, rgb) {
    const maxHeight = h * 0.5;
    const midY = h / 2;
    const step = w / (BAR_COUNT - 1);

    ctx.beginPath();
    ctx.moveTo(0, midY);

    for (let i = 0; i < BAR_COUNT; i++) {
        const x = i * step;
        const y = midY - (data[i] * maxHeight);

        if (i === 0) {
            ctx.lineTo(x, y);
        } else {
            const prevX = (i - 1) * step;
            const prevY = midY - (data[i - 1] * maxHeight);
            const cpX = (prevX + x) / 2;
            ctx.quadraticCurveTo(prevX, prevY, cpX, (prevY + y) / 2);
        }
    }

    ctx.lineTo(w, midY);

    for (let i = BAR_COUNT - 1; i >= 0; i--) {
        const x = i * step;
        const y = midY + (data[i] * maxHeight);
        if (i === BAR_COUNT - 1) {
            ctx.lineTo(x, y);
        } else {
            const nextX = (i + 1) * step;
            const nextY = midY + (data[i + 1] * maxHeight);
            const cpX = (nextX + x) / 2;
            ctx.quadraticCurveTo(nextX, nextY, cpX, (nextY + y) / 2);
        }
    }

    ctx.lineTo(0, midY + (data[0] * maxHeight));
    ctx.lineTo(0, midY);
    ctx.closePath();
    ctx.fillStyle = makeGradient(ctx, 0, 0, 0, h, playing, primary, rgb);
    ctx.fill();
}

function drawCircle(ctx, w, h, data, playing, primary, rgb) {
    const centerX = w / 2;
    const centerY = h / 2;
    const maxRadius = Math.min(w, h) / 2 * 0.9;
    const baseRadius = maxRadius * 0.3;

    ctx.beginPath();
    for (let i = 0; i <= BAR_COUNT; i++) {
        const idx = i % BAR_COUNT;
        const val = data[idx];
        const radius = baseRadius + (val * (maxRadius - baseRadius));
        const angle = (i / BAR_COUNT) * Math.PI * 2 - Math.PI / 2;
        const x = centerX + Math.cos(angle) * radius;
        const y = centerY + Math.sin(angle) * radius;

        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    }

    ctx.closePath();
    ctx.fillStyle = makeGradient(ctx, 0, 0, w, h, playing, primary, rgb);
    ctx.fill();
}

export function destroyVisualizer() {
    initialized = false;
    if (animFrameId) {
        cancelAnimationFrame(animFrameId);
        animFrameId = null;
    }
    if (resizeHandler) window.removeEventListener('resize', resizeHandler);
    resizeHandler = null;
    if (unsubscribeDpr) unsubscribeDpr();
    unsubscribeDpr = null;
    if (visibilityObserver) visibilityObserver.disconnect();
    visibilityObserver = null;
    targets.forEach(target => {
        if (target.ctx) gradientCache.delete(target.ctx);
        target.canvas = null;
        target.ctx = null;
        target.parentPage = null;
    });
    bars = [];
}






window.addEventListener('nedotify:efficiency_state', (e) => {
    const state = e.detail;
    efficiencyPaused = !!(state.active && state.disable_visualizations);
    efficiencyFps = state.active && !state.disable_visualizations ? (state.fps_limit || 15) : null;
    frameInterval = 1000 / Math.min(targetFps, efficiencyFps || targetFps);
    syncVisualizerAnimation();
});
