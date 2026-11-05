import { RainEffect, SnowEffect, FogEffect, StormEffect } from './atmosphere-effects.js';

export const ATMOSPHERE_DEFAULTS = Object.freeze({
    enabled: false,
    effects: { rain: true, thunderstorm: false, fog: false, snow: false },
    intensity: 0.5,
    quality: 'auto',
    reactive: true,
    sensitivity: 1,
    bass: 1,
    mid: 1,
    treble: 1,
    smoothing: 0.65,
    max_reaction: 0.65,
    rain: { speed: 1, size: 1, opacity: 0.5, depth: 3, direction: 12, highlights: true, reactive: true },
    snow: { speed: 1, size: 1, opacity: 0.55, depth: 3, direction: 0, density: 0.5, reactive: true },
    fog: { density: 0.35, speed: 0.5, opacity: 0.3, tint: 'theme', depth: 3, reactive: true },
    storm: { flashes: true, interval: 15, brightness: 0.18, thunder: false, volume: 0.15 },
});
const finite = (value, fallback, min, max) =>
    Number.isFinite(Number(value)) ? Math.max(min, Math.min(max, Number(value))) : fallback;
const boolean = (value, fallback) => (typeof value === 'boolean' ? value : fallback);
const SIGNAL_BANDS = ['low', 'mid', 'high', 'energy'];
export function normalizeAtmosphere(input = {}) {
    const source = input && typeof input === 'object' ? input : {},
        out = {};
    for (const key of ['enabled', 'reactive']) out[key] = boolean(source[key], ATMOSPHERE_DEFAULTS[key]);
    for (const key of ['intensity', 'smoothing', 'max_reaction'])
        out[key] = finite(source[key], ATMOSPHERE_DEFAULTS[key], 0, 1);
    for (const key of ['sensitivity', 'bass', 'mid', 'treble'])
        out[key] = finite(source[key], ATMOSPHERE_DEFAULTS[key], 0, 3);
    out.quality = ['auto', 'high', 'balanced', 'low'].includes(source.quality) ? source.quality : 'auto';
    out.effects = {};
    for (const key of Object.keys(ATMOSPHERE_DEFAULTS.effects))
        out.effects[key] = boolean(source.effects?.[key], ATMOSPHERE_DEFAULTS.effects[key]);
    for (const name of ['rain', 'snow', 'fog', 'storm']) {
        out[name] = {};
        for (const [key, fallback] of Object.entries(ATMOSPHERE_DEFAULTS[name])) {
            const value = source[name]?.[key];
            if (typeof fallback === 'boolean') out[name][key] = boolean(value, fallback);
            else if (key === 'tint')
                out[name][key] = typeof value === 'string' && /^#[\da-f]{6}$/i.test(value) ? value : 'theme';
            else {
                const limits =
                    key === 'direction'
                        ? [-45, 45]
                        : key === 'depth'
                          ? [1, 4]
                          : key === 'interval'
                            ? [8, 120]
                            : ['speed', 'size'].includes(key)
                              ? [name === 'fog' ? 0.1 : 0.2, 3]
                              : [0, 1];
                out[name][key] = finite(value, fallback, ...limits);
            }
        }
    }
    return out;
}

