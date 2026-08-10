// NeDotify — Particles Module (GPU-Optimized)
let canvas = null;
let ctx = null;
let animFrameId = null;
let lastFrameTime = 0;
let isParticlesRunning = false;

let particles = [];
let mouse = { x: -1000, y: -1000, active: false };

let particleShape = 'dot';
let particleSpeed = 1.2;
let particleCount = 12;

// Throttle FPS for smooth performance
let targetFps = 24;
let frameInterval = 1000 / targetFps;

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
    } else if (isParticlesRunning && !animFrameId) {
        lastFrameTime = 0;
        animFrameId = requestAnimationFrame(animate);
    }
});

const WHITE_PARTICLE = '#ffffff';

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

    if (animFrameId) {
        cancelAnimationFrame(animFrameId);
        animFrameId = null;
    }

    container.innerHTML = '';
    container.style.display = 'block';

    canvas = document.createElement('canvas');
    canvas.id = 'particles-canvas';
    canvas.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none !important;will-change:transform;transform:translateZ(0);';

    container.appendChild(canvas);
    ctx = canvas.getContext('2d', { alpha: true, desynchronized: true });

    const resize = () => {
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
    resize();
    window.removeEventListener('resize', resize);
    window.addEventListener('resize', resize);
    window.addEventListener('nedotify:mini_player_toggled', () => {
        setTimeout(resize, 100);
    });

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

    // Read settings
    const countSlider = document.getElementById('slider-particles-count');
    particleCount = countSlider ? Math.min(parseInt(countSlider.value) || 30, 80) : 30;

    const speedSlider = document.getElementById('slider-particles-speed');
    particleSpeed = speedSlider ? parseInt(speedSlider.value) || 2 : 2;

    const sizeSlider = document.getElementById('slider-particles-size');
    const sizeVal = sizeSlider ? parseInt(sizeSlider.value) || 2 : 2;
    const sizeScaleMap = { 1: 0.6, 2: 1.0, 3: 1.6, 4: 2.4, 5: 3.2 };
    const sizeScale = sizeScaleMap[sizeVal] || 1.0;

    const activeShape = document.querySelector('.particle-shape-btn.active');
    if (activeShape) particleShape = activeShape.dataset.shape || 'dot';

    const baseSpeed = particleSpeed === 1 ? 0.3 : (particleSpeed === 3 ? 1.2 : 0.7);

    particles = [];
    for (let i = 0; i < particleCount; i++) {
        particles.push(createParticle(baseSpeed));
    }

    function createParticle(speed) {
        const radius = (Math.random() * 2.5 + 2.0) * sizeScale;
        const fontPx = particleShape === 'coat_rf' || particleShape === 'eagle_rf'
            ? Math.max(9, radius * 2.2)
            : Math.max(10, radius * 3.6);
        const fontStr = (particleShape === 'coat_rf' || particleShape === 'eagle_rf')
            ? `${fontPx}px "Segoe UI Emoji", sans-serif`
            : `${fontPx}px "Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji", sans-serif`;

        let symbol = '';
        if (particleShape === 'heart') symbol = '❤️';
        else if (particleShape === 'star') symbol = '⭐';
        else if (particleShape === 'snow') symbol = '❄️';
        else if (particleShape === 'note') symbol = '🎵';
        else if (particleShape === 'sparkle') symbol = '✨';
        else if (particleShape === 'coat_rf' || particleShape === 'eagle_rf') symbol = '🦅';

        return {
            x: Math.random() * (canvas.width || window.innerWidth || 800),
            y: Math.random() * (canvas.height || window.innerHeight || 600),
            vx: (Math.random() - 0.5) * 0.4,
            vy: Math.random() * speed + 0.3,
            radius: radius,
            opacity: Math.random() * 0.35 + 0.55,
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
            ctx.beginPath();
            ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
            ctx.fillStyle = WHITE_PARTICLE;
            ctx.fill();
        } else if (p.shape === 'flag_rf') {
            // Draw real 3-stripe Russian tricolor flag
            const w = Math.max(14, p.radius * 3.6);
            const h = Math.max(9, w * 0.65);
            const x = p.x - w / 2;
            const y = p.y - h / 2;
            const stripeH = h / 3;

            // White
            ctx.fillStyle = '#ffffff';
            ctx.fillRect(x, y, w, stripeH);

            // Blue
            ctx.fillStyle = '#0039a6';
            ctx.fillRect(x, y + stripeH, w, stripeH);

            // Red
            ctx.fillStyle = '#d52b1e';
            ctx.fillRect(x, y + stripeH * 2, w, stripeH);

            // Border
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.4)';
            ctx.lineWidth = 0.8;
            ctx.strokeRect(x, y, w, h);
        } else if (p.shape === 'coat_rf' || p.shape === 'eagle_rf') {
            // Draw Coat of Arms of Russia (Golden shield with red backing)
            const w = Math.max(12, p.radius * 3.0);
            const h = Math.max(14, w * 1.2);
            const x = p.x - w / 2;
            const y = p.y - h / 2;

            ctx.beginPath();
            ctx.moveTo(x, y);
            ctx.lineTo(x + w, y);
            ctx.lineTo(x + w, y + h * 0.68);
            ctx.quadraticCurveTo(x + w / 2, y + h, x, y + h * 0.68);
            ctx.closePath();
            ctx.fillStyle = '#b30000';
            ctx.fill();
            ctx.strokeStyle = '#ffd700';
            ctx.lineWidth = 1.2;
            ctx.stroke();

            ctx.font = p.fontStr;
            ctx.fillStyle = '#ffd700';
            ctx.fillText(p.symbol, p.x, p.y);
        } else {
            if (p.symbol) {
                ctx.font = p.fontStr;
                ctx.fillStyle = WHITE_PARTICLE;
                ctx.fillText(p.symbol, p.x, p.y);
            } else {
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
                ctx.fillStyle = WHITE_PARTICLE;
                ctx.fill();
            }
        }
    }

    const pushRadius = 60;
    const pushRadiusSq = pushRadius * pushRadius;

    isParticlesRunning = true;
    lastFrameTime = 0;

    function animate(timestamp) {
        if (!isParticlesRunning || document.hidden) {
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

        for (let i = 0; i < particles.length; i++) {
            const p = particles[i];

            if (mouse.active) {
                const dx = p.x - mouse.x;
                const dy = p.y - mouse.y;
                const distSq = dx * dx + dy * dy;

                if (distSq < pushRadiusSq && distSq > 0) {
                    const dist = Math.sqrt(distSq);
                    const force = (pushRadius - dist) / pushRadius;
                    const pushFactor = 0.6;
                    p.pushVx += (dx / dist) * force * pushFactor;
                    p.pushVy += (dy / dist) * force * pushFactor;
                }
            }

            p.x += p.vx + p.pushVx;
            p.y += p.vy + p.pushVy;

            p.pushVx *= 0.82;
            p.pushVy *= 0.82;

            if (Math.abs(p.pushVx) < 0.001) p.pushVx = 0;
            if (Math.abs(p.pushVy) < 0.001) p.pushVy = 0;

            if (p.y > (canvas.height || window.innerHeight) + 20) {
                p.y = -20;
                p.x = Math.random() * (canvas.width || window.innerWidth);
            }
            if (p.x < -20) p.x = (canvas.width || window.innerWidth) + 20;
            if (p.x > (canvas.width || window.innerWidth) + 20) p.x = -20;

            drawParticle(p);
        }

        ctx.globalAlpha = 1;
    }

    animate(performance.now());
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
        const currSettings = window.settings || {};
        if (currSettings.ui?.particles_enabled !== false) {
            lastFrameTime = performance.now();
            if (!animFrameId) animFrameId = requestAnimationFrame(animate);
        }
    }
    
    if (state.active && !state.disable_visualizations) {
        // Throttle FPS if not fully paused
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
