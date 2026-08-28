// NeDotify — Particles Module (GPU-Optimized)
let canvas = null;
let ctx = null;
let animFrameId = null;
let lastFrameTime = 0;
let isParticlesRunning = false;
let animateFn = null;

let particles = [];
let mouse = { x: -1000, y: -1000, active: false };

let particleShape = 'dot';
let particleSpeed = 2;
let particleCount = 30;

// Throttle FPS for smooth performance
let targetFps = 24;
let frameInterval = 1000 / targetFps;

// Performance guardrails
const prefersReducedMotion = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const isLowEndDevice = () => (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 4);

export function setParticlesFps(fps) {
    targetFps = Math.max(5, Math.min(30, parseInt(fps) || 24));
    frameInterval = 1000 / targetFps;
}

// Pause when hidden
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        if (animFrameId) {
            cancelAnimationFrame(animFrameId);
            animFrameId = null;
        }
    } else if (isParticlesRunning && !animFrameId && animateFn) {
        lastFrameTime = 0;
        animFrameId = requestAnimationFrame(animateFn);
    }
});

const WHITE_PARTICLE = '#ffffff';

// O-7: pre-rendered emoji sprites (offscreen canvas, once per size/symbol)
const emojiSpriteCache = new Map();
function getEmojiSprite(symbol, fontStr) {
    const key = symbol + '|' + fontStr;
    let sprite = emojiSpriteCache.get(key);
    if (!sprite) {
        const size = Math.ceil(parseFloat(fontStr) * 1.5) + 6;
        const cv = document.createElement('canvas');
        cv.width = size;
        cv.height = size;
        const c = cv.getContext('2d');
        c.font = fontStr;
        c.textAlign = 'center';
        c.textBaseline = 'middle';
        c.fillStyle = WHITE_PARTICLE;
        c.shadowColor = 'rgba(255, 255, 255, 0.4)';
        c.shadowBlur = 3;
        c.fillText(symbol, size / 2, size / 2);
        sprite = { canvas: cv, size };
        emojiSpriteCache.set(key, sprite);
    }
    return sprite;
}

// Cached Coat of Arms (Герб РФ) sprite generator for high-performance rendering
const emblemSpriteCache = new Map();
function getCoatRfSprite(w, h) {
    const key = `${Math.round(w)}x${Math.round(h)}`;
    let sprite = emblemSpriteCache.get(key);
    if (!sprite) {
        const cv = document.createElement('canvas');
        cv.width = Math.ceil(w + 6);
        cv.height = Math.ceil(h + 6);
        const c = cv.getContext('2d');
        const cx = cv.width / 2;
        const cy = cv.height / 2;
        const x = cx - w / 2;
        const y = cy - h / 2;

        // Red heraldic shield
        c.beginPath();
        c.moveTo(x, y);
        c.lineTo(x + w, y);
        c.lineTo(x + w, y + h * 0.68);
        c.quadraticCurveTo(cx, y + h, x, y + h * 0.68);
        c.closePath();
        c.fillStyle = '#b30000';
        c.shadowColor = 'rgba(255, 215, 0, 0.4)';
        c.shadowBlur = 4;
        c.fill();
        c.shadowBlur = 0;

        // Golden border
        c.strokeStyle = '#ffd700';
        c.lineWidth = Math.max(1.0, w * 0.08);
        c.stroke();

        // Golden double-headed eagle emblem
        const eagleFontPx = Math.max(9, Math.round(w * 0.58));
        c.font = `${eagleFontPx}px "Segoe UI Emoji", "Apple Color Emoji", sans-serif`;
        c.fillStyle = '#ffd700';
        c.textAlign = 'center';
        c.textBaseline = 'middle';
        c.fillText('🦅', cx, cy - 1);

        sprite = { canvas: cv, sizeW: cv.width, sizeH: cv.height };
        emblemSpriteCache.set(key, sprite);
    }
    return sprite;
}