// Time-based attack/release, RMS bands and noise floor. The one reusable
// frequency buffer samples the existing player graph without creating nodes.
export class AtmosphereSignal {
    constructor() {
        this.bins = null;
        this.value = { low: 0, mid: 0, high: 0, energy: 0 };
        this.raw = { low: 0, mid: 0, high: 0, energy: 0 };
    }
    reset() {
        for (const key of SIGNAL_BANDS) this.value[key] = 0;
    }
    sample(audio, config, dt) {
        let low = 0,
            mid = 0,
            high = 0,
            energy = 0;
        if (config.reactive && audio?.playing && audio?.hasTrack) {
            const analyser = audio.analyser;
            if (analyser && analyser.frequencyBinCount > 0) {
                if (this.bins?.length !== analyser.frequencyBinCount)
                    this.bins = new Uint8Array(analyser.frequencyBinCount);
                analyser.getByteFrequencyData(this.bins);
                const binHz =
                    (audio.context?.sampleRate || 48000) / (analyser.fftSize || this.bins.length * 2);
                let ln = 0,
                    mn = 0,
                    hn = 0;
                for (let index = 1; index < this.bins.length; index++) {
                    const frequency = index * binHz;
                    if (frequency > 16000) break;
                    const magnitude = Math.max(0, (this.bins[index] / 255 - 0.06) / 0.94);
                    if (frequency < 250) {
                        low += magnitude * magnitude;
                        ln++;
                    } else if (frequency < 4000) {
                        mid += magnitude * magnitude;
                        mn++;
                    } else {
                        high += magnitude * magnitude;
                        hn++;
                    }
                }
                low = Math.sqrt(low / Math.max(1, ln));
                mid = Math.sqrt(mid / Math.max(1, mn));
                high = Math.sqrt(high / Math.max(1, hn));
                energy = (low + mid + high) / 3;
            } else if (audio.bands) {
                low = finite(audio.bands.low, 0, 0, 1);
                mid = finite(audio.bands.mid, 0, 0, 1);
                high = finite(audio.bands.high, 0, 0, 1);
                energy = finite(audio.bands.energy, (low + mid + high) / 3, 0, 1);
            }
        }
        this.raw.low = low * config.bass;
        this.raw.mid = mid * config.mid;
        this.raw.high = high * config.treble;
        this.raw.energy = energy;
        for (const key of SIGNAL_BANDS) {
            const target = Math.min(config.max_reaction, Math.max(0, this.raw[key] * config.sensitivity));
            const seconds =
                target > this.value[key] ? 0.035 + config.smoothing * 0.16 : 0.18 + config.smoothing * 0.65;
            this.value[key] +=
                (target - this.value[key]) * (1 - Math.exp(-Math.min(0.25, Math.max(0, dt)) / seconds));
            if (this.value[key] < 0.0001) this.value[key] = 0;
        }
        return this.value;
    }
}

