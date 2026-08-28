// NeDotify — Audio-Reactive Visualizer (GPU-Optimized)
import { getIsPlaying, getVolume, getCurrentTrack, getAudioFrequencyData } from './player.js';

let animFrameId = null;
let bars = [];
const BAR_COUNT = 48;
const SMOOTHING = 0.18;
let visualizerStyle = 'bars';
let isEnabled = true;
let beatInterval = 0.45;
let currentVolumeSampled = 70;
const freqData = new Uint8Array(64);

// FPS throttle
let lastFrameTime = 0;
let targetFps = 24;
let frameInterval = 1000 / targetFps;
let hasDrawnIdle = false;

export function setVisualizerFps(fps) {
    targetFps = Math.max(5, Math.min(60, parseInt(fps) || 24));
    frameInterval = 1000 / targetFps;
}

// Cached gradient colors
let cachedPrimaryRgb = '255, 159, 28';
let gradientCacheTime = 0;
const GRADIENT_CACHE_DURATION = 5000;

const targets = [
    { id: 'visualizer-canvas', canvas: null, ctx: null, primary: true },
    { id: 'home-visualizer-canvas', canvas: null, ctx: null, primary: false }
];

let documentVisible = !document.hidden;
document.addEventListener('visibilitychange', () => {
    documentVisible = !document.hidden;
    if (documentVisible && isEnabled && !animFrameId) {
        hasDrawnIdle = false;
        animFrameId = requestAnimationFrame(draw);
    }
});

export function notifyPlaybackState(playing) {
    if (playing) {
        hasDrawnIdle = false;
        if (isEnabled && documentVisible && !animFrameId) {
            animFrameId = requestAnimationFrame(draw);
        }
    }
}

document.addEventListener('nedotify:state_changed', (e) => {
    notifyPlaybackState(e.detail === 'playing');
});

window.addEventListener('nedotify:page_changed', () => {
    if (isEnabled && documentVisible && !animFrameId) {
        hasDrawnIdle = false;
        animFrameId = requestAnimationFrame(draw);
    }
});

export function initVisualizer() {
    targets.forEach(t => {
        t.canvas = document.getElementById(t.id);
        if (t.canvas) t.ctx = t.canvas.getContext('2d', { alpha: true, desynchronized: true });
    });

    const resizeCanvas = () => {
        targets.forEach(t => {
            if (t.canvas && t.canvas.parentElement) {
                t.canvas.width = t.canvas.parentElement.offsetWidth || 380;
                t.canvas.height = t.canvas.parentElement.offsetHeight || 380;
            }
        });
    };
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

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
    if (styleSelect) {
        styleSelect.addEventListener('change', (e) => {
            visualizerStyle = e.target.value;
            if (window.pywebview?.api) {
                window.pywebview.api.save_setting('visualizer_style', visualizerStyle, 'audio');
            }
        });
    }

    const toggleEnabled = document.getElementById('toggle-visualizer');
    if (toggleEnabled) {
        toggleEnabled.addEventListener('click', () => {
            isEnabled = !isEnabled;
            toggleEnabled.classList.toggle('on', isEnabled);
            if (!isEnabled) {
                if (animFrameId) {
                    cancelAnimationFrame(animFrameId);
                    animFrameId = null;
                }
                targets.forEach(t => {
                    if (t.ctx && t.canvas) t.ctx.clearRect(0, 0, t.canvas.width, t.canvas.height);
                });
            } else {
                draw(0);
            }
        });
    }

    // Volume is dynamically fetched from player module (getVolume()) to avoid pywebview RPC polling

    setTimeout(async () => {
        if (window.pywebview?.api) {
            const settings = await window.pywebview.api.get_settings();
            if (settings?.audio?.visualizer_style) {
                visualizerStyle = settings.audio.visualizer_style;
                if (styleSelect) styleSelect.value = visualizerStyle;
            }
        }
    }, 1000);

    startDrawLoop();
}

function startDrawLoop() {
    if (!animFrameId && isEnabled && documentVisible) {
        hasDrawnIdle = false;
        animFrameId = requestAnimationFrame(draw);
    }
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
    let seed = 0;
    for (let i = 0; i < title.length; i++) {
        seed = (seed + title.charCodeAt(i)) % 100000;
    }
    const effectiveVol = volScale;

    const freqAdjust = 0.5 + (seed % 50) / 25.0;
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
            bar.target = 0.015 + Math.sin(now * 0.4 + bar.phase) * 0.012;
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
    if (!isEnabled || !documentVisible) {
        animFrameId = null;
        return;
    }

    const playing = getIsPlaying();

    let hasVisibleCanvas = false;
    targets.forEach(t => {
        if (t.canvas && t.canvas.offsetParent !== null && t.canvas.width > 0 && t.canvas.height > 0) {
            const parentPage = t.canvas.closest('.view-page');
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
        if (hasDrawnIdle) {
            animFrameId = null;
            return;
        }
        hasDrawnIdle = true;
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

    targets.forEach(target => {
        if (!target.ctx || !target.canvas) return;
        if (target.canvas.width === 0 || target.canvas.height === 0) return;
        if (target.canvas.offsetParent === null) return;

        // Optimization for laptops: skip drawing if parent view page is not active
        const parentPage = target.canvas.closest('.view-page');
        if (parentPage && !parentPage.classList.contains('active')) return;

        const ctx = target.ctx;
        const w = target.canvas.width;
        const h = target.canvas.height;
        ctx.clearRect(0, 0, w, h);

        const data = new Array(BAR_COUNT);
        for (let i = 0; i < BAR_COUNT; i++) {
            data[i] = playing ? bars[i].current * volScale : bars[i].current;
        }

        if (visualizerStyle === 'wave') {
            drawWave(ctx, w, h, data, playing, target.primary, rgb);
        } else if (visualizerStyle === 'circle') {
            drawCircle(ctx, w, h, data, playing, target.primary, rgb);
        } else {
            drawBars(ctx, w, h, data, playing, target.primary, rgb);
        }
    });
}

function makeGradient(ctx, x1, y1, x2, y2, playing, primary, rgb) {
    const grad = ctx.createLinearGradient(x1, y1, x2, y2);
    const alpha = playing ? (primary ? 0.7 : 0.4) : 0.15;
    grad.addColorStop(0, `rgba(${rgb}, ${alpha * 0.3})`);
    grad.addColorStop(0.5, `rgba(${rgb}, ${alpha * 0.6})`);
    grad.addColorStop(1, `rgba(${rgb}, ${alpha})`);
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
    if (animFrameId) {
        cancelAnimationFrame(animFrameId);
        animFrameId = null;
    }
}






window.addEventListener('nedotify:efficiency_state', (e) => {
    const state = e.detail;
    if (state.active && state.disable_visualizations) {
        // Paused by efficiency manager
        if (animFrameId) {
            cancelAnimationFrame(animFrameId);
            animFrameId = null;
        }
    } else {
        // Resumed
        if (isEnabled && documentVisible && !animFrameId) {
            lastFrameTime = performance.now();
            animFrameId = requestAnimationFrame(draw);
        }
    }
    
    if (state.active && !state.disable_visualizations) {
        // Throttle FPS if not fully paused
        frameInterval = 1000 / (state.fps_limit || 15);
    } else {
        // Restore standard FPS
        frameInterval = 1000 / targetFps;
    }
});