// Cached Russian Tricolor (Флаг РФ) sprite generator
const flagSpriteCache = new Map();
function getFlagRfSprite(w, h) {
    const key = `${Math.round(w)}x${Math.round(h)}`;
    let sprite = flagSpriteCache.get(key);
    if (!sprite) {
        const cv = document.createElement('canvas');
        cv.width = Math.ceil(w + 4);
        cv.height = Math.ceil(h + 4);
        const c = cv.getContext('2d');
        const x = 2;
        const y = 2;
        const stripeH = h / 3;

        // White
        c.fillStyle = '#ffffff';
        c.fillRect(x, y, w, stripeH);

        // Blue
        c.fillStyle = '#0039a6';
        c.fillRect(x, y + stripeH, w, stripeH);

        // Red
        c.fillStyle = '#d52b1e';
        c.fillRect(x, y + stripeH * 2, w, stripeH);

        // Fine border
        c.strokeStyle = 'rgba(255, 255, 255, 0.4)';
        c.lineWidth = 0.8;
        c.strokeRect(x, y, w, h);

        sprite = { canvas: cv, sizeW: cv.width, sizeH: cv.height };
        flagSpriteCache.set(key, sprite);
    }
    return sprite;
}

// Cached Soft Bokeh Blurred Dot sprite generator
const dotSpriteCache = new Map();
function getBlurredDotSprite(radius) {
    const rKey = Math.max(1, Math.round(radius * 2) / 2);
    let sprite = dotSpriteCache.get(rKey);
    if (!sprite) {
        const spriteRadius = Math.max(8, rKey * 2.8);
        const cv = document.createElement('canvas');
        const d = Math.ceil(spriteRadius * 2);
        cv.width = d;
        cv.height = d;
        const c = cv.getContext('2d');
        const cx = d / 2;
        const cy = d / 2;

        const grad = c.createRadialGradient(cx, cy, 0, cx, cy, spriteRadius);
        grad.addColorStop(0, 'rgba(255, 255, 255, 0.95)');
        grad.addColorStop(0.2, 'rgba(255, 255, 255, 0.7)');
        grad.addColorStop(0.45, 'rgba(255, 255, 255, 0.35)');
        grad.addColorStop(0.75, 'rgba(255, 255, 255, 0.1)');
        grad.addColorStop(1, 'rgba(255, 255, 255, 0)');

        c.fillStyle = grad;
        c.beginPath();
        c.arc(cx, cy, spriteRadius, 0, Math.PI * 2);
        c.fill();

        sprite = { canvas: cv, size: d, offset: cx };
        dotSpriteCache.set(rKey, sprite);
    }
    return sprite;
}

export function stopParticles() {
    isParticlesRunning = false;
    if (animFrameId) {
        cancelAnimationFrame(animFrameId);
        animFrameId = null;
    }
    const container = document.getElementById('particles-bg');
    if (container) {
        container.style.display = 'none';
        container.innerHTML = '';
    }
    canvas = null;
    ctx = null;
}