export class AtmosphereEngine {
    constructor(options = {}) {
        this.window = options.window || globalThis.window;
        this.document = options.document || globalThis.document;
        this.raf = options.requestAnimationFrame || ((fn) => globalThis.requestAnimationFrame(fn));
        this.caf = options.cancelAnimationFrame || ((id) => globalThis.cancelAnimationFrame(id));
        this.now = options.now || (() => performance.now());
        this.random = options.random || Math.random;
        this.config = normalizeAtmosphere();
        this.signal = new AtmosphereSignal();
        this.silent = { low: 0, mid: 0, high: 0, energy: 0 };
        this.frame = {
            width: 0,
            height: 0,
            dt: 0,
            time: 0,
            signal: this.signal.value,
            silent: this.silent,
            intensity: 0.5,
            reduced: false,
        };
        this.effects = {
            rain: new RainEffect(this.random),
            snow: new SnowEffect(this.random),
            fog: new FogEffect(this.random),
            thunderstorm: new StormEffect(this.random),
        };
        this.provider = null;
        this.canvas = null;
        this.ctx = null;
        this.frameId = null;
        this.listeners = [];
        this.media = null;
        this.poolKey = null;
        this.active = false;
        this.lastTime = 0;
        this.simulationTime = 0;
        this.requestedFps = 30;
        this.efficiencyFps = 30;
        this.efficiencyPaused = false;
        this.battery = false;
        this.autoScale = 1;
        this.averageCost = 0;
        this.nextBudgetAt = 0;
        this.audioArmed = false;
        this.pendingThunderAt = 0;
        this.thunderBuffer = null;
        this.thunderContext = null;
        this.thunderNodes = new Set();
        this.draw = this.draw.bind(this);
        this.sync = this.sync.bind(this);
    }
    configure(input) {
        this.config = normalizeAtmosphere(input);
        this.active = this.config.enabled;
        if (
            !this.config.storm.thunder ||
            !this.config.effects.thunderstorm ||
            this.config.storm.volume <= 0
        ) {
            this.audioArmed = false;
            this.pendingThunderAt = 0;
            this.stopThunder();
        }
        if (!this.active) {
            this.audioArmed = false;
            this.release();
            return;
        }
        this.init();
    }
    setAudioProvider(provider) {
        this.provider = typeof provider === 'function' ? provider : null;
    }
    setFps(fps) {
        this.requestedFps = finite(fps, 30, 5, 60);
        this.rebuild();
    }
    hidden() {
        return (
            this.document.hidden ||
            this.document.documentElement.dataset?.decorations === 'false' ||
            this.document.documentElement.classList.contains('window-hidden') ||
            this.document.body.classList.contains('mini-player-active')
        );
    }
    reduced() {
        return !!this.media?.matches;
    }
    hasEffects() {
        return this.config.intensity > 0 && Object.values(this.config.effects).some(Boolean);
    }
    budget() {
        const preset = this.window.settings?.optimization?.performance_preset;
        let scale = this.config.quality === 'high' ? 1 : this.config.quality === 'low' ? 0.3 : 0.62;
        if (this.config.quality === 'auto')
            scale = ((this.window.navigator?.hardwareConcurrency || 8) <= 4 ? 0.45 : 0.72) * this.autoScale;
        if (preset === 'low') scale = Math.min(scale, 0.3);
        else if (preset === 'balanced') scale = Math.min(scale, 0.72);
        if (this.battery) scale = Math.min(scale, 0.25);
        if (this.reduced()) scale = Math.min(scale, 0.22);
        return scale;
    }
    fps() {
        return Math.min(
            this.requestedFps,
            this.config.quality === 'low' ? 15 : 30,
            this.efficiencyFps,
            this.battery ? 12 : 60,
            this.reduced() ? 10 : 60,
        );
    }
    listen(target, name, callback) {
        target?.addEventListener?.(name, callback);
        this.listeners.push(() => target?.removeEventListener?.(name, callback));
    }
    init() {
        if (!this.config.enabled || !this.hasEffects()) {
            this.release();
            return;
        }
        this.active = true;
        this.battery = this.document.documentElement.classList.contains('battery-saver-active');
        if (!this.canvas) {
            const host = this.document.getElementById('particles-bg');
            if (!host) return;
            this.canvas = this.document.createElement('canvas');
            this.canvas.id = 'atmosphere-canvas';
            this.canvas.setAttribute('aria-hidden', 'true');
            this.canvas.style.cssText =
                'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;';
            host.style.display = 'block';
            host.style.pointerEvents = 'none';
            host.appendChild(this.canvas);
            this.ctx = this.canvas.getContext('2d', { alpha: true, desynchronized: true });
            if (!this.ctx) {
                this.release();
                return;
            }
            this.media = this.window.matchMedia?.('(prefers-reduced-motion: reduce)');
            this.listen(this.document, 'visibilitychange', this.sync);
            this.listen(this.document, 'nedotify:window_visibility_changed', this.sync);
            this.listen(this.window, 'nedotify:mini_player_toggled', this.sync);
            this.listen(this.window, 'resize', () => {
                this.rebuild();
                this.sync();
            });
            this.listen(this.window, 'nedotify:background_decoration_changed', this.sync);
            this.listen(this.window, 'nedotify:appearance_changed', () => {
                this.rebuild();
                this.sync();
            });
            this.listen(this.window, 'nedotify:performance_preset_changed', () => {
                this.rebuild();
                this.sync();
            });
            this.listen(this.window, 'nedotify:efficiency_state', (event) => {
                this.efficiencyPaused = !!(event.detail?.active && event.detail?.disable_visualizations);
                this.efficiencyFps = event.detail?.active ? finite(event.detail.fps_limit, 15, 5, 60) : 30;
                this.rebuild();
                this.sync();
            });
            this.listen(this.window, 'nedotify:battery_saver_changed', (event) => {
                this.battery = !!event.detail?.isBatteryMode;
                this.rebuild();
                this.sync();
            });
            this.listen(this.media, 'change', () => {
                this.rebuild();
                this.sync();
            });
            this.listen(this.window, 'pagehide', () => this.destroy());
        }
        this.rebuild();
        this.sync();
    }
    rebuild() {
        if (!this.canvas || !this.ctx) return;
        const width = Math.max(1, this.window.innerWidth || 1),
            height = Math.max(1, this.window.innerHeight || 1),
            scale = this.budget();
        const dpr = Math.min(this.window.devicePixelRatio || 1, scale < 0.5 ? 1 : 1.5),
            ratio = Math.min(dpr, Math.sqrt(3000000 / (width * height)));
        this.frame.width = width;
        this.frame.height = height;
        this.frame.reduced = this.reduced();
        const raw =
            this.window
                .getComputedStyle?.(this.document.documentElement)
                ?.getPropertyValue('--color-primary-rgb')
                ?.trim() || '170, 195, 220';
        const color = /^\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}$/.test(raw) ? raw : '170, 195, 220';
        const poolKey = JSON.stringify([
            width,
            height,
            ratio,
            scale,
            color,
            this.config.effects,
            this.config.snow.density,
            this.config.fog.depth,
            this.config.fog.tint,
        ]);
        if (poolKey === this.poolKey) return;
        this.poolKey = poolKey;
        this.canvas.width = Math.round(width * ratio);
        this.canvas.height = Math.round(height * ratio);
        this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        const falling = (this.config.effects.rain ? 1 : 0) + (this.config.effects.snow ? 1 : 0),
            total = Math.round(180 * scale * Math.min(1.2, Math.sqrt((width * height) / (1280 * 720))));
        for (const [name, effect] of Object.entries(this.effects)) {
            effect.release();
            if (!this.config.effects[name]) continue;
            const density = name === 'snow' ? this.config.snow.density : 1;
            let tint = color;
            if (name === 'fog' && this.config.fog.tint !== 'theme')
                tint = [1, 3, 5]
                    .map((index) => parseInt(this.config.fog.tint.slice(index, index + 2), 16))
                    .join(', ');
            effect.configure({
                document: this.document,
                width,
                height,
                color: tint,
                count:
                    name === 'fog'
                        ? Math.max(1, Math.round(this.config.fog.depth * scale))
                        : Math.max(1, Math.round((total / Math.max(1, falling)) * density)),
            });
        }
    }
    sync() {
        if (!this.active || !this.canvas || this.hidden() || this.efficiencyPaused || !this.hasEffects()) {
            if (this.frameId !== null) this.caf(this.frameId);
            this.frameId = null;
            this.lastTime = 0;
            if (this.hidden() || this.efficiencyPaused) {
                this.pendingThunderAt = 0;
                this.stopThunder();
                this.signal.reset();
            }
            return;
        }
        if (this.frameId === null) {
            this.lastTime = this.lastTime || this.now();
            this.frameId = this.raf(this.draw);
        }
    }
    draw(timestamp) {
        this.frameId = null;
        if (!this.active || !this.canvas || this.hidden() || this.efficiencyPaused) {
            this.sync();
            return;
        }
        const elapsed = timestamp - this.lastTime;
        if (elapsed >= 1000 / this.fps() - 0.25) {
            const begin = this.now(),
                dt = Math.min(0.1, Math.max(0.001, elapsed / 1000));
            this.lastTime = timestamp;
            this.simulationTime += dt * 1000;
            this.frame.time = this.simulationTime;
            this.frame.dt = dt;
            let audio = null;
            try {
                audio = this.provider?.();
            } catch {}
            this.frame.signal = this.signal.sample(audio, this.config, dt);
            const targetIntensity = Math.min(
                1,
                this.config.intensity * (1 + this.signal.value.energy * 0.12),
            );
            this.frame.intensity += (targetIntensity - this.frame.intensity) * (1 - Math.exp(-dt / 0.35));
            this.ctx.clearRect(0, 0, this.frame.width, this.frame.height);
            if (this.config.effects.fog) this.effects.fog.render(this.ctx, this.frame, this.config.fog);
            if (this.config.effects.rain) this.effects.rain.render(this.ctx, this.frame, this.config.rain);
            if (this.config.effects.snow) this.effects.snow.render(this.ctx, this.frame, this.config.snow);
            if (
                this.config.effects.thunderstorm &&
                this.effects.thunderstorm.render(this.ctx, this.frame, this.config.storm) &&
                this.config.storm.thunder &&
                this.audioArmed
            )
                this.pendingThunderAt = this.frame.time + 250 + this.random() * 500;
            if (this.pendingThunderAt && this.frame.time >= this.pendingThunderAt) {
                this.pendingThunderAt = 0;
                this.playThunder(audio);
            }
            const cost = Math.max(0, this.now() - begin);
            this.averageCost = this.averageCost * 0.9 + cost * 0.1;
            if (this.config.quality === 'auto' && timestamp > this.nextBudgetAt) {
                const previous = this.autoScale;
                if (this.averageCost > 6) this.autoScale = Math.max(0.3, this.autoScale * 0.8);
                else if (this.averageCost < 2) this.autoScale = Math.min(1, this.autoScale + 0.05);
                this.nextBudgetAt = timestamp + 3000;
                if (previous !== this.autoScale) this.rebuild();
            }
        }
        this.sync();
    }
    armAudio(event) {
        if (
            !this.config.enabled ||
            !this.config.effects.thunderstorm ||
            !this.config.storm.thunder ||
            this.reduced()
        )
            return false;
        if (event?.isTrusted !== true && !this.window.navigator?.userActivation?.isActive) return false;
        this.audioArmed = true;
        return true;
    }
    playThunder(audio) {
        const context = audio?.context;
        if (
            !this.audioArmed ||
            !this.config.storm.thunder ||
            this.reduced() ||
            !context ||
            context.state !== 'running' ||
            this.config.storm.volume <= 0
        )
            return;
        try {
            if (this.thunderContext !== context) {
                this.thunderBuffer = null;
                this.thunderContext = context;
            }
            if (!this.thunderBuffer) {
                this.thunderBuffer = context.createBuffer(
                    1,
                    Math.round(context.sampleRate * 1.7),
                    context.sampleRate,
                );
                const samples = this.thunderBuffer.getChannelData(0);
                let previous = 0;
                for (let index = 0; index < samples.length; index++) {
                    previous = (previous + this.random() * 0.04 - 0.02) / 1.02;
                    samples[index] = previous * 3;
                }
            }
            const source = context.createBufferSource(),
                filter = context.createBiquadFilter(),
                gain = context.createGain();
            source.buffer = this.thunderBuffer;
            filter.type = 'lowpass';
            filter.frequency.value = 180;
            const now = context.currentTime;
            gain.gain.setValueAtTime(0.0001, now);
            gain.gain.exponentialRampToValueAtTime(
                Math.min(0.12, this.config.storm.volume * 0.16),
                now + 0.12,
            );
            gain.gain.exponentialRampToValueAtTime(0.0001, now + 1.65);
            source.connect(filter);
            filter.connect(gain);
            gain.connect(context.destination);
            const nodes = { source, filter, gain };
            this.thunderNodes.add(nodes);
            source.onended = () => {
                source.disconnect();
                filter.disconnect();
                gain.disconnect();
                this.thunderNodes.delete(nodes);
            };
            source.start();
            source.stop(now + 1.7);
        } catch {
            this.stopThunder();
        }
    }
    stopThunder() {
        for (const nodes of this.thunderNodes) {
            try {
                nodes.source.onended = null;
                nodes.source.stop();
                nodes.source.disconnect();
                nodes.filter.disconnect();
                nodes.gain.disconnect();
            } catch {}
        }
        this.thunderNodes.clear();
    }
    release() {
        if (this.frameId !== null) this.caf(this.frameId);
        this.frameId = null;
        this.lastTime = 0;
        this.simulationTime = 0;
        for (const dispose of this.listeners) dispose();
        this.listeners.length = 0;
        this.media = null;
        for (const effect of Object.values(this.effects)) effect.release();
        this.stopThunder();
        this.pendingThunderAt = 0;
        this.thunderBuffer = null;
        this.thunderContext = null;
        this.signal.bins = null;
        this.signal.reset();
        if (this.canvas) {
            this.canvas.width = 0;
            this.canvas.height = 0;
            this.canvas.remove?.();
        }
        const host = this.document.getElementById('particles-bg');
        if (host) host.style.display = 'none';
        this.canvas = null;
        this.ctx = null;
        this.poolKey = null;
    }
    stop() {
        this.active = false;
        this.release();
    }
    destroy() {
        this.stop();
        this.provider = null;
        this.audioArmed = false;
    }
    status() {
        return {
            active: this.active,
            rendering: this.frameId !== null,
            canvas: !!this.canvas,
            fps: this.fps(),
            qualityScale: this.budget(),
            signal: { ...this.signal.value },
            listeners: this.listeners.length,
            audioArmed: this.audioArmed,
            thunderVoices: this.thunderNodes.size,
        };
    }
}
export const createAtmosphereEngine = (options) => new AtmosphereEngine(options);
const atmosphere = new AtmosphereEngine();
export function configureAtmosphere(config) {
    atmosphere.configure(config);
}
export function initAtmosphere() {
    if (globalThis.window?.settings?.atmosphere)
        atmosphere.config = normalizeAtmosphere(window.settings.atmosphere);
    atmosphere.init();
}
export function stopAtmosphere() {
    atmosphere.stop();
}
export function destroyAtmosphere() {
    atmosphere.destroy();
}
export function setAtmosphereFps(fps) {
    atmosphere.setFps(fps);
}
export function setAtmosphereAudioProvider(provider) {
    atmosphere.setAudioProvider(provider);
}
export function armAtmosphereAudio(event) {
    return atmosphere.armAudio(event);
}
export function getAtmosphereStatus() {
    return atmosphere.status();
}
