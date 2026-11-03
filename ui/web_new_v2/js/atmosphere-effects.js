// Effect components own bounded pools and cached sprites. One manager owns
// rendering, time, quality, visibility and the existing audio connection.
const TAU = Math.PI * 2;
function sprite(document, width, height, paint) {
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (ctx) paint(ctx, width, height);
    return canvas;
}
class FallingEffect {
    constructor(kind, random) {
        this.kind = kind;
        this.random = random;
        this.items = [];
        this.sprite = null;
    }
    configure({ document, width, height, count, color }) {
        const rain = this.kind === 'rain';
        this.sprite = sprite(document, rain ? 12 : 48, rain ? 100 : 48, (ctx, w, h) => {
            const gradient = rain
                ? ctx.createLinearGradient(0, 0, w, h)
                : ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2);
            if (rain) {
                gradient.addColorStop(0, `rgba(${color},0)`);
                gradient.addColorStop(0.8, `rgba(${color},.46)`);
                gradient.addColorStop(1, `rgba(${color},.9)`);
            } else {
                gradient.addColorStop(0, `rgba(${color},.88)`);
                gradient.addColorStop(0.3, `rgba(${color},.35)`);
                gradient.addColorStop(1, `rgba(${color},0)`);
            }
            ctx.fillStyle = gradient;
            if (rain) {
                ctx.beginPath();
                ctx.moveTo(w * 0.42, 0);
                ctx.lineTo(w * 0.65, h * 0.85);
                ctx.quadraticCurveTo(w * 0.5, h, w * 0.35, h * 0.85);
                ctx.closePath();
                ctx.fill();
            } else ctx.fillRect(0, 0, w, h);
        });
        while (this.items.length > count) this.items.pop();
        while (this.items.length < count)
            this.items.push({
                x: this.random() * width,
                y: this.random() * height,
                depth: this.random(),
                phase: this.random() * TAU,
                speed: 0.6 + this.random() * 0.8,
            });
    }
    render(ctx, frame, settings) {
        const rain = this.kind === 'rain';
        const { width, height, dt, time, signal, intensity, reduced } = frame;
        const reacting = settings.reactive ? signal : frame.silent;
        const direction = Math.tan((settings.direction * Math.PI) / 180);
        const visibleCount = Math.round(this.items.length * intensity);
        const depthRange = Math.max(0.2, Math.min(1.4, settings.depth / 3));
        for (let index = 0; index < visibleCount; index++) {
            const item = this.items[index],
                depth = 0.25 + item.depth * depthRange;
            const velocity =
                (rain ? 400 : 38) *
                settings.speed *
                item.speed *
                depth *
                (reduced ? 0.25 : 1) *
                (1 + reacting.mid * 0.18);
            item.y += dt * velocity;
            item.x +=
                dt * velocity * direction +
                (rain
                    ? reacting.low * Math.sin(time * 0.003 + item.phase) * 0.15
                    : Math.sin(time * 0.0006 + item.phase) * dt * 12 * (1 + reacting.mid));
            if (item.y > height + 60) {
                item.y = -60;
                item.x = this.random() * width;
            }
            if (item.x > width + 70) item.x = -70;
            else if (item.x < -70) item.x = width + 70;
            const size = settings.size * (rain ? 1.3 : 4.5) * depth;
            ctx.globalAlpha = Math.min(
                0.7,
                settings.opacity * (0.25 + depth * 0.48) * (1 + reacting.low * 0.2 + reacting.high * 0.1),
            );
            const length = rain ? (17 + 20 * depth) * settings.size : size * 2.5;
            ctx.drawImage(this.sprite, item.x, item.y, rain ? Math.max(1.2, size * 2.5) : length, length);
            if ((settings.highlights ?? true) && depth > 0.95 && reacting.high > 0.08 && index % 11 === 0) {
                ctx.globalAlpha = Math.min(0.2, reacting.high * 0.16);
                ctx.drawImage(
                    this.sprite,
                    item.x - size,
                    item.y + length * 0.7,
                    size * 4,
                    Math.max(size * 2, 2),
                );
            }
        }
        ctx.globalAlpha = 1;
    }
    release() {
        if (this.sprite) {
            this.sprite.width = 0;
            this.sprite.height = 0;
        }
        this.sprite = null;
        this.items.length = 0;
    }
}
export class RainEffect extends FallingEffect {
    constructor(random) {
        super('rain', random);
    }
}
export class SnowEffect extends FallingEffect {
    constructor(random) {
        super('snow', random);
    }
}
export class FogEffect {
    constructor(random) {
        this.random = random;
        this.layers = [];
        this.sprite = null;
    }
    configure({ document, count, color }) {
        this.sprite = sprite(document, 256, 128, (ctx, w, h) => {
            const gradient = ctx.createRadialGradient(w * 0.5, h * 0.5, 0, w * 0.5, h * 0.5, Math.min(w, h) * 0.5);
            gradient.addColorStop(0, `rgba(${color},.5)`);
            gradient.addColorStop(0.4, `rgba(${color},.25)`);
            gradient.addColorStop(1, `rgba(${color},0)`);
            ctx.fillStyle = gradient;
            ctx.fillRect(0, 0, w, h);
        });
        this.layers = Array.from({ length: count }, (_, index) => ({
            phase: this.random() * TAU,
            y: 0.25 + (index / Math.max(1, count)) * 0.7,
            size: 0.85 + this.random() * 0.6,
        }));
    }
    render(ctx, frame, settings) {
        const signal = settings.reactive ? frame.signal : frame.silent,
            drift = frame.reduced ? 0.2 : 1;
        for (const layer of this.layers) {
            const phase = frame.time * 0.000025 * settings.speed * drift + layer.phase,
                width = frame.width * layer.size,
                height = frame.height * (0.3 + settings.density * 0.3);
            const x = (Math.sin(phase) * 0.2 + 0.4) * frame.width - width * 0.5,
                y =
                    (layer.y + Math.sin(phase * 1.7) * 0.05 * (1 + signal.mid * 0.2)) * frame.height -
                    height * 0.5;
            ctx.globalAlpha = Math.min(
                0.35,
                settings.opacity *
                    settings.density *
                    frame.intensity *
                    (1 + signal.low * 0.2 + signal.energy * 0.15),
            );
            ctx.drawImage(this.sprite, x, y, width, height);
        }
        ctx.globalAlpha = 1;
    }
    release() {
        if (this.sprite) {
            this.sprite.width = 0;
            this.sprite.height = 0;
        }
        this.sprite = null;
        this.layers.length = 0;
    }
}
export class StormEffect {
    constructor(random) {
        this.random = random;
        this.nextFlash = 0;
        this.flashAt = -Infinity;
        this.origin = 0.5;
        this.sprite = null;
    }
    configure({ document, color }) {
        this.sprite = sprite(document, 512, 256, (ctx, w, h) => {
            const gradient = ctx.createRadialGradient(w / 2, h * 0.1, 0, w / 2, h * 0.1, h * 0.85);
            gradient.addColorStop(0, `rgba(${color},.8)`);
            gradient.addColorStop(0.35, `rgba(${color},.25)`);
            gradient.addColorStop(1, `rgba(${color},0)`);
            ctx.fillStyle = gradient;
            ctx.fillRect(0, 0, w, h);
        });
    }
    render(ctx, frame, settings) {
        // Local reflected light, not full-screen white flashes or beat strobes.
        if (!settings.flashes || frame.reduced) return false;
        if (!this.nextFlash)
            this.nextFlash =
                frame.time + Math.max(8000, settings.interval * 1000) * (0.8 + this.random() * 0.6);
        let triggered = false;
        if (frame.time >= this.nextFlash) {
            this.flashAt = frame.time;
            this.origin = 0.15 + this.random() * 0.7;
            triggered = true;
            this.nextFlash =
                frame.time + Math.max(8000, settings.interval * 1000) * (0.8 + this.random() * 0.7);
        }
        const age = frame.time - this.flashAt;
        if (age < 1100) {
            const envelope = Math.exp(-age / 230) * Math.min(1, age / 55);
            ctx.globalAlpha = Math.min(0.2, settings.brightness * 0.7) * envelope * frame.intensity;
            ctx.drawImage(
                this.sprite,
                frame.width * (this.origin - 0.4),
                -frame.height * 0.12,
                frame.width * 0.8,
                frame.height * 0.7,
            );
            ctx.globalAlpha = 1;
        }
        return triggered;
    }
    release() {
        if (this.sprite) {
            this.sprite.width = 0;
            this.sprite.height = 0;
        }
        this.sprite = null;
        this.nextFlash = 0;
        this.flashAt = -Infinity;
    }
}