export function initParticles() {
    // Respect accessibility settings
    if (prefersReducedMotion()) {
        stopParticles();
        return;
    }

    // Clean up any running instance first to prevent leaks
    if (animFrameId) {
        cancelAnimationFrame(animFrameId);
        animFrameId = null;
    }

    const toggle = document.getElementById('toggle-particles');
    if (toggle) {
        if (!toggle.classList.contains('on')) {
            stopParticles();
            return;
        }
    } else {
        const currSettings = window.settings || {};
        if (currSettings.ui && currSettings.ui.particles_enabled === false) {
            stopParticles();
            return;
        }
    }

    const container = document.getElementById('particles-bg');
    if (!container) return;

    container.innerHTML = '';
    container.style.display = 'block';

    canvas = document.createElement('canvas');
    canvas.id = 'particles-canvas';
    canvas.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none !important;display:block;';

    container.appendChild(canvas);
    ctx = canvas.getContext('2d', { alpha: true, desynchronized: true });

    // Debounced resize with coordinate rescaling
    const performResize = () => {
        if (!canvas) return;
        const oldW = canvas.width || window.innerWidth;
        const oldH = canvas.height || window.innerHeight;
        const newW = window.innerWidth;
        const newH = window.innerHeight;

        canvas.width = newW;
        canvas.height = newH;

        if (oldW > 0 && oldH > 0 && (oldW !== newW || oldH !== newH) && particles.length > 0) {
            const scaleX = newW / oldW;
            const scaleY = newH / oldH;
            particles.forEach(p => {
                p.x = p.x * scaleX;
                p.y = p.y * scaleY;
            });
        }
    };

    performResize();

    let resizeTimeout = null;
    const onResize = () => {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(performResize, 100);
    };

    window.removeEventListener('resize', onResize);
    window.addEventListener('resize', onResize);

    const onMiniPlayerToggled = () => {
        if (document.body.classList.contains('mini-player-active')) {
            if (animFrameId) {
                cancelAnimationFrame(animFrameId);
                animFrameId = null;
            }
        } else if (isParticlesRunning && !animFrameId && animateFn) {
            lastFrameTime = 0;
            animFrameId = requestAnimationFrame(animateFn);
        }
        setTimeout(performResize, 100);
    };
    window.removeEventListener('nedotify:mini_player_toggled', onMiniPlayerToggled);
    window.addEventListener('nedotify:mini_player_toggled', onMiniPlayerToggled);

    let mouseThrottleId = null;
    const onMouseMove = (e) => {
        if (!mouseThrottleId) {
            mouseThrottleId = setTimeout(() => {
                mouse.x = e.clientX;
                mouse.y = e.clientY;
                mouse.active = true;
                mouseThrottleId = null;
            }, 32);
        }
    };
    const onMouseLeave = () => {
        mouse.active = false;
    };

    window.removeEventListener('mousemove', onMouseMove);
    window.addEventListener('mousemove', onMouseMove, { passive: true });
    window.removeEventListener('mouseleave', onMouseLeave);
    window.addEventListener('mouseleave', onMouseLeave);

    // Read settings with robust fallbacks
    const countSlider = document.getElementById('slider-particles-count');
    const rawCount = countSlider ? parseInt(countSlider.value) : (window.settings?.ui?.particles_count || 30);
    particleCount = isLowEndDevice() ? Math.min(rawCount, 25) : Math.min(rawCount, 80);

    const speedSlider = document.getElementById('slider-particles-speed');
    particleSpeed = speedSlider ? parseInt(speedSlider.value) || 2 : (window.settings?.ui?.particles_speed || 2);

    const sizeSlider = document.getElementById('slider-particles-size');
    const sizeVal = sizeSlider ? parseInt(sizeSlider.value) || 2 : (window.settings?.ui?.particles_size || 2);
    const sizeScaleMap = { 1: 0.65, 2: 1.0, 3: 1.5, 4: 2.2, 5: 3.0 };
    const sizeScale = sizeScaleMap[sizeVal] || 1.0;

    // Resolve active shape
    const activeShape = document.querySelector('.particle-shape-btn.active');
    const savedShape = window.settings?.ui?.particles_shape;
    let localShape = null;
    try {
        const rawLocal = localStorage.getItem('nedotify_ui_particles_shape');
        if (rawLocal) localShape = JSON.parse(rawLocal);
    } catch(e) {}

    particleShape = (activeShape?.dataset?.shape) || savedShape || localShape || 'dot';

    const baseSpeed = particleSpeed === 1 ? 0.35 : (particleSpeed === 3 ? 1.3 : 0.75);

    particles = [];
    for (let i = 0; i < particleCount; i++) {
        particles.push(createParticle(baseSpeed));
    }

    function createParticle(speed) {
        const radius = (Math.random() * 2.5 + 2.2) * sizeScale;
        const fontPx = Math.max(12, Math.round(radius * 3.2));
        const fontStr = `${fontPx}px "Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji", sans-serif`;

        let symbol = '';
        if (particleShape === 'heart') symbol = '❤️';
        else if (particleShape === 'star') symbol = '⭐';
        else if (particleShape === 'snow') symbol = '❄️';
        else if (particleShape === 'note') symbol = '🎵';
        else if (particleShape === 'sparkle') symbol = '✨';

        return {
            x: Math.random() * (canvas.width || window.innerWidth || 800),
            y: Math.random() * (canvas.height || window.innerHeight || 600),
            vx: (Math.random() - 0.5) * 0.4,
            vy: Math.random() * speed + 0.35,
            radius: radius,
            opacity: Math.random() * 0.25 + 0.35,
            pushVx: 0,
            pushVy: 0,
            shape: particleShape,
            fontStr: fontStr,
            symbol: symbol
        };
    }

    function drawParticle(p) {
        ctx.globalAlpha = p.opacity;

        if (p.shape === 'dot') {
            const sprite = getBlurredDotSprite(p.radius);
            ctx.drawImage(sprite.canvas, p.x - sprite.offset, p.y - sprite.offset);
        } else if (p.shape === 'flag_rf') {
            const w = Math.max(18, p.radius * 3.8);
            const h = Math.max(12, w * 0.67);
            const sprite = getFlagRfSprite(w, h);
            ctx.drawImage(sprite.canvas, p.x - sprite.sizeW / 2, p.y - sprite.sizeH / 2);
        } else if (p.shape === 'coat_rf' || p.shape === 'eagle_rf') {
            const w = Math.max(18, p.radius * 3.6);
            const h = Math.max(22, w * 1.2);
            const sprite = getCoatRfSprite(w, h);
            ctx.drawImage(sprite.canvas, p.x - sprite.sizeW / 2, p.y - sprite.sizeH / 2);
        } else {
            if (p.symbol) {
                const sprite = getEmojiSprite(p.symbol, p.fontStr);
                ctx.drawImage(sprite.canvas, p.x - sprite.size / 2, p.y - sprite.size / 2);
            } else {
                const sprite = getBlurredDotSprite(p.radius);
                ctx.drawImage(sprite.canvas, p.x - sprite.offset, p.y - sprite.offset);
            }
        }
    }

    const pushRadius = 70;
    const pushRadiusSq = pushRadius * pushRadius;

    isParticlesRunning = true;
    lastFrameTime = 0;

    function animate(timestamp) {
        // Stop loop when paused, tab hidden, or mini-player active
        if (!isParticlesRunning || document.hidden || document.body.classList.contains('mini-player-active')) {
            animFrameId = null;
            return;
        }

        animFrameId = requestAnimationFrame(animate);

        // FPS throttle
        if (lastFrameTime > 0) {
            const elapsed = timestamp - lastFrameTime;
            if (elapsed < frameInterval) return;
            lastFrameTime = timestamp - (elapsed % frameInterval);
        } else {
            lastFrameTime = timestamp;
        }

        if (!ctx || !canvas) return;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.globalAlpha = 1;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';

        const screenW = canvas.width || window.innerWidth;
        const screenH = canvas.height || window.innerHeight;

        for (let i = 0; i < particles.length; i++) {
            const p = particles[i];

            if (mouse.active) {
                const dx = p.x - mouse.x;
                const dy = p.y - mouse.y;
                const distSq = dx * dx + dy * dy;

                if (distSq < pushRadiusSq && distSq > 0) {
                    const dist = Math.sqrt(distSq);
                    const force = (pushRadius - dist) / pushRadius;
                    const pushFactor = 0.65;
                    p.pushVx += (dx / dist) * force * pushFactor;
                    p.pushVy += (dy / dist) * force * pushFactor;
                }
            }

            p.x += p.vx + p.pushVx;
            p.y += p.vy + p.pushVy;

            p.pushVx *= 0.84;
            p.pushVy *= 0.84;

            if (Math.abs(p.pushVx) < 0.001) p.pushVx = 0;
            if (Math.abs(p.pushVy) < 0.001) p.pushVy = 0;

            if (p.y > screenH + 25) {
                p.y = -25;
                p.x = Math.random() * screenW;
            }
            if (p.x < -25) p.x = screenW + 25;
            if (p.x > screenW + 25) p.x = -25;

            drawParticle(p);
        }

        ctx.globalAlpha = 1;
    }

    animateFn = animate;
    animate(performance.now());
}

window.addEventListener('nedotify:efficiency_state', (e) => {
    const state = e.detail;
    if (state.active && state.disable_visualizations) {
        if (animFrameId) {
            cancelAnimationFrame(animFrameId);
            animFrameId = null;
        }
    } else {
        const currSettings = window.settings || {};
        if (currSettings.ui?.particles_enabled !== false) {
            lastFrameTime = performance.now();
            if (!animFrameId && animateFn) animFrameId = requestAnimationFrame(animateFn);
        }
    }

    if (state.active && !state.disable_visualizations) {
        frameInterval = 1000 / (state.fps_limit || 15);
    } else {
        frameInterval = 1000 / targetFps;
    }
});

window.addEventListener('nedotify:battery_saver_changed', (e) => {
    const isBattery = !!e.detail?.isBatteryMode;
    if (isBattery) {
        frameInterval = 1000 / 15;
    } else {
        frameInterval = 1000 / targetFps;
    }
});
