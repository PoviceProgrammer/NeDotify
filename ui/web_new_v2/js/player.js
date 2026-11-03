import { formatTime, renderIcons, showToast, getCoverUrl, extractDominantColor, escapeHtml, updatePlayingTrackInDOM, sizeCanvasForDpr, registerCanvasDprListener } from './utils.js';
import { fetchRealPeaks } from './waveform-peaks.js';

let isDraggingProgress = false;
let cancelProgressDrag = null;
let isDraggingVolume = false;
let lastSeekTime = 0;
let isSeeking = false;
let seekTimeoutId = null;
// Playback facts that must move together when the backend changes tracks or state.
// Keep this object as the single source for track, status, and timeline values.
const playbackState = {
    track: null,
    status: 'stopped',
    durationMs: 0,
    positionMs: 0,
    lastAnimTimestamp: 0,
};
let animFrameId = null;
let currentVolume = 70;
let isMuted = false;
let currentReplayGain = 1.0;
const TARGET_LUFS = -14.0;
let isInitialLoad = true;
let currentPlaybackRate = 1.0;
let currentPreservesPitch = true;
let currentQueueVersion = 0;
let playbackGeneration = 0;
let backendPlaybackEpoch = -1;
let recoveryRequest = null;
let retryStableSince = 0;
let preparedNext = null;
let automaticTransition = null;
let gaplessAdoptionKey = null;
let currentFadeInterval = null;
let outgoingAudio = null;
let desiredOutputDevice = 'default';
let actualOutputDevice = 'default';
let outputQueue = Promise.resolve();

// M-1: throttle volume RPC to 100ms (last value wins); flush immediately on release
let volumeRpcTimer = null;

function scheduleVolumeRpc(volume, immediate) {
    if (volumeRpcTimer !== null) clearTimeout(volumeRpcTimer);
    volumeRpcTimer = setTimeout(() => {
        volumeRpcTimer = null;
        api('set_volume', volume);
    }, immediate ? 0 : 100);
}

// Duration units normalizer: the backend persists seconds; anything already
// looking like milliseconds (a >50000s "track" is impossible) passes through.
function normalizeDurationMs(dur) {
    const d = Number(dur);
    if (!Number.isFinite(d) || d <= 0) return 0;
    return d > 50000 ? Math.round(d) : Math.round(d * 1000);
}

export function getQueueVersion() {
    return currentQueueVersion;
}

export function incrementQueueVersion() {
    currentQueueVersion++;
    preparedNext = null;
    return currentQueueVersion;
}

export function setPlaybackRate(rate) {
    currentPlaybackRate = Math.max(.25, Math.min(4, Number(rate) || 1));
    for (const audio of [audioA, audioB]) audio.playbackRate = currentPlaybackRate;
    notifyLyricsClock();
}

export function setPreservesPitch(enabled) {
    currentPreservesPitch = Boolean(enabled);
    for (const audio of [audioA, audioB]) {
        if ('preservesPitch' in audio) audio.preservesPitch = currentPreservesPitch;
        else if ('webkitPreservesPitch' in audio) audio.webkitPreservesPitch = currentPreservesPitch;
        else if ('mozPreservesPitch' in audio) audio.mozPreservesPitch = currentPreservesPitch;
    }
}

// Dual Audio Engine for Crossfade
let audioA = new Audio();
audioA.crossOrigin = "anonymous";
let audioB = new Audio();
audioB.crossOrigin = "anonymous";
let activeAudio = audioA;
// HLS instance lives on its audio element: prefetch loads the inactive element and
// must not tear down the stream the active element is still playing.
function destroyHls(audioEl) {
    if (audioEl) audioEl._loadedSourceUrl = null;
    if (audioEl && audioEl._hls) {
        try { audioEl._hls.destroy(); } catch(e) {}
        audioEl._hls = null;
    }
}

function normalizeAudioSourceUrl(src) {
    if (typeof src === 'string' && (src.startsWith('\\\\') || src.startsWith('//'))) return '';
    if (typeof src === 'string' && (src.match(/^[a-zA-Z]:[\\/]/) || src.startsWith('file://')) && window.PROXY_PORT) {
        const tokenQuery = window.PROXY_TOKEN ? `&k=${encodeURIComponent(window.PROXY_TOKEN)}` : '';
        return `http://127.0.0.1:${window.PROXY_PORT}/api/stream?url=${encodeURIComponent(src)}${tokenQuery}`;
    }
    return src;
}

function loadAudioSource(audioEl, src) {
    src = normalizeAudioSourceUrl(src);
    // A preloaded inactive element already owns the request and decoded data.
    // Clearing src here discarded that work exactly when playback needed it.
    if (src && audioEl._loadedSourceUrl === src && !audioEl.error) {
        if (audioEl.currentTime > 0) {
            try { audioEl.currentTime = 0; } catch(e) {}
        }
        return;
    }
    destroyHls(audioEl);
    // Reset stale src so a fast skip never fires error/stall handlers for the old stream
    try { audioEl.removeAttribute('src'); audioEl.src = ''; audioEl.load(); } catch(e) {}

    // Proxy query parameters percent-encode the upstream /playlist path.
    let mediaUrl = src;
    try { mediaUrl = new URL(src, window.location.href).searchParams.get('url') || src; } catch (e) {}
    const mediaType = audioEl._mediaType || (playbackState.track?.stream_url === src ? playbackState.track?.stream_type || playbackState.track?.mime_type : '');
    let soundcloudManifest = false;
    try {
        const upstream = new URL(mediaUrl);
        // SoundCloud's media service serves HLS without a .m3u8 suffix.
        // Restrict this to that service, not arbitrary /playlist CDN paths.
        soundcloudManifest = upstream.protocol === 'https:' &&
            upstream.hostname.endsWith('.soundcloud.cloud') &&
            /\/playlist\//.test(upstream.pathname) &&
            !/\.(?:mp3|mp4|m4a|aac|ogg|opus|webm|wav)$/i.test(upstream.pathname);
    } catch (_) {}
    // BUG-A1-015: HLS is decided by the backend's explicit stream_type/mime
    // marker, or by a genuinely manifest-shaped URL. The retired substring
    // probe for the /playlist path segment routed ordinary CDN paths into
    // hls.js, where a parse failure meant a fatal stop of playback.
    const isHls = soundcloudManifest || /(?:hls|mpegurl|m3u8)/i.test(mediaType || '') || typeof mediaUrl === 'string' && (mediaUrl.includes('.m3u8') || mediaUrl.includes('format=m3u8'));
    if (isHls && window.Hls && window.Hls.isSupported()) {
        try {
            audioEl._hls = new window.Hls({
                enableWorker: true,
                lowLatencyMode: false
            });
            audioEl._hls.loadSource(src);
            audioEl._hls.attachMedia(audioEl);
            if (audioEl._hls.on && window.Hls.Events?.ERROR) {
                audioEl._hls.on(window.Hls.Events.ERROR, (event, data) => {
                    if (data?.fatal && audioEl === activeAudio) handleStreamError(audioEl, 'hls_fatal');
                });
            }
            audioEl._loadedSourceUrl = src;
            return;
        } catch(he) {
            console.warn('HLS.js initialization error, falling back to direct src:', he);
        }
    }
    audioEl.src = src;
    try { audioEl.load(); } catch(e) {}
    audioEl._loadedSourceUrl = src;
}

// Prefetch state for the finite playback queue
function trackPlaybackKey(track) {
    if (!track) return '';
    if (track.source_id) return `${track.source || ''}|${track.source_id}`;
    if (track.id !== undefined && track.id !== null) return `id|${track.id}`;
    return `${track.source || ''}|${track.artist || ''}|${track.title || ''}`;
}

function releaseAudio(audio) {
    if (!audio) return;
    disarmStallFallback(audio);
    try { audio.pause(); } catch (error) {}
    destroyHls(audio);
    try { audio.removeAttribute('src'); audio.src = ''; audio.load(); } catch (error) {}
}

function finishFade() {
    if (currentFadeInterval !== null) clearInterval(currentFadeInterval);
    currentFadeInterval = null;
    if (outgoingAudio && outgoingAudio !== activeAudio) releaseAudio(outgoingAudio);
    outgoingAudio = null;
    if (activeAudio) activeAudio.volume = playbackVolume();
}

function playbackVolume() {
    return isMuted ? 0 : Math.min(1, Math.max(0, currentVolume / 100 * currentReplayGain));
}

function audioSetting(key, fallback) {
    if (window.settings?.audio?.[key] !== undefined) return window.settings.audio[key];
    try {
        const value = localStorage.getItem(`nedotify_audio_${key}`);
        return value === null ? fallback : JSON.parse(value);
    } catch (error) { return fallback; }
}

export async function listAudioOutputs(requestPermission = false) {
    const media = navigator.mediaDevices;
    const supported = audioCtx ? typeof audioCtx.setSinkId === 'function' :
        Boolean(typeof audioA.setSinkId === 'function' || window.AudioContext?.prototype?.setSinkId);
    if (!supported || !media?.enumerateDevices) return {supported: false, devices: [{deviceId: 'default', label: 'Системное устройство'}]};
    try {
        if (requestPermission && typeof media.selectAudioOutput === 'function') {
            await media.selectAudioOutput();
        }
        const devices = (await media.enumerateDevices()).filter(device => device.kind === 'audiooutput');
        return {supported: true, devices: [{deviceId: 'default', label: 'Системное устройство'},
            ...devices.filter(device => device.deviceId && device.deviceId !== 'default').map((device, index) => ({
                deviceId: device.deviceId, label: device.label || `Аудиоустройство ${index + 1}`,
            }))]};
    } catch (error) {
        return {supported: true, devices: [{deviceId: 'default', label: 'Системное устройство'}],
            code: error.name, error: 'Не удалось получить устройства. Разрешите выбор аудиовыхода и повторите'};
    }
}

function enqueueOutputDevice(deviceId) {
    const requested = deviceId === 'default' ? '' : deviceId;
    outputQueue = outputQueue.catch(() => {}).then(async () => {
        const targets = audioCtx ? [audioCtx] : [audioA, audioB];
        if (!targets.every(target => typeof target.setSinkId === 'function')) {
            return {ok: deviceId === 'default', deviceId: actualOutputDevice, code: 'unsupported',
                error: deviceId === 'default' ? undefined : 'Этот WebView не поддерживает выбор аудиовыхода'};
        }
        const previous = actualOutputDevice === 'default' ? '' : actualOutputDevice;
        try {
            for (const target of targets) await target.setSinkId(requested);
            actualOutputDevice = deviceId;
            return {ok: true, deviceId};
        } catch (error) {
            for (const target of targets) {
                try { await target.setSinkId(previous); } catch (rollbackError) {}
            }
            return {ok: false, deviceId: actualOutputDevice, code: error.name,
                error: error.name === 'NotAllowedError' ? 'Разрешите доступ к выбранному аудиовыходу' : 'Аудиоустройство недоступно. Обновите список устройств'};
        }
    });
    return outputQueue;
}

export async function setAudioOutput(deviceId, {persist = true} = {}) {
    const requested = String(deviceId || 'default');
    const previous = actualOutputDevice;
    const result = await enqueueOutputDevice(requested);
    if (result.ok) {
        if (persist) {
            const saved = await api('save_setting', 'output_device', requested, 'audio');
            if (saved !== true && saved?.success !== true) {
                await enqueueOutputDevice(previous);
                return {ok: false, deviceId: actualOutputDevice, code: 'save_failed',
                    error: 'Не удалось сохранить устройство вывода. Повторите выбор'};
            }
            if (window.settings?.audio) window.settings.audio.output_device = requested;
            try { localStorage.setItem('nedotify_audio_output_device', JSON.stringify(requested)); } catch (error) {}
        }
        desiredOutputDevice = requested;
    }
    return result;
}

export function applyAudioSettings(settings = {}) {
    if (settings.volume_normalization !== undefined) {
        updateReplayGain(Boolean(settings.volume_normalization));
        // A settings change affects the current element immediately. Retain the
        // outgoing fade ratio rather than interrupting an active crossfade.
        if (!outgoingAudio && activeAudio) activeAudio.volume = playbackVolume();
    }
    if (settings.output_device !== undefined) {
        desiredOutputDevice = String(settings.output_device || 'default');
        setAudioOutput(desiredOutputDevice, {persist: false}).then(result => {
            if (!result.ok && result.code !== 'unsupported') enqueueOutputDevice('default');
        });
    }
}

function updateReplayGain(enabled = audioSetting('volume_normalization', false)) {
    const track = playbackState.track;
    const loudness = track?.loudness_lufs ?? track?.lufs;
    currentReplayGain = enabled && loudness != null && Number.isFinite(Number(loudness))
        ? Math.min(2, Math.max(.1, Math.pow(10, (TARGET_LUFS - Number(loudness)) / 20))) : 1;
}

if (navigator.mediaDevices?.addEventListener) {
    navigator.mediaDevices.addEventListener('devicechange', async () => {
        const snapshot = await listAudioOutputs();
        if (!snapshot.supported || snapshot.error) return;
        const found = snapshot.devices.some(device => device.deviceId === desiredOutputDevice);
        const nextDevice = found ? desiredOutputDevice : 'default';
        if (nextDevice !== actualOutputDevice) {
            await enqueueOutputDevice(nextDevice);
            window.dispatchEvent(new CustomEvent('nedotify:audio_outputs_changed', {detail: snapshot}));
        }
    });
}

let lastPrefetchedTrackId = null;
let isPreloadingNextTrack = false;

// Web Audio API for Equalizer
let audioCtx = null;
let mediaSourcesCreated = false;
let eqNodes = [];
let preampNode = null;
let srcA = null;
let srcB = null;
let compressorNode = null;
let analyserNode = null;

let audioToolsRack = null;
let audioToolsCurrentSettings = null;
let audioToolsRevision = 0;
let sleepAtTrackEnd = false;
export function setSleepAtTrackEnd(enabled) {sleepAtTrackEnd=Boolean(enabled);}
export function cancelAudioFade() {audioToolsRack?.resetFade();}
export async function fadeOutAndPause(isCurrent=()=>true) {
    await applyAudioTools(audioToolsCurrentSettings || window.settings?.audio?.audio_tools || {},true);
    if (!isCurrent()) return;
    audioToolsRack?.fade(4);
    await new Promise(resolve=>setTimeout(resolve,4000));
    if (!isCurrent()) return;
    // Pause explicitly: toggling a paused or buffering element could resume it.
    finishFade();
    playbackGeneration++;
    recoveryRequest=null;pendingResume=null;automaticTransition=null;
    if(streamRetryTimer){clearTimeout(streamRetryTimer);streamRetryTimer=null;}
    for(const audio of [audioA,audioB])audio.pause();
    onStateChanged('paused');api('report_state','paused',Math.round(activeAudio.currentTime*1000)||0,playbackState.track?.listening_session);
    audioToolsRack?.resetFade();
}
export async function applyAudioTools(settings = {}, forceGraph=false) {
    const request=++audioToolsRevision;
    const module=await import('./audio-effects.js');
    if(request!==audioToolsRevision)return false;
    const next=module.normalizeAudioTools(settings);
    const needsGraph=Object.keys(module.AUDIO_DEFAULTS).some(key=>!['speed','linkedSpeed','pitch','engine'].includes(key)&&next[key]!==module.AUDIO_DEFAULTS[key]);
    if(forceGraph || needsGraph || audioToolsRack) {
        initAudioContext();
        if(!audioCtx || !compressorNode)throw new Error('Обработка звука недоступна');
        if(!audioToolsRack) {
            const tail=eqNodes[eqNodes.length-1];
            if(!tail)throw new Error('Эквалайзер недоступен');
            const rack=new module.RiffAudioRack(audioCtx);
            try {
                rack.output.connect(compressorNode);
                tail.disconnect(compressorNode);tail.connect(rack.input);
                audioToolsRack=rack;
            } catch(error) {
                rack.destroy();
                try{tail.disconnect();tail.connect(compressorNode);}catch{}
                throw error;
            }
        }
        audioToolsRack.apply(next);
    }
    audioToolsCurrentSettings=next;
    const playback=module.audioPlayback(next);
    setPreservesPitch(playback.preservesPitch);setPlaybackRate(playback.rate);
    return next;
}

// Atmosphere reads the existing post-EQ, mixed-deck analyser. This accessor
// never initializes/resumes the audio graph: enabling a backdrop cannot capture
// a media element again or create an AudioContext while playback is idle.
const atmosphereAudioSource = {analyser: null, context: null, playing: false, hasTrack: false};
export function getAtmosphereAudioSource() {
    atmosphereAudioSource.analyser = analyserNode;
    atmosphereAudioSource.context = audioCtx;
    atmosphereAudioSource.playing = playbackState.status === 'playing' && !activeAudio.paused;
    atmosphereAudioSource.hasTrack = Boolean(playbackState.track) && playbackState.status !== 'stopped';
    return atmosphereAudioSource;
}

function initAudioContext() {
    if (audioCtx) return;
    try {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        
        analyserNode = audioCtx.createAnalyser();
        analyserNode.fftSize = 256; // 128 frequency bins РІР‚вЂќ smoother visualizer
        analyserNode.smoothingTimeConstant = 0.8;
        
        // Create 10-band EQ filters (VLC / ISO standard curve)
        preampNode = audioCtx.createGain();
        const freqs = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000];
        
        let prevNode = preampNode;
        freqs.forEach((f, index) => {
            const filter = audioCtx.createBiquadFilter();
            if (index === 0) {
                filter.type = 'lowshelf';
            } else if (index === freqs.length - 1) {
                filter.type = 'highshelf';
            } else {
                filter.type = 'peaking';
                filter.Q.value = 1.414;
            }
            filter.frequency.value = f;
            filter.gain.value = 0;
            
            prevNode.connect(filter);
            prevNode = filter;
            eqNodes.push(filter);
        });
        
        // Add limiter/compressor to prevent digital clipping/distortion
        compressorNode = audioCtx.createDynamicsCompressor();
        compressorNode.threshold.value = -1.5;
        compressorNode.knee.value = 12;
        compressorNode.ratio.value = 3;
        compressorNode.attack.value = 0.003;
        compressorNode.release.value = 0.1;
        
        prevNode.connect(compressorNode);
        compressorNode.connect(analyserNode);
        analyserNode.connect(audioCtx.destination);
        
        // Connect both audio elements safely
        if (!mediaSourcesCreated || !srcA || (srcA.context && srcA.context !== audioCtx)) {
            if (mediaSourcesCreated && audioCtx) {
                const oldActive = activeAudio;
                const newAudioA = new Audio();
                newAudioA.crossOrigin = "anonymous";
                const newAudioB = new Audio();
                newAudioB.crossOrigin = "anonymous";
                setupAudioEvents(newAudioA);
                setupAudioEvents(newAudioB);
                audioA = newAudioA;
                audioB = newAudioB;
                activeAudio = (oldActive === audioB) ? audioB : audioA;
            }
            try {
                srcA = audioCtx.createMediaElementSource(audioA);
                srcB = audioCtx.createMediaElementSource(audioB);
                mediaSourcesCreated = true;
            } catch (err) {
                console.warn("createMediaElementSource failed:", err);
            }
        }
        
        if (srcA && srcA.context === audioCtx) {
            try { srcA.connect(preampNode); } catch {}
        }
        if (srcB && srcB.context === audioCtx) {
            try { srcB.connect(preampNode); } catch {}
        }
        enqueueOutputDevice(desiredOutputDevice).then(result => {
            if (!result.ok) enqueueOutputDevice('default');
        });
    } catch(e) {
        console.error("AudioContext initialization failed:", e);
        // A MediaElementSource captures its element permanently. Keep every
        // captured element connected even if a later DSP node failed.
        if (audioCtx && (srcA || srcB)) {
            for (const source of [srcA, srcB]) {
                if (!source) continue;
                try { source.disconnect(); source.connect(audioCtx.destination); } catch {}
            }
            analyserNode = null;
            eqNodes = [];
            preampNode = null;
        } else if (audioCtx) {
            Promise.resolve(audioCtx.close()).catch(() => {});
            audioCtx = null;
        }
    }
}

export function applyVolumeNormalization(enabled) {
    if (!audioCtx) initAudioContext();
    if (!compressorNode) return;
    try {
        if (enabled) {
            compressorNode.threshold.value = -1.5;
            compressorNode.knee.value = 12;
            compressorNode.ratio.value = 3;
            compressorNode.attack.value = 0.003;
            compressorNode.release.value = 0.1;
        } else {
            compressorNode.threshold.value = -1.0;
            compressorNode.knee.value = 24;
            compressorNode.ratio.value = 2;
        }
    } catch(e) {}
}

export function getAudioFrequencyData(dataArray) {
    if (!audioCtx) initAudioContext();
    if (audioCtx && audioCtx.state === 'suspended') {
        audioCtx.resume().catch(() => {});
    }
    if (analyserNode && dataArray) {
        analyserNode.getByteFrequencyData(dataArray);
        return true;
    }
    return false;
}

export function setEq(preamp, bands) {
    if (!audioCtx) initAudioContext();
    if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume().catch(() => {});
    
    const now = audioCtx ? audioCtx.currentTime : 0;
    if (preampNode && audioCtx) {
        const gainVal = Math.pow(10, preamp / 20); // dB to linear gain
        preampNode.gain.setTargetAtTime(gainVal, now, 0.015);
    }
    bands.forEach((val, i) => {
        if (eqNodes[i] && audioCtx) {
            eqNodes[i].gain.setTargetAtTime(val, now, 0.015);
        }
    });
}

// Global track retry management (prevents audioA/audioB ping-pong infinite loops)
let currentTrackRetries = 0;
let streamRetryTimer = null;
let lastRetriedTrackId = null;
let pendingResume = null;
const STALL_FALLBACK_MS = 10000;

function handleStreamError(audio, reason) {
    if (audio !== activeAudio || !playbackState.track) return;
    if (reason === 'NotAllowedError') {
        onStateChanged('paused');
        return;
    }
    disarmStallFallback(audio);
    if (streamRetryTimer || recoveryRequest) return;
    finishFade();
    const trackIdKey = trackPlaybackKey(playbackState.track);
    if (lastRetriedTrackId !== trackIdKey) {
        lastRetriedTrackId = trackIdKey;
        currentTrackRetries = 0;
    }
    
    currentTrackRetries++;
    console.warn(`Audio stream error (${reason}), retry attempt ${currentTrackRetries} for:`, playbackState.track.title);
    
    if (currentTrackRetries <= 2 && window.pywebview?.api?.recover_stream) {
        const resumeMs = Math.round((audio.currentTime || 0) * 1000);
        const generation = playbackGeneration;
        const track = {...playbackState.track};
        onStateChanged('loading');
        streamRetryTimer = setTimeout(async () => {
            streamRetryTimer = null;
            if (generation !== playbackGeneration || trackPlaybackKey(playbackState.track) !== trackIdKey) return;
            const request = {generation};
            recoveryRequest = request;
            try {
                const result = await window.pywebview.api.recover_stream(track, resumeMs);
                if (generation !== playbackGeneration || recoveryRequest !== request) return;
                recoveryRequest = null;
                if (!result?.ok || !result.stream_url) {
                    if (currentTrackRetries >= 2 || ['offline', 'file_missing'].includes(result?.code)) {
                        stopFailedPlayback(result?.error);
                    } else handleStreamError(audio, 'renewal_failed');
                    return;
                }
                releaseAudio(audio);
                playTrack({...track, stream_url: result.stream_url}, result.stream_url, {resumeMs, recovery: true});
            } catch (error) {
                if (generation !== playbackGeneration || recoveryRequest !== request) return;
                recoveryRequest = null;
                if (currentTrackRetries >= 2) stopFailedPlayback();
                else handleStreamError(audio, 'renewal_rejected');
            }
        }, 1500 * currentTrackRetries);
    } else {
        stopFailedPlayback();
    }
}

function stopFailedPlayback(message) {
    playbackGeneration++;
    recoveryRequest = null;
    pendingResume = null;
    finishFade();
    releaseAudio(audioA);
    releaseAudio(audioB);
    onStateChanged('paused');
    window.dispatchEvent(new CustomEvent('nedotify:toast', {detail: {
        msg: message || `Не удалось восстановить «${playbackState.track?.title || 'трек'}». Проверьте подключение и повторите`,
        type: 'error',
    }}));
}

function armStallFallback(audio) {
    disarmStallFallback(audio);
    audio._stallTimer = setTimeout(() => {
        audio._stallTimer = null;
        if (audio === activeAudio && playbackState.track && !audio.paused && audio.src && audio.src !== '' && audio.src !== 'about:blank') {
            handleStreamError(audio, 'stall_timeout');
        }
    }, STALL_FALLBACK_MS);
}

function disarmStallFallback(audio) {
    if (audio._stallTimer) {
        clearTimeout(audio._stallTimer);
        audio._stallTimer = null;
    }
}

function setupAudioEvents(audio) {
    for (const name of ['play', 'pause', 'seeking', 'seeked', 'waiting', 'stalled', 'playing', 'ratechange', 'emptied']) {
        audio.addEventListener(name, () => {
            if (audio === activeAudio) document.dispatchEvent(new CustomEvent('nedotify:lyrics_clock_changed', {detail: {}}));
        });
    }
    audio.addEventListener('loadstart', () => armStallFallback(audio));
    audio.addEventListener('stalled', () => {
        armStallFallback(audio);
        if (audio === activeAudio) retryStableSince = 0;
        if (audio === activeAudio) api('report_listening_state', playbackState.track?.listening_session, false);
    });
    audio.addEventListener('waiting', () => {
        armStallFallback(audio);
        if (audio === activeAudio) retryStableSince = 0;
        if (audio === activeAudio) api('report_listening_state', playbackState.track?.listening_session, false);
    });
    audio.addEventListener('playing', () => {
        disarmStallFallback(audio);
        if (audio === activeAudio) {
            retryStableSince = performance.now();
            api('report_state', 'playing', Math.round(audio.currentTime * 1000), playbackState.track?.listening_session);
            api('report_listening_state', playbackState.track?.listening_session, true, false, audio.duration, audio.playbackRate);
            onStateChanged('playing');
        }
    });
    audio.addEventListener('canplay', () => disarmStallFallback(audio));
    audio.addEventListener('loadedmetadata', () => {
        if (audio === activeAudio) applyPendingResume(audio);
    });
    audio.addEventListener('progress', () => {
        if (audio.readyState >= 3) disarmStallFallback(audio);
    });
    audio.addEventListener('seeking', () => {
        if (audio === activeAudio) {
            isSeeking = true;
            api('report_listening_state', playbackState.track?.listening_session, false);
        }
    });
    audio.addEventListener('seeked', () => {
        if (audio === activeAudio) {
            isSeeking = false;
            if (!audio.paused && audio.readyState >= 3) {
                api('report_listening_state', playbackState.track?.listening_session, true, false, audio.duration, audio.playbackRate);
            }
            if (seekTimeoutId) {
                clearTimeout(seekTimeoutId);
                seekTimeoutId = null;
            }
        }
    });
    audio.addEventListener('timeupdate', () => {
        if (audio === activeAudio && !isDraggingProgress && !isSeeking) {
            // Prefer HTML5 duration if backend didn't provide one
            // PLAYER-001: only trust it once the media has current data, so a
            // stale duration from a previous track can't overwrite the timeline.
            if (audio.readyState >= 2 && audio.duration && audio.duration !== Infinity) {
                const audioDurMs = Math.round(audio.duration * 1000);
                if (audioDurMs > 0 && Math.abs(playbackState.durationMs - audioDurMs) > 2000) {
                    playbackState.durationMs = audioDurMs;
                    setElText('pb-time-total', formatTime(playbackState.durationMs / 1000));
                    setElText('pp-time-total', formatTime(playbackState.durationMs / 1000));
                }
            }
            
            playbackState.positionMs = Math.round(audio.currentTime * 1000);
            if (retryStableSince && performance.now() - retryStableSince > 30000) currentTrackRetries = 0;
            checkAutomaticTransition((playbackState.durationMs - playbackState.positionMs) / 1000);
            if (isPlayerUiHidden() && (playbackState.status === 'playing') && playbackState.durationMs > 0) {
                checkPlaybackLookahead((playbackState.durationMs - playbackState.positionMs) / 1000);
            }
            
            // Also paint paused/buffering media and newly discovered duration.
            if (!isPlayerUiHidden()) paintPlaybackProgress();

            // Dispatch locally for lyrics
            document.dispatchEvent(new CustomEvent('nedotify:position_changed', { detail: { pos: playbackState.positionMs, duration: playbackState.durationMs } }));
            
            // Periodically report to backend for scrobbling
            const now = performance.now();
            if (now - (window._lastReportTime || 0) > 5000) {
                window._lastReportTime = now;
                api('report_position', playbackState.positionMs, playbackState.durationMs, 0, playbackState.track?.listening_session);
            }
        }
    });
    // 'playing' above means audio is audible; 'play' can still be buffering.
    audio.addEventListener('pause', () => { 
        if (audio === activeAudio) {
            retryStableSince = 0;
            api('report_state', 'paused', Math.round(audio.currentTime * 1000), playbackState.track?.listening_session);
            onStateChanged('paused');
        }
    });
    audio.addEventListener('ended', async () => {
        if (audio === activeAudio) {
            if (sleepAtTrackEnd) {
                sleepAtTrackEnd=false;
                api('report_listening_state',playbackState.track?.listening_session,false,true,audio.duration,audio.playbackRate);
                stopPlaybackForQueueEnd();api('report_state','paused',0,playbackState.track?.listening_session);
                window.dispatchEvent(new Event('nedotify:sleep_timer_finished'));return;
            }
            if (automaticTransition) return;
            const endedGeneration = playbackGeneration;
            let gaplessStarted = false;
            if (window.pywebview?.api?.report_listening_state) {
                Promise.resolve(window.pywebview.api.report_listening_state(playbackState.track?.listening_session, false, true, audio.duration, audio.playbackRate)).catch(() => {});
            }
            if (audioSetting('gapless_playback', false) && preparedNext && preparedNext.queueVersion === currentQueueVersion) {
                const prepared = preparedNext;
                const incoming = audio === audioA ? audioB : audioA;
                if (incoming.readyState >= 3 && prepared.key !== trackPlaybackKey(playbackState.track)) {
                    playTrack(prepared.track, prepared.track.stream_url, {automatic: true});
                    gaplessStarted = true;
                }
            }
            let advanced = false;
            if (window.pywebview?.api?.next_track) {
                try {
                    const nextRes = await window.pywebview.api.next_track(false);
                    if (nextRes) advanced = true;
                } catch(e) {
                    console.error('next_track on ended failed:', e);
                }
            } else {
                api('next_track', false);
            }
        }
    });
    audio.addEventListener('error', (e) => {
        if (audio === activeAudio) api('report_listening_state', playbackState.track?.listening_session, false);
        isSeeking = false;
        if (seekTimeoutId) {
            clearTimeout(seekTimeoutId);
            seekTimeoutId = null;
        }
        // Ignore synthetic or background cleanup errors
        if (audio !== activeAudio || !audio.src || audio.src === '' || audio.src === 'about:blank' || audio.src === window.location.href) {
            return;
        }
        handleStreamError(audio, 'error_event');
    });
}

function applyPendingResume(audio) {
    if (!audio || !pendingResume || pendingResume.ms <= 0
        || pendingResume.key !== trackPlaybackKey(playbackState.track)) return false;
    const seconds = pendingResume.ms / 1000;
    try { audio.currentTime = Number.isFinite(audio.duration) ? Math.min(seconds, Math.max(0, audio.duration - 0.05)) : seconds; }
    catch { return false; }
    playbackState.positionMs = Math.round(audio.currentTime * 1000);
    pendingResume = null;
    return true;
}
for (const audio of [audioA, audioB]) {
    audio.addEventListener('ratechange', () => {
        if (audio === activeAudio) api('report_listening_state', playbackState.track?.listening_session, !audio.paused && !isSeeking, false, audio.duration, audio.playbackRate);
    });
}
setupAudioEvents(audioA);
setupAudioEvents(audioB);

export function updateMediaSession(track) {
    if ('mediaSession' in navigator) {
        navigator.mediaSession.metadata = new MediaMetadata({
            title: track.title || 'Unknown Title',
            artist: track.artist || 'Unknown Artist',
            artwork: [
                { src: getCoverUrl(track), sizes: '512x512', type: 'image/jpeg' }
            ]
        });
        
        navigator.mediaSession.setActionHandler('play', () => {
            if (activeAudio.paused && !streamRetryTimer && !recoveryRequest) togglePlayPause();
        });
        navigator.mediaSession.setActionHandler('pause', () => {
            if (!activeAudio.paused || streamRetryTimer || recoveryRequest) togglePlayPause();
        });
        navigator.mediaSession.setActionHandler('previoustrack', () => api('prev_track'));
        navigator.mediaSession.setActionHandler('nexttrack', () => api('next_track'));
    }
}

export function playTrack(track, streamUrl, options = {}) {
    if (!track || !streamUrl) return;
    
    if (audioCtx && audioCtx.state === 'suspended') {
        audioCtx.resume().catch(() => {});
    }
    
    updateMediaSession(track);
    
    finishFade();
    playbackGeneration++;
    recoveryRequest = null;
    retryStableSince = 0;

    if (streamRetryTimer) {
        clearTimeout(streamRetryTimer);
        streamRetryTimer = null;
    }

    const trackIdKey = trackPlaybackKey(track);
    gaplessAdoptionKey = options.automatic ? trackIdKey : null;
    if (!options.recovery) {
        lastRetriedTrackId = trackIdKey;
        currentTrackRetries = 0;
    }

    // ReplayGain LUFS volume normalization
    updateReplayGain();

    const newAudio = activeAudio === audioA ? audioB : audioA;
    const oldAudio = activeAudio;
    const transition = automaticTransition;
    const fadeDuration = transition && transition.key === trackIdKey && transition.queueVersion === currentQueueVersion
        ? Math.min(transition.duration, Math.max(0, (oldAudio.duration - oldAudio.currentTime) / currentPlaybackRate)) : 0;
    automaticTransition = null;
    preparedNext = null;
    lastPrefetchedTrackId = null;
    isPreloadingNextTrack = false;
    
    // Switch activeAudio immediately FIRST to prevent old audio error handlers from firing
    activeAudio = newAudio;
    playbackState.track = track;
    playbackState.status = 'loading';
    disarmStallFallback(newAudio);
    
    // Instantly stop and clean up old audio
    if (oldAudio && fadeDuration > 0 && !oldAudio.paused) {
        outgoingAudio = oldAudio;
    } else if (oldAudio) {
        disarmStallFallback(oldAudio);
        try { oldAudio.pause(); } catch(e) {}
        try { oldAudio.currentTime = 0; } catch(e) {}
        destroyHls(oldAudio);
        oldAudio.removeAttribute('src');
        oldAudio.src = '';
        try { oldAudio.load(); } catch(e) {}
    }

    // Parse duration from streamUrl if track.duration is missing
    let parsedDuration = 0;
    try {
        const urlParams = new URLSearchParams(streamUrl.split('?')[1]);
        const durParam = urlParams.get('duration');
        if (durParam) {
            parsedDuration = parseInt(durParam, 10);
        }
    } catch(e) {}

    const dur = track.duration || parsedDuration;
    playbackState.durationMs = normalizeDurationMs(dur);
    pendingResume = Number(options.resumeMs) > 0 ? {key: trackIdKey, ms: Number(options.resumeMs)} : null;

    loadAudioSource(newAudio, streamUrl);
    if (newAudio.readyState >= 1) applyPendingResume(newAudio);
    newAudio.playbackRate = currentPlaybackRate;
    if ('preservesPitch' in newAudio) newAudio.preservesPitch = currentPreservesPitch;
    else if ('webkitPreservesPitch' in newAudio) newAudio.webkitPreservesPitch = currentPreservesPitch;
    else if ('mozPreservesPitch' in newAudio) newAudio.mozPreservesPitch = currentPreservesPitch;

    const targetVol = isMuted ? 0 : Math.min(1.0, Math.max(0.0, (currentVolume / 100) * currentReplayGain));
    newAudio.volume = outgoingAudio ? 0 : targetVol;
    const generation = playbackGeneration;
    
    const playPromise = newAudio.play();
    if (playPromise !== undefined) {
        playPromise.then(() => {
            if (generation !== playbackGeneration || newAudio !== activeAudio || !outgoingAudio) return;
            const outgoing = outgoingAudio;
            const initialVolume = outgoing.volume;
            const started = performance.now();
            currentFadeInterval = setInterval(() => {
                if (generation !== playbackGeneration || newAudio.paused) { finishFade(); return; }
                const fraction = Math.min(1, (performance.now() - started) / (fadeDuration * 1000));
                outgoing.volume = Math.max(0, initialVolume * Math.cos(fraction * Math.PI / 2));
                newAudio.volume = playbackVolume() * Math.sin(fraction * Math.PI / 2);
                if (fraction >= 1) finishFade();
            }, 25);
        }).catch(e => {
            if (generation !== playbackGeneration || newAudio !== activeAudio || e.name === 'AbortError') return;
            if (e.name === 'NotAllowedError') {
                console.warn("Audio autoplay blocked by browser policy (NotAllowedError):", e);
                onStateChanged('paused');
                return;
            }
            console.warn("Audio play promise error:", e);
            handleStreamError(newAudio, 'play_rejected');
        });
    }
    
    // BUG-A1-013: playTrack used to claim 'playing' before any audio was
    // audible, so the whole buffering phase showed a playing UI. The real
    // state arrives with the element's 'playing' event (setupAudioEvents);
    // until then the player is buffering, not playing.
    onStateChanged('loading');
}

export function seekTo(posMs) {
    if (!Number.isFinite(playbackState.durationMs) || playbackState.durationMs <= 0) return;
    posMs = Math.min(Math.max(0, Number(posMs) || 0), Math.max(0, playbackState.durationMs));
    finishFade();
    automaticTransition = null;
    playbackState.positionMs = posMs;
    lastSeekTime = performance.now();
    isSeeking = true;
    if (seekTimeoutId) {
        clearTimeout(seekTimeoutId);
        seekTimeoutId = null;
    }
    // Remove isSeeking as soon as the active media reports the seek completed.
    // Add the listener lazily so elements created without setupAudioEvents still work.
    if (activeAudio && typeof activeAudio.addEventListener === 'function' && !activeAudio._nedotifySeekedClearsSeeking) {
        const seekTarget = activeAudio;
        seekTarget.addEventListener('seeked', () => {
            if (seekTarget === activeAudio) {
                isSeeking = false;
                if (seekTimeoutId) {
                    clearTimeout(seekTimeoutId);
                    seekTimeoutId = null;
                }
            }
        });
        seekTarget._nedotifySeekedClearsSeeking = true;
    }
    // A same-position seek can omit seeked. Only clear that case: HLS may
    // legitimately take longer than this guard to load the target segment.
    const seekingAudio = activeAudio;
    seekTimeoutId = setTimeout(() => {
        if (activeAudio === seekingAudio && !seekingAudio?.seeking) isSeeking = false;
        seekTimeoutId = null;
    }, 1500);
    
    paintPlaybackProgress();

    if (activeAudio) {
        try {
            activeAudio.currentTime = posMs / 1000;
        } catch (e) {
            console.error("Error seeking audio:", e);
            isSeeking = false;
            if (seekTimeoutId) {
                clearTimeout(seekTimeoutId);
                seekTimeoutId = null;
            }
        }
    }
    // M-1: single RPC with the final value (set_position is a no-op on the backend)
    api('report_position', posMs, playbackState.durationMs, 0, playbackState.track?.listening_session);
    if (typeof CustomEvent === 'function') document.dispatchEvent?.(new CustomEvent('nedotify:lyrics_clock_changed', {detail: {}}));
}


export function getCurrentTrack() { return playbackState.track; }
export function getIsPlaying() { return (playbackState.status === 'playing'); }
window.getIsPlaying = getIsPlaying;
export function getVolume() { return isMuted ? 0 : currentVolume; }

// The primary element switches when the incoming crossfade track is adopted.
// Reading it directly avoids a second timer drifting during pause/seek/buffering.
export function getLyricsPlaybackClock() {
    const position = Number(activeAudio?.currentTime);
    const path = playbackState.track?.file_path || '';
    const track = playbackState.track;
    return {
        positionMs: Number.isFinite(position) ? Math.max(0, position * 1000) : playbackState.positionMs || 0,
        paused: !activeAudio || activeAudio.paused || playbackState.status !== 'playing',
        buffering: !activeAudio || activeAudio.readyState < 3,
        seeking: Boolean(activeAudio?.seeking || isSeeking),
        playbackRate: Number(activeAudio?.playbackRate) || 1,
        trackKey: track ? JSON.stringify([track.source || 'local', track.source_id || track.id || '',
            track.title || '', track.artist || '', track.album || '', /^https?:\/\//i.test(path) ? '' : path]) : '',
    };
}

function notifyLyricsClock() {
    document.dispatchEvent(new CustomEvent('nedotify:lyrics_clock_changed', {detail: {}}));
}



export function togglePlayPause() {
    if (streamRetryTimer || recoveryRequest) {
        playbackGeneration++;
        recoveryRequest = null;
        pendingResume = null;
        if (streamRetryTimer) { clearTimeout(streamRetryTimer); streamRetryTimer = null; }
        finishFade();
        activeAudio.pause();
        onStateChanged('paused');
        return;
    }
    if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume().catch(() => {});

    // BUG-A1-007: a loaded src only counts as resumable when it belongs to the
    // CURRENT track. After a track change the resolving window (and after an
    // audio_error) the element still holds the previous stream; playing it
    // would sound the old song under the new title.
    const currentTrackSrc = normalizeAudioSourceUrl(
        playbackState.track?.stream_url || playbackState.track?.file_path || '');
    const hasValidSrc = Boolean(
        currentTrackSrc &&
        activeAudio && activeAudio._loadedSourceUrl === currentTrackSrc &&
        activeAudio.src && activeAudio.src !== '' && !activeAudio.src.endsWith('about:blank'));
    if (!hasValidSrc) {
        // The element is holding a stale stream for a track that never
        // resolved; release it so no retry can resurrect the previous song.
        if (activeAudio && activeAudio._loadedSourceUrl && activeAudio._loadedSourceUrl !== currentTrackSrc) {
            releaseAudio(activeAudio);
        }
        if (playbackState.track) {
            if (window.pywebview?.api?.play_track) {
                // The backend owns the authoritative queue. Passing the UI's
                // snapshot here could overwrite intervening shuffle/reorder edits.
                Promise.resolve(window.pywebview.api.play_track(playbackState.track)).then(result => {
                    if (result === false || result?.success === false) {
                        showToast('Не удалось продолжить воспроизведение', 'error');
                    }
                }).catch(() => showToast('Не удалось продолжить воспроизведение', 'error'));
            }
        }
        return;
    }

    if (activeAudio.paused) {
        currentTrackRetries = 0;
        activeAudio.play().catch(e => console.error("Play error:", e));
    } else {
        finishFade();
        playbackGeneration++;
        recoveryRequest = null;
        if (streamRetryTimer) { clearTimeout(streamRetryTimer); streamRetryTimer = null; }
        activeAudio.pause();
        // Also pause the inactive audio if it's currently crossfading
        const inactiveAudio = activeAudio === audioA ? audioB : audioA;
        if (!inactiveAudio.paused) {
            inactiveAudio.pause();
        }
    }
}

export function initPlayer() {
    // Reserve the largest morph width so transport neighbours never move.
    for (const prefix of ['pb', 'pp']) {
        const button = document.getElementById(`${prefix}-btn-play`);
        if (button && !button.parentElement?.classList.contains('player-play-slot')) {
            const slot = document.createElement('span');
            slot.className = `player-play-slot ${prefix}-play-slot`;
            button.before(slot);
            slot.appendChild(button);
        }
    }
    // Bottom bar controls
    const btnPlay = document.getElementById('pb-btn-play');
    const btnNext = document.getElementById('pb-btn-next');
    const btnPrev = document.getElementById('pb-btn-prev');
    const btnShuffle = document.getElementById('pb-btn-shuffle');
    const btnRepeat = document.getElementById('pb-btn-repeat');
    const btnLike = document.getElementById('pb-btn-like');

    /* keydown moved to hotkeys.js */

    if (btnPlay) btnPlay.addEventListener('click', togglePlayPause);
    if (btnNext) btnNext.addEventListener('click', () => api('next_track', true));
    if (btnPrev) btnPrev.addEventListener('click', () => api('prev_track'));

    if (btnShuffle) btnShuffle.addEventListener('click', async () => {
        const active = await api('toggle_shuffle');
        btnShuffle.classList.toggle('active', active);
        const ppShuffle = document.getElementById('pp-btn-shuffle');
        if (ppShuffle) ppShuffle.classList.toggle('active', active);
    });

    if (btnRepeat) btnRepeat.addEventListener('click', async () => {
        const mode = await api('toggle_repeat');
        btnRepeat.classList.toggle('active', mode !== 'off');
        const ppRepeat = document.getElementById('pp-btn-repeat');
        if (ppRepeat) ppRepeat.classList.toggle('active', mode !== 'off');
        updateRepeatIcon(btnRepeat, mode);
        if (ppRepeat) updateRepeatIcon(ppRepeat, mode);
    });

    if (btnLike) btnLike.addEventListener('click', async () => {
        if (!playbackState.track) return;
        const res = await api('toggle_favorite', playbackState.track);
        if (res && res.success) {
            playbackState.track.is_favorite = res.is_favorite;
            updateLikeButtons();
        }
    });

    // Player page controls
    const ppPlay = document.getElementById('pp-btn-play');
    const ppNext = document.getElementById('pp-btn-next');
    const ppPrev = document.getElementById('pp-btn-prev');
    const ppShuffle = document.getElementById('pp-btn-shuffle');
    const ppRepeat = document.getElementById('pp-btn-repeat');
    const ppLike = document.getElementById('pp-btn-like');

    if (ppPlay) ppPlay.addEventListener('click', togglePlayPause);
    if (ppNext) ppNext.addEventListener('click', () => api('next_track', true));
    if (ppPrev) ppPrev.addEventListener('click', () => api('prev_track'));

    if (ppShuffle) ppShuffle.addEventListener('click', async () => {
        const active = await api('toggle_shuffle');
        ppShuffle.classList.toggle('active', active);
        if (btnShuffle) btnShuffle.classList.toggle('active', active);
    });

    if (ppRepeat) ppRepeat.addEventListener('click', async () => {
        const mode = await api('toggle_repeat');
        ppRepeat.classList.toggle('active', mode !== 'off');
        if (btnRepeat) btnRepeat.classList.toggle('active', mode !== 'off');
        updateRepeatIcon(ppRepeat, mode);
        if (btnRepeat) updateRepeatIcon(btnRepeat, mode);
    });

    if (ppLike) ppLike.addEventListener('click', async () => {
        if (!playbackState.track) return;
        const res = await api('toggle_favorite', playbackState.track);
        if (res && res.success) {
            playbackState.track.is_favorite = res.is_favorite;
            updateLikeButtons();
        }
    });

    document.getElementById('pp-btn-more')?.addEventListener('click', event => {
        if (playbackState.track) window.NeDotify?.showTrackContextMenu?.(playbackState.track, event);
    });
    const expandPlayer = document.getElementById('pp-btn-expand');
    let playerHomeMarker = null;
    const setPlayerExpanded = expanded => {
        const view = document.getElementById('view-player');
        // backdrop-filter on #main-content establishes a containing block for
        // fixed descendants. Move the existing view instead of cloning it:
        // media, lyrics nodes, listeners and scroll state all remain intact.
        if (expanded && view && !playerHomeMarker) {
            playerHomeMarker = document.createComment('player view home');
            view.before(playerHomeMarker);
            document.body.appendChild(view);
        } else if (!expanded && playerHomeMarker && view) {
            playerHomeMarker.replaceWith(view);
            playerHomeMarker = null;
        }
        view?.classList.toggle('player-expanded', expanded);
        document.documentElement.classList.toggle('player-view-expanded', expanded);
        expandPlayer?.setAttribute('aria-pressed', String(expanded));
        expandPlayer?.setAttribute('aria-label', expanded ? 'Свернуть плеер' : 'Развернуть плеер');
        expandPlayer?.setAttribute('title', expanded ? 'Свернуть плеер' : 'Развернуть плеер');
        window.dispatchEvent(new Event('resize'));
    };
    expandPlayer?.addEventListener('click', () => setPlayerExpanded(expandPlayer.getAttribute('aria-pressed') !== 'true'));
    window.addEventListener('nedotify:page_changed', event => {
        if (event.detail !== 'player' && expandPlayer?.getAttribute('aria-pressed') === 'true') setPlayerExpanded(false);
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && expandPlayer?.getAttribute('aria-pressed') === 'true') {
            setPlayerExpanded(false);
            expandPlayer.focus();
        }
    });



    const ppQueue = document.getElementById('pp-btn-queue');
    if (ppQueue) ppQueue.addEventListener('click', () => {
        const queueDrawer = document.getElementById('queue-drawer');
        if (queueDrawer) queueDrawer.classList.toggle('open');
    });

    // Tray Context Menu Action Listener (Phase 5)
    window.addEventListener('nedotify:tray_action', (evt) => {
        const action = evt.detail?.action;
        switch(action) {
            case 'toggle_play':
                togglePlayPause();
                break;
            case 'next':
                api('next_track');
                break;
            case 'prev':
                api('prev_track');
                break;
            case 'toggle_like':
                if (playbackState.track) {
                    api('toggle_favorite', playbackState.track).then(res => {
                        if (res && res.success) {
                            playbackState.track.is_favorite = res.is_favorite;
                            updateLikeButtons();
                        }
                    });
                }
                break;
        }
    });

    // Status-bar mini player shares the main transport and timeline.
    document.getElementById('mp-btn-play')?.addEventListener('click', togglePlayPause);
    document.getElementById('mp-btn-next')?.addEventListener('click', () => api('next_track', true));
    document.getElementById('mp-btn-prev')?.addEventListener('click', () => api('prev_track'));
    const restoreMainWindow = () => window.toggleMiniPlayerMode?.(false);
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && document.body.classList.contains('mini-player-active')) {
            event.preventDefault();
            restoreMainWindow();
        }
    });
    const mpCard = document.getElementById('mini-player-overlay');
    mpCard?.addEventListener('mousedown', event => {
        if (event.button !== 0 || event.target.closest('button, a, input, [role="slider"]')) return;
        event.preventDefault();
        api('begin_window_drag');
    });
    mpCard?.addEventListener('dblclick', event => {
        if (!event.target.closest('button, [role="slider"]')) restoreMainWindow();
    });

    setupDragBar('mp-progress-track', progressDragHandlers());
    setupDragBar('pb-progress-track', progressDragHandlers(), {
        pointerEnabled: () => document.documentElement.dataset.progressStyle !== 'panel',
    });
    setupDragBar('player-bar', progressDragHandlers(), {
        pointerEnabled: () => document.documentElement.dataset.progressStyle === 'panel',
        feedbackId: 'pb-progress-track', keyboard: false,
    });
    setupDragBar('pp-progress-track', progressDragHandlers());
    paintPlaybackProgress();

    // Volume bar drag
    const syncVolumeAria = () => {
        ['pb-volume-track', 'mp-volume-track'].forEach((id) => {
            const vt = document.getElementById(id);
            if (vt) vt.setAttribute('aria-valuenow', String(currentVolume));
        });
    };
    setupDragBar('pb-volume-track', {
        onCancel: () => { isDraggingVolume = false; scheduleVolumeRpc(currentVolume, true); },
        onDrag: (pct) => {
            isDraggingVolume = true;
            currentVolume = Math.round(pct * 100);
            setEl('pb-volume-fill', 'width', `${pct * 100}%`);
            updateVolumeIcon(currentVolume, isMuted);
            activeAudio.volume = isMuted ? 0 : Math.min(1.0, Math.max(0.0, (currentVolume / 100) * currentReplayGain));
            // M-1: throttle RPC while dragging РІР‚вЂќ last value wins
            syncVolumeAria();
            scheduleVolumeRpc(currentVolume, false);
        },
        onRelease: (pct) => {
            isDraggingVolume = false;
            currentVolume = Math.round(pct * 100);
            activeAudio.volume = isMuted ? 0 : Math.min(1.0, Math.max(0.0, (currentVolume / 100) * currentReplayGain));
            // M-1: flush the final value immediately
            syncVolumeAria();
            scheduleVolumeRpc(currentVolume, true);
        }
    });

    // Volume bar drag (mini player) — mirrors the bottom-bar handler
    setupDragBar('mp-volume-track', {
        onCancel: () => { isDraggingVolume = false; scheduleVolumeRpc(currentVolume, true); },
        onDrag: (pct) => {
            isDraggingVolume = true;
            currentVolume = Math.round(pct * 100);
            setEl('mp-volume-fill', 'width', `${pct * 100}%`);
            updateVolumeIcon(currentVolume, isMuted);
            activeAudio.volume = isMuted ? 0 : Math.min(1.0, Math.max(0.0, (currentVolume / 100) * currentReplayGain));
            syncVolumeAria();
            scheduleVolumeRpc(currentVolume, false);
        },
        onRelease: (pct) => {
            isDraggingVolume = false;
            currentVolume = Math.round(pct * 100);
            activeAudio.volume = isMuted ? 0 : Math.min(1.0, Math.max(0.0, (currentVolume / 100) * currentReplayGain));
            syncVolumeAria();
            scheduleVolumeRpc(currentVolume, true);
        }
    });

    window.NeDotify = window.NeDotify || {};
    window.NeDotify.adjustVolume = (delta) => {
        currentVolume = Math.max(0, Math.min(100, currentVolume + delta));
        setEl('pb-volume-fill', 'width', `${currentVolume}%`);
        updateVolumeIcon(currentVolume, isMuted);
        if (activeAudio) activeAudio.volume = isMuted ? 0 : Math.min(1.0, Math.max(0.0, (currentVolume / 100) * currentReplayGain));
        // M-1: discrete event РІР‚вЂќ send immediately
        syncVolumeAria();
        scheduleVolumeRpc(currentVolume, true);
    };

    // Volume icon mute toggle: backend owns the persisted mute state
    const volBtn = document.getElementById('pb-volume-btn');
    if (volBtn) volBtn.addEventListener('click', async () => {
        let next = !isMuted;
        if (window.pywebview?.api?.toggle_mute) {
            try { next = !!(await window.pywebview.api.toggle_mute()); } catch(e) {}
        }
        applyMuteState(next);
    });
    // Mini player volume icon mirrors the bottom-bar mute toggle
    const mpVolBtn = document.getElementById('mp-volume-btn');
    if (mpVolBtn) mpVolBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        let next = !isMuted;
        if (window.pywebview?.api?.toggle_mute) {
            try { next = !!(await window.pywebview.api.toggle_mute()); } catch(err) {}
        }
        applyMuteState(next);
    });
    window.awaitBridge?.().then(async () => {
        if (!window.pywebview?.api?.is_muted) return;
        try { applyMuteState(!!(await window.pywebview.api.is_muted())); } catch(e) {}
    }).catch(() => {});

    // Three-dot track options menu
    const optBtn = document.getElementById('pb-btn-options');
    const optMenu = document.getElementById('track-options-menu');
    if (optBtn && optMenu) {
        optBtn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const rect = optBtn.getBoundingClientRect();
            optMenu.style.left = `${rect.left}px`;
            optMenu.style.top = `${rect.top - 10}px`;
            optMenu.style.transform = 'translateY(-100%)';
            optMenu.classList.toggle('visible');
            // Fixed-position menu: dismiss it when the window resizes or the page changes.
            if (optMenu.classList.contains('visible')) {
                window.NeDotify?._armFloatingMenuGuard?.();
            }

            // Update track title in header
            const header = document.getElementById('track-options-header');
            if (header && playbackState.track) {
                header.textContent = playbackState.track.title || 'ОПЦИИ ТРЕКА';
            }

            // Load playlists into menu
            const itemsEl = document.getElementById('track-options-playlist-items');
            if (itemsEl && playbackState.track) {
                itemsEl.innerHTML = '<div class="context-menu-item" style="justify-content:center"><div class="spinner"></div></div>';
                try {
                    const pls = await api('get_playlists');
                    itemsEl.innerHTML = '';
                    if (pls && pls.length > 0) {
                        pls.forEach(pl => {
                            const btn = document.createElement('button');
                            btn.className = 'context-menu-item';
                            const plId = pl.id !== undefined ? pl.id : pl.ID;
                            btn.innerHTML = `<i data-lucide="list-music" style="width:14px;height:14px"></i> ${escapeHtml(pl.name)}`;
                            btn.addEventListener('click', async () => {
                                await api('add_to_playlist', plId, playbackState.track);
                                optMenu.classList.remove('visible');
                                const { showToast } = await import('./utils.js');
                                showToast(`Добавлено в «${pl.name}»`, 'success');
                            });
                            itemsEl.appendChild(btn);
                        });
                        renderIcons();
                    } else {
                        itemsEl.innerHTML = '<div class="context-menu-item" style="color:var(--text-dim)">Нет плейлистов</div>';
                    }
                } catch(e) {
                    itemsEl.innerHTML = '';
                }
            }
        });

        // Open player page
        document.getElementById('track-options-open-player')?.addEventListener('click', () => {
            optMenu.classList.remove('visible');
            if (window.showPage) window.showPage('player');
        });

        // Download track
        document.getElementById('track-options-download')?.addEventListener('click', () => {
            optMenu.classList.remove('visible');
            if (playbackState.track && window.NeDotify?.downloadTrack) {
                window.NeDotify.downloadTrack(playbackState.track);
            }
        });

        // Copy track title
        document.getElementById('track-options-copy')?.addEventListener('click', () => {
            optMenu.classList.remove('visible');
            if (playbackState.track) {
                const text = `${playbackState.track.title} — ${playbackState.track.artist || ''}`.trim();
                navigator.clipboard?.writeText(text).catch(() => {});
            }
        });

        // Close on outside click
        document.addEventListener('click', (e) => {
            if (!e.target.closest('#track-options-menu') && !e.target.closest('#pb-btn-options')) {
                optMenu.classList.remove('visible');
            }
        });
    }

    const pbArtist = document.getElementById('pb-artist');
    if (pbArtist) {
        pbArtist.classList.add('clickable-artist');
        pbArtist.addEventListener('click', (e) => {
            e.stopPropagation();
            if (playbackState.track && playbackState.track.artist && playbackState.track.artist !== 'Unknown' && playbackState.track.artist !== 'Выберите трек') {
                if (window.searchArtistProfile) {
                    window.searchArtistProfile(playbackState.track.artist, playbackState.track);
                } else if (window.NeDotify?.searchArtistProfile) {
                    window.NeDotify.searchArtistProfile(playbackState.track.artist, playbackState.track);
                }
            }
        });
    }

    const ppArtist = document.getElementById('pp-artist');
    if (ppArtist) {
        ppArtist.classList.add('clickable-artist');
        ppArtist.addEventListener('click', (e) => {
            e.stopPropagation();
            if (playbackState.track && playbackState.track.artist && playbackState.track.artist !== 'Unknown' && playbackState.track.artist !== 'Выберите трек') {
                if (window.searchArtistProfile) {
                    window.searchArtistProfile(playbackState.track.artist, playbackState.track);
                } else if (window.NeDotify?.searchArtistProfile) {
                    window.NeDotify.searchArtistProfile(playbackState.track.artist, playbackState.track);
                }
            }
        });
    }

    // Start smooth progress animation if playing
    if ((playbackState.status === 'playing') && !isPlayerUiHidden() && !animFrameId) {
        animFrameId = requestAnimationFrame(animateProgress);
    }
}

let lastProgressFrame = 0;

let progressThrottleMs = 33;

function isPlayerUiHidden() {
    return document.hidden || document.documentElement.classList.contains('window-hidden');
}

export function setUiFps(fps) {
    const clamped = Math.max(10, Math.min(60, parseInt(fps) || 30));
    progressThrottleMs = Math.round(1000 / clamped);
    document.documentElement.style.setProperty('--ui-fps', clamped);
    const transSec = (clamped / 60) * 0.2;
    document.documentElement.style.setProperty('--ui-transition-duration', `${transSec.toFixed(3)}s`);
}

function animateProgress(timestamp) {
    if (!(playbackState.status === 'playing')) {
        animFrameId = null;
        return;
    }
    if (isPlayerUiHidden()) {
        animFrameId = null;
        return;
    }
    animFrameId = requestAnimationFrame(animateProgress);

    // Throttle progress bar updates to target UI FPS
    if (timestamp - lastProgressFrame < progressThrottleMs) return;
    lastProgressFrame = timestamp;

    if (!isDraggingProgress && !isSeeking && activeAudio) {
        if (Number.isFinite(activeAudio.duration) && activeAudio.duration > 0) {
            playbackState.durationMs = Math.round(activeAudio.duration * 1000);
        }
        if (playbackState.durationMs > 0) {
            playbackState.positionMs = Math.round(activeAudio.currentTime * 1000);
            const pct = Math.max(0, Math.min(100, (playbackState.positionMs / playbackState.durationMs) * 100));
            if (!isFinite(pct)) return;

            paintPlaybackProgress();

            const remainingSec = (playbackState.durationMs - playbackState.positionMs) / 1000;
            checkPlaybackLookahead(remainingSec);
        }
    }
}

function checkPlaybackLookahead(remainingSec) {
    checkAutomaticTransition(remainingSec);
    // 1. Next Track Prefetching (Phase 4: at 20s remaining, single-flight pre-warm)
    if (remainingSec <= 20 && playbackState.durationMs > 25000 && !isPreloadingNextTrack) {
        const prefetchEnabled = (window.settings?.player?.player_prefetch ??
            (localStorage.getItem('nedotify_player_player_prefetch') !== 'false')) ||
            audioSetting('gapless_playback', false) || audioSetting('crossfade_enabled', false);
        if (prefetchEnabled && window.pywebview?.api?.get_next_track) {
            isPreloadingNextTrack = true;
            const capturedQueueVer = currentQueueVersion;
            const capturedGeneration = playbackGeneration;

            window.pywebview.api.get_next_track().then(nextTrack => {
                if (nextTrack && capturedQueueVer === currentQueueVersion && capturedGeneration === playbackGeneration) {
                    const trackKey = trackPlaybackKey(nextTrack);
                    if (trackKey && lastPrefetchedTrackId !== trackKey) {
                        lastPrefetchedTrackId = trackKey;
                        if (window.pywebview?.api?.prefetch_track) {
                            window.pywebview.api.prefetch_track(nextTrack);
                        }
                        if (nextTrack.stream_url) {
                            const inactiveAudio = activeAudio === audioA ? audioB : audioA;
                            preparedNext = {track: nextTrack, key: trackPlaybackKey(nextTrack), queueVersion: capturedQueueVer};
                            if (inactiveAudio && inactiveAudio.src !== nextTrack.stream_url) {
                                try {
                                    // Route through the HLS-aware loader, never raw .src.
                                    loadAudioSource(inactiveAudio, nextTrack.stream_url);
                                } catch (preErr) {
                                    destroyHls(inactiveAudio);
                                    inactiveAudio.src = "";
                                    inactiveAudio.removeAttribute("src");
                                    try { inactiveAudio.load(); } catch(e) {}
                                }
                            }
                        }
                    }
                }
            }).catch(err => {
                console.debug('Prefetch error:', err);
            }).finally(() => {
                setTimeout(() => { isPreloadingNextTrack = false; }, 8000);
            });
        }
    }


}

function checkAutomaticTransition(remainingSec) {
    if (sleepAtTrackEnd || !preparedNext || automaticTransition || outgoingAudio || !audioSetting('crossfade_enabled', false) ||
        preparedNext.queueVersion !== currentQueueVersion || !(playbackState.status === 'playing') || activeAudio.paused || isSeeking ||
        preparedNext.key === trackPlaybackKey(playbackState.track) || !window.pywebview?.api?.next_track) return;
    const duration = Math.max(0, Math.min(12, Number(audioSetting('crossfade_duration_sec', audioSetting('crossfade_duration', 3))) || 0));
    const inactive = activeAudio === audioA ? audioB : audioA;
    if (!duration || remainingSec <= 0 || remainingSec / currentPlaybackRate > duration || inactive.readyState < 3) return;
    const transition = {key: preparedNext.key, queueVersion: currentQueueVersion, duration};
    automaticTransition = transition;
    Promise.resolve(window.pywebview.api.next_track()).then(result => {
        if (!result && automaticTransition === transition) automaticTransition = null;
    }).catch(() => { if (automaticTransition === transition) automaticTransition = null; });
}

function syncPlayerVisibility() {
    if (isPlayerUiHidden() && animFrameId) {
        cancelAnimationFrame(animFrameId);
        animFrameId = null;
    } else if (!isPlayerUiHidden() && (playbackState.status === 'playing') && !animFrameId) {
        lastProgressFrame = 0;
        animFrameId = requestAnimationFrame(animateProgress);
    }
    if (isPlayerUiHidden()) {
        stopMiniEqLoop();
    } else if (playbackState.status === 'playing' && document.body.classList.contains('mini-player-active')) {
        startMiniEqLoop();
    }
}

document.addEventListener('visibilitychange', syncPlayerVisibility);
document.addEventListener('nedotify:window_visibility_changed', syncPlayerVisibility);

window.addEventListener('pagehide', () => {
    api('report_listening_state', playbackState.track?.listening_session, false);
    stopPlaybackForQueueEnd();
    stopOrbitGlowLoop();
    if (animFrameId) cancelAnimationFrame(animFrameId);
    animFrameId = null;
    for (const node of [srcA, srcB, preampNode, compressorNode, analyserNode, ...eqNodes]) {
        try { node?.disconnect(); } catch {}
    }
    srcA = null;
    srcB = null;
    preampNode = null;
    compressorNode = null;
    analyserNode = null;
    eqNodes = [];
    audioToolsRack?.destroy();
    audioToolsRack = null;
    mediaSourcesCreated = false;
    if (audioCtx) {
        if (audioCtx.state !== 'closed') {
            try { audioCtx.suspend(); } catch {}
        }
    }
});

// --- Event handlers called from events.js ---

let artworkRequestId = 0;

function updatePlayerArtwork(coverUrl) {
    const requestId = ++artworkRequestId;
    const root = document.documentElement;
    const glow = document.getElementById('player-bg-glow');
    glow?.parentElement.classList.toggle('has-player-artwork', !!coverUrl);
    for (const property of ['--player-art-color', '--ambient-glow', '--aura-orb-1', '--aura-orb-2']) {
        root.style.removeProperty(property);
    }
    if (glow) {
        glow.classList.add('player-bg-glow-downscaled');
        // Painting artwork does not require canvas access. Keep this fallback
        // even when a remote host does not allow CORS pixel sampling.
        glow.style.backgroundImage = coverUrl ? `url(${JSON.stringify(coverUrl)})` : '';
    }
    if (!coverUrl) return;

    // Do not sample the displayed <img>: cross-origin images can render while
    // tainting a canvas. A separate anonymous request leaves that image intact
    // when the host does not support CORS, and works for cached/local art too.
    const sample = new Image();
    sample.crossOrigin = 'anonymous';
    sample.onload = () => {
        if (requestId !== artworkRequestId) return;
        const color = extractDominantColor(sample);
        if (!color) return;
        const rgb = `rgb(${color.r}, ${color.g}, ${color.b})`;
        root.style.setProperty('--player-art-color', rgb);
        root.style.setProperty('--ambient-glow', rgb);
        root.style.setProperty('--aura-orb-1', rgb);
        root.style.setProperty('--aura-orb-2', `rgb(${Math.min(255, color.r + 40)}, ${Math.max(0, color.g - 25)}, ${Math.min(255, color.b + 50)})`);
        updateOrbitGlowPalette(color);
    };
    // A failed/stale sample must never clear the current CSS artwork.
    sample.onerror = () => {};
    sample.src = coverUrl;
}

export function onTrackChanged(track) {
    if (!track) return;
    const epoch = Number(track.playback_epoch);
    if (Number.isFinite(epoch) && epoch < backendPlaybackEpoch) return;
    cancelProgressDrag?.();
    isDraggingProgress = false;
    isSeeking = false;
    lastSeekTime = 0;
    if (seekTimeoutId) clearTimeout(seekTimeoutId);
    seekTimeoutId = null;
    if (Number.isFinite(epoch)) backendPlaybackEpoch = epoch;
    const sameTrack = trackPlaybackKey(playbackState.track) === trackPlaybackKey(track);
    const adoptingGapless = sameTrack && gaplessAdoptionKey === trackPlaybackKey(track);
    const preparedAudio = activeAudio === audioA ? audioB : audioA;
    const preparedStream = preparedNext?.key === trackPlaybackKey(track) &&
        preparedNext.queueVersion === currentQueueVersion && preparedAudio.readyState >= 3
        ? preparedNext.track.stream_url : null;
    gaplessAdoptionKey = null;
    if (!sameTrack) {
        playbackGeneration++;
        recoveryRequest = null;
        pendingResume = null;
        currentTrackRetries = 0;
        lastRetriedTrackId = null;
        lastPrefetchedTrackId = null;
        isPreloadingNextTrack = false;
        if (streamRetryTimer) { clearTimeout(streamRetryTimer); streamRetryTimer = null; }
    }
    const restorePositionMs = Math.max(0, Number(track.restore_position_sec) || 0) * 1000;
    if (restorePositionMs > 0) pendingResume = {key: trackPlaybackKey(track), ms: restorePositionMs};
    playbackState.track = track;
    updatePlayingTrackInDOM(playbackState.track);
    playbackState.positionMs = sameTrack ? Math.round((activeAudio.currentTime || 0) * 1000) : 0;
    const trackLufs = track.loudness_lufs !== undefined && track.loudness_lufs !== null ? track.loudness_lufs : track.lufs;
    if (audioSetting('volume_normalization', false) && Number.isFinite(Number(trackLufs)) && trackLufs != null) {
        currentReplayGain = Math.min(2.0, Math.max(0.1, Math.pow(10, (TARGET_LUFS - Number(trackLufs)) / 20)));
    } else {
        currentReplayGain = 1.0;
    }
    
    playbackState.durationMs = normalizeDurationMs(track.duration);
    
    paintPlaybackProgress();

    // The backend tags every track notification with its intended playback
    // state. Keep an initial restore paused across both metadata and resolved
    // stream notifications; an explicit user play always carries autoplay=true.
    const shouldAutoplay = track.autoplay === true || (track.autoplay !== false && !isInitialLoad);
    isInitialLoad = false;
    if (!shouldAutoplay) {
        if (track.stream_url) {
            if (!sameTrack || activeAudio._loadedSourceUrl !== normalizeAudioSourceUrl(track.stream_url)) {
                loadAudioSource(activeAudio, track.stream_url);
            }
            if (activeAudio.readyState >= 1) applyPendingResume(activeAudio);
        } else if (track.file_path) {
            if (!sameTrack || activeAudio._loadedSourceUrl !== normalizeAudioSourceUrl(track.file_path)) {
                loadAudioSource(activeAudio, track.file_path);
            }
            if (activeAudio.readyState >= 1) applyPendingResume(activeAudio);
        }
        activeAudio.pause();
        playbackState.status = 'paused';
        onStateChanged('paused');
        updateMediaSession(track);
        if ('mediaSession' in navigator) {
            navigator.mediaSession.playbackState = 'paused';
        }
    } else if (adoptingGapless) {
        updateMediaSession(track);
        api('report_state', 'playing', Math.round(activeAudio.currentTime * 1000), track.listening_session);
        api('report_listening_state', track.listening_session, !activeAudio.paused, false, activeAudio.duration, activeAudio.playbackRate);
    } else if (preparedStream) {
        playTrack(track, preparedStream);
    } else if (track.stream_url) {
        window._pendingResolveKey = null;
        // Avoid restarting playback when backend re-emits the same stream (e.g. double resolution notify)
        if (!sameTrack || activeAudio.ended || (activeAudio.paused && track.autoplay === true) || !activeAudio.src || activeAudio._loadedSourceUrl !== normalizeAudioSourceUrl(track.stream_url)) {
            playTrack(track, track.stream_url, {resumeMs: restorePositionMs});
        }
    } else if (track.file_path) {
        if (!sameTrack || activeAudio.ended || (activeAudio.paused && track.autoplay === true) || !activeAudio.src || activeAudio._loadedSourceUrl !== normalizeAudioSourceUrl(track.file_path)) {
            playTrack(track, track.file_path, {resumeMs: restorePositionMs});
        }
    } else if (track.source && track.source !== 'local' && track.source_id && window.pywebview?.api?.play_track) {
        // Resolution belongs to the backend. An unresolved notification is an
        // acknowledgement, never a command to start another resolution chain.
        // BUG-A1-007: the active element still holds the PREVIOUS track's
        // stream here; leaving it loaded made "Play" during the resolution
        // window restart the old song under the new title. Release it the
        // same way stopPlaybackForQueueEnd does.
        if (!sameTrack) {
            releaseAudio(activeAudio);
            if (preparedAudio && preparedAudio !== activeAudio) releaseAudio(preparedAudio);
        }
        activeAudio.pause();
        playbackState.status = 'paused';
        onStateChanged(shouldAutoplay ? 'loading' : 'paused');
    } else {
        activeAudio.pause();
        onStateChanged('stopped');
        showToast('Не удалось воспроизвести трек: источник недоступен', 'error');
    }
    
    const coverUrl = getCoverUrl(track);

    // Update bottom bar
    const pbTitleEl = document.getElementById('pb-title');
    if (pbTitleEl) {
        pbTitleEl.textContent = track?.title || 'Не играет';
        pbTitleEl.title = track?.title || '';
    }
    setElText('pb-artist', track?.artist || 'Выберите трек');
    const pbCover = document.getElementById('pb-cover');
    if (pbCover) {
        pbCover.onload = null;
        setElSrc('pb-cover', coverUrl);
    }
    updatePlayerArtwork(coverUrl);

    fetchAndRenderWaveform(track);

    // Update player page
    const hasArtist = track?.artist && track.artist !== 'Локальный файл' && track.artist !== '...' && track.artist !== 'Unknown Artist';
    const headerTitle = (track?.title || 'Трек не выбран') + (hasArtist ? ' — ' + track.artist : '');
    const headerEl = document.getElementById('pp-header-title');
    if (headerEl) {
        headerEl.title = headerTitle;
    }
    // Atomically reset progress bar and position tracking to prevent 100% / ended flicker
    playbackState.positionMs = sameTrack ? Math.round((activeAudio.currentTime || 0) * 1000) : 0;
    const normalizedDur = normalizeDurationMs(track?.duration);
    if (normalizedDur > 0) playbackState.durationMs = normalizedDur;
    paintPlaybackProgress();

    setElText('pp-title', track?.title || 'Трек не выбран');
    setElText('pp-artist', track?.artist || 'Выберите трек для воспроизведения');
    setElSrc('pp-cover', coverUrl);

    // Update Mini Player widget
    function setMarqueeText(elId, text) {
        const el = document.getElementById(elId);
        if (!el) return;
        el.title = text || '';
        let span = el.querySelector('.mp-marquee-span');
        if (!span) {
            span = document.createElement('span');
            span.className = 'mp-marquee-span';
            el.replaceChildren(span);
        }
        span.textContent = text || '';
        
        const updateMarquee = () => {
            if (span && span.scrollWidth > el.clientWidth && el.clientWidth > 0) {
                const dist = span.scrollWidth - el.clientWidth + 16;
                span.style.setProperty('--scroll-dist', `-${dist}px`);
                span.classList.add('animate-marquee');
            } else if (span) {
                span.classList.remove('animate-marquee');
            }
        };
        
        setTimeout(updateMarquee, 60);
        
        if (!el._resizeObserver) {
            el._resizeObserver = new ResizeObserver(() => {
                updateMarquee();
            });
            el._resizeObserver.observe(el);
        }
    }

    setMarqueeText('mp-title', track?.title || 'Трек не выбран');
    setMarqueeText('mp-artist', track?.artist || 'Выберите трек');
    setElSrc('mp-cover', coverUrl);

    updateLikeButtons();
    renderIcons();
}

export function stopPlaybackForQueueEnd() {
    fetchAndRenderWaveform(null);
    playbackGeneration++;
    recoveryRequest = null;
    automaticTransition = null;
    preparedNext = null;
    pendingResume = null;
    if (streamRetryTimer) { clearTimeout(streamRetryTimer); streamRetryTimer = null; }
    finishFade();
    releaseAudio(audioA);
    releaseAudio(audioB);
    // The backend reports the queue is exhausted, but that says nothing about the
    // audio element: pressing "next" on the last track leaves the current stream
    // playing while the UI already says "stopped". Release the socket the same
    // way the other teardown sites do (CODING_STANDARDS: src="" + load()).
    try {
        if (activeAudio && !activeAudio.paused) activeAudio.pause();
        destroyHls(activeAudio);
        activeAudio.removeAttribute('src');
        activeAudio.src = '';
        activeAudio.load();
    } catch (e) {
        console.debug('queue_ended teardown failed:', e);
    }
    window._pendingResolveKey = null;
}

// --- Mini player frequency bars: live low/mid/high spectrum -----------------
// The 7 bars in the mini player mirror the track's spectrum: bars 1-2 follow
// the low band, 3-5 the mid band, 6-7 the high band. Driven from the shared
// WebAudio analyser (getAudioFrequencyData); while there is no analyser data
// (or playback is stopped) the CSS idle/bounce animation stays in charge.
const MINI_EQ_BAR_COUNT = 7;
// Bin ranges over the analyser's 128 bins (~187 Hz per bin at 48 kHz), chosen
// logarithmically with overlap so neighboring bars move coherently.
const MINI_EQ_BIN_RANGES = [
    [1, 6],     // sub / low
    [3, 10],    // low
    [8, 17],    // low-mid
    [13, 26],   // mid
    [21, 38],   // mid
    [33, 64],   // high-mid
    [54, 112],  // high
];
// High frequencies carry far less energy than lows; boost so all three
// regions are visible at normal listening levels.
const MINI_EQ_BAND_GAINS = [1.0, 1.15, 1.3, 1.45, 1.6, 1.8, 2.1];
const miniEqData = new Uint8Array(128);
const miniEqLevels = new Float32Array(MINI_EQ_BAR_COUNT);
let miniEqRafId = null;

function updateMiniEqLevels() {
    if (!getAudioFrequencyData(miniEqData)) return false;
    for (let i = 0; i < MINI_EQ_BAR_COUNT; i++) {
        const [from, to] = MINI_EQ_BIN_RANGES[i];
        let sum = 0;
        for (let j = from; j <= to; j++) sum += miniEqData[j];
        let v = (sum / (to - from + 1)) / 255;
        v = Math.min(1, v * MINI_EQ_BAND_GAINS[i]);
        v = Math.pow(v, 0.8);
        // Fast attack, slow decay: peaks snap up, troughs glide down
        const prev = miniEqLevels[i];
        miniEqLevels[i] = v > prev ? v : Math.max(v, prev - 0.05);
    }
    return true;
}

function startMiniEqLoop() {
    if (miniEqRafId !== null) return;
    if (isPlayerUiHidden()) return;
    if (document.documentElement.classList.contains('perf-low')) return;
    const eqEl = document.querySelector('#mini-player-overlay .mp-eq');
    if (!eqEl || eqEl.querySelectorAll('span').length !== MINI_EQ_BAR_COUNT) return;

    const step = () => {
        miniEqRafId = null;
        const active = document.body.classList.contains('mini-player-active');
        if (!active || playbackState.status !== 'playing' || isPlayerUiHidden()) {
            stopMiniEqLoop();
            return;
        }
        if (updateMiniEqLevels()) {
            eqEl.classList.add('live');
            const bars = eqEl.querySelectorAll('span');
            bars.forEach((bar, i) => {
                bar.style.transform = `scaleY(${Math.max(0.12, miniEqLevels[i]).toFixed(3)})`;
            });
        }
        miniEqRafId = requestAnimationFrame(step);
    };
    miniEqRafId = requestAnimationFrame(step);
}

function stopMiniEqLoop() {
    if (miniEqRafId !== null) {
        cancelAnimationFrame(miniEqRafId);
        miniEqRafId = null;
    }
    const eqEl = document.querySelector('#mini-player-overlay .mp-eq');
    if (eqEl) {
        eqEl.classList.remove('live');
        eqEl.querySelectorAll('span').forEach((bar) => { bar.style.transform = ''; });
    }
}

export function onStateChanged(state) {
    playbackState.status = state;
    notifyLyricsClock();
    if ('mediaSession' in navigator) navigator.mediaSession.playbackState = (playbackState.status === 'playing') ? 'playing' : state === 'paused' ? 'paused' : 'none';

    syncOrbitGlowState();

    // Mini player: ring the visual state and run the frequency bars only
    // while playback is running and the mini player is actually on screen.
    const miniOverlay = document.getElementById('mini-player-overlay');
    if (miniOverlay) miniOverlay.classList.toggle('is-playing', playbackState.status === 'playing');
    // Animated Play/Pause morphing (circle <-> rounded rect) like Riff.
    const playing = playbackState.status === 'playing';
    for (const id of ['pb-btn-play', 'pp-btn-play', 'mp-btn-play']) {
        const button = document.getElementById(id);
        button?.classList.toggle('is-playing', playing);
        button?.setAttribute('aria-label', playing ? 'Пауза' : state === 'loading' ? 'Загрузка' : 'Воспроизведение');
        button?.setAttribute('aria-busy', String(state === 'loading'));
    }
    if (playbackState.status === 'playing' && document.body.classList.contains('mini-player-active')) {
        startMiniEqLoop();
    } else {
        stopMiniEqLoop();
    }

    document.dispatchEvent(new CustomEvent('nedotify:state_changed', { detail: state }));

    if ((playbackState.status === 'playing')) {
        if (!isPlayerUiHidden() && !animFrameId) {
            lastProgressFrame = performance.now();
            animFrameId = requestAnimationFrame(animateProgress);
        }
    } else {
        if (animFrameId) {
            cancelAnimationFrame(animFrameId);
            animFrameId = null;
        }
    }

    const packId = document.documentElement.getAttribute('data-icon-pack') || 'aura_neon';

    // Resolve play/pause icon name synchronously from cached map (set on first applyIconPack call)
    let playIconName, pauseIconName;
    try {
        const cachedMaps = window.__PACK_ICON_MAPS__;
        if (cachedMaps && cachedMaps[packId]) {
            playIconName = cachedMaps[packId].play || 'play';
            pauseIconName = cachedMaps[packId].pause || 'pause';
        }
    } catch(e) {}
    if (!playIconName) { playIconName = 'play'; pauseIconName = 'pause'; }

    const playIcon = (playbackState.status === 'playing') ? pauseIconName : playIconName;

    const coverSection = document.querySelector('.player-cover-section');
    
    const mpPlaySvg = (playbackState.status === 'playing')
        ? '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" stroke="none"><rect x="5" y="3" width="4" height="18" rx="1"></rect><rect x="15" y="3" width="4" height="18" rx="1"></rect></svg>'
        : '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" stroke="none"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>';

    if (state === 'loading') {
        if (coverSection) {
            coverSection.classList.add('loading');
            if (!coverSection.querySelector('.player-cover-loading')) {
                const overlay = document.createElement('div');
                overlay.className = 'player-cover-loading';
                overlay.innerHTML = '<div class="spinner"></div>';
                coverSection.appendChild(overlay);
            }
        }
        setElHtml('pb-btn-play', '<div class="spinner"></div>');
        setElHtml('pp-btn-play', '<div class="spinner"></div>');
        setElHtml('mp-btn-play', '<div class="spinner"></div>');
    } else {
        if (coverSection) coverSection.classList.remove('loading');
        const pbPlaySvg = (playbackState.status === 'playing')
            ? '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" stroke="none"><rect x="5" y="4" width="4" height="16" rx="1"></rect><rect x="15" y="4" width="4" height="16" rx="1"></rect></svg>'
            : '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" stroke="none"><polygon points="6 4 18 12 6 20 6 4"></polygon></svg>';

        const ppPlaySvg = (playbackState.status === 'playing')
            ? '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" stroke="none"><rect x="5" y="4" width="4" height="16" rx="1"></rect><rect x="14" y="4" width="4" height="16" rx="1"></rect></svg>'
            : '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" stroke="none"><polygon points="6 4 18 12 6 20 6 4"></polygon></svg>';

        setElHtml('pb-btn-play', pbPlaySvg);
        setElHtml('pp-btn-play', ppPlaySvg);
        setElHtml('mp-btn-play', mpPlaySvg);
        renderIcons();
    }
}

export function onPositionChanged(posMs, durationMs) {
    try {
        if (isSeeking || isDraggingProgress || performance.now() - lastSeekTime < 600) return;
        
        // If audio is actively playing in HTML5 Audio, let animateProgress handle smooth frame updates
        if ((playbackState.status === 'playing') && activeAudio && !activeAudio.paused) {
            return;
        }

        const mediaDuration = activeAudio?.duration;
        playbackState.durationMs = Number.isFinite(mediaDuration) && mediaDuration > 0
            ? Math.round(mediaDuration * 1000)
            : (Number.isFinite(durationMs) && durationMs > 0 ? durationMs : 0);
        playbackState.positionMs = Number.isFinite(posMs) ? Math.max(0, posMs) : 0;
        paintPlaybackProgress();
    } catch(e) {
        console.error("Player onPositionChanged Error:", e);
    }
}

export function applySettings(settings) {
    applyAudioSettings(settings.audio || {});
    const btnShuffle = document.getElementById('pb-btn-shuffle');
    const btnRepeat = document.getElementById('pb-btn-repeat');
    const ppShuffle = document.getElementById('pp-btn-shuffle');
    const ppRepeat = document.getElementById('pp-btn-repeat');
    const volFill = document.getElementById('pb-volume-fill');

    const session = settings.session || {};
    if (btnShuffle) btnShuffle.classList.toggle('active', !!session.shuffle);
    if (ppShuffle) ppShuffle.classList.toggle('active', !!session.shuffle);
    if (btnRepeat) btnRepeat.classList.toggle('active', (session.repeat || 'off') !== 'off');
    if (ppRepeat) ppRepeat.classList.toggle('active', (session.repeat || 'off') !== 'off');
    
    if (settings.audio?.volume !== undefined) {
        currentVolume = Math.max(0, Math.min(100, Number(settings.audio.volume) || 0));
        if (activeAudio) activeAudio.volume = playbackVolume();
    }
    
    if (volFill) volFill.style.width = `${currentVolume}%`;
    updateVolumeIcon(currentVolume, isMuted);
}

// --- Helpers ---

export function updateLikeButtons() {
    const isFav = playbackState.track?.is_favorite;
    ['pb-btn-like', 'pp-btn-like'].forEach(id => {
        const btn = document.getElementById(id);
        if (!btn) return;
        btn.classList.toggle('active', !!isFav);
        const size = id.startsWith('pp') ? '20px' : '14px';
        btn.innerHTML = `<i data-lucide="heart" style="width:${size};height:${size};${isFav ? 'fill:currentColor' : ''}"></i>`;
    });

    renderIcons();
}

window.addEventListener('nedotify:favorites_updated', (e) => {
    if (!playbackState.track) return;
    const favs = e.detail;
    if (Array.isArray(favs)) {
        const isFav = favs.some(f =>
            (f.id && playbackState.track.id && String(f.id) === String(playbackState.track.id)) ||
            (f.source_id && playbackState.track.source_id && f.source_id === playbackState.track.source_id) ||
            (f.title && f.artist && f.title === playbackState.track.title && f.artist === playbackState.track.artist)
        );
        if (playbackState.track.is_favorite !== isFav) {
            playbackState.track.is_favorite = isFav;
            updateLikeButtons();
        }
    }
});

window.addEventListener('nedotify:track_favorite_toggled', (e) => {
    const { track, is_favorite } = e.detail || {};
    if (!playbackState.track || !track) return;
    const matches = (track.id && playbackState.track.id && String(track.id) === String(playbackState.track.id)) ||
        (track.source_id && playbackState.track.source_id && track.source_id === playbackState.track.source_id) ||
        (track.title && track.artist && track.title === playbackState.track.title && track.artist === playbackState.track.artist);
    if (matches) {
        playbackState.track.is_favorite = is_favorite;
        updateLikeButtons();
    }
});

window.NeDotify = window.NeDotify || {};
window.NeDotify.updateLikeButtons = updateLikeButtons;

export async function downloadTrack(track) {
    if (!track) return {success: false, error: 'Трек не указан'};
    if (window.pywebview?.api?.download_track) {
        return window.pywebview.api.download_track(track);
    }
    return {success: false, error: 'Загрузка недоступна: нет соединения с приложением'};
}

function updateRepeatIcon(btn, mode) {
    if (!btn) return;
    if (mode === 'one') {
        btn.innerHTML = '<i data-lucide="repeat-1" style="width:16px;height:16px"></i>';
    } else {
        btn.innerHTML = '<i data-lucide="repeat" style="width:16px;height:16px"></i>';
    }
    renderIcons();
}

export function applyMuteState(muted) {
    isMuted = !!muted;
    audioA.muted = isMuted;
    audioB.muted = isMuted;
    if (activeAudio) activeAudio.volume = isMuted ? 0 : Math.min(1.0, Math.max(0.0, (currentVolume / 100) * currentReplayGain));
    const vfill = document.getElementById('pb-volume-fill');
    if (vfill) vfill.style.opacity = isMuted ? '0.3' : '1';
    const mpVfill = document.getElementById('mp-volume-fill');
    if (mpVfill) mpVfill.style.opacity = isMuted ? '0.3' : '1';
    updateVolumeIcon(currentVolume, isMuted);
}

function updateVolumeIcon(volume, isMuted) {
    let icon = 'volume-2';
    if (isMuted || volume === 0) icon = 'volume-x';
    else if (volume <= 50) icon = 'volume-1';

    const btn = document.getElementById('pb-volume-btn');
    if (btn) btn.innerHTML = `<i data-lucide="${icon}" style="width:16px;height:16px"></i>`;

    // Mini player mirrors the bottom bar: same icon + fill width + aria value
    const mpBtn = document.getElementById('mp-volume-btn');
    if (mpBtn) {
        mpBtn.classList.toggle('active', !!(isMuted || volume === 0));
        mpBtn.innerHTML = `<i data-lucide="${icon}" style="width:15px;height:15px"></i>`;
    }
    const mpFill = document.getElementById('mp-volume-fill');
    if (mpFill) mpFill.style.width = `${Math.max(0, Math.min(100, volume))}%`;
    const mpTrack = document.getElementById('mp-volume-track');
    if (mpTrack) mpTrack.setAttribute('aria-valuenow', String(Math.round(volume)));

    renderIcons();
}

// Every surface paints the same media facts, including the drag preview. This
// function adds no clock: timeupdate and the existing animation loop drive it.
function paintPlaybackProgress(position = playbackState.positionMs) {
    const duration = Number.isFinite(playbackState.durationMs) && playbackState.durationMs > 0 ? playbackState.durationMs : 0;
    const fraction = duration ? Math.max(0, Math.min(1, position / duration)) : 0;
    const current = formatTime((duration ? fraction * duration : Math.max(0, position || 0)) / 1000);
    const total = formatTime(duration / 1000);
    for (const prefix of ['pb', 'pp', 'mp']) {
        const fill = document.getElementById(`${prefix}-progress-fill`);
        if (fill) fill.style.transform = `scaleX(${fraction})`;
        const track = document.getElementById(`${prefix}-progress-track`);
        if (track) {
            track.style.setProperty('--seek-progress', `${fraction * 100}%`);
            for (const [name, value] of [['aria-valuenow', (fraction * 100).toFixed(1)],
                ['aria-valuetext', `${current} / ${total}`], ['aria-disabled', String(!duration)]]) {
                if (track.getAttribute(name) !== value) track.setAttribute(name, value);
            }
        }
        setElText(`${prefix}-time-current`, current);
        setElText(`${prefix}-time-total`, total);
    }
    const panel = document.getElementById('pb-panel-fill');
    if (panel) panel.style.clipPath = `inset(0 ${100 - fraction * 100}% 0 0)`;
    paintProgressWave(fraction, position);
    renderWaveforms(fraction);
}

// Adapted from Riff v44 src/renderer/app.js scrubber (MIT, rootscripts 2026).
// The decorative sine is a seek indicator, independent of decoded audio peaks.
// Keep its 42px wavelength and rounded stroke without adding an animation clock.
function paintProgressWave(fraction, position) {
    if (document.documentElement.dataset?.progressStyle !== 'solid') return;
    const track = document.getElementById('pb-progress-track');
    if (!track) return;
    let canvas = track.querySelector('.progress-wave');
    if (!canvas) {
        canvas = document.createElement('canvas');
        canvas.className = 'progress-wave';
        canvas.setAttribute('aria-hidden', 'true');
        track.append(canvas);
    }
    const width = track.getBoundingClientRect().width, height = 12;
    if (!width) return;
    const dpr = window.devicePixelRatio || 1;
    const pixelWidth = Math.round(width * dpr), pixelHeight = Math.round(height * dpr);
    if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
        canvas.width = pixelWidth; canvas.height = pixelHeight;
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const styles = getComputedStyle(document.documentElement);
    ctx.strokeStyle = canvas.id === 'pp-waveform-canvas' ? '#eeeef2' :
        styles.getPropertyValue('--player-progress-color').trim() || getWaveColor();
    ctx.globalAlpha = getProgressOpacity();
    ctx.lineWidth = 2.5; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    const end = Math.max(0, Math.min(width, width * fraction));
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const phase = reduced ? 0 : (position || 0) / 1000 * 3.5;
    if (end > 0) {
        ctx.beginPath();
        for (let x = 0; x <= end; x += 2) {
            const y = 6 + Math.sin(phase - (end - x) * 2 * Math.PI / 42) * 3;
            if (!x) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.lineTo(end, 6 + Math.sin(phase) * 3);
        ctx.stroke();
    }
    ctx.globalAlpha *= .24;
    if (end < width) {
        ctx.beginPath(); ctx.moveTo(end, 6); ctx.lineTo(width, 6); ctx.stroke();
    }
}

function progressDragHandlers() {
    return {
        onDrag(pct) {
            isDraggingProgress = true;
            paintPlaybackProgress(pct * playbackState.durationMs);
        },
        onRelease(pct) {
            isDraggingProgress = false;
            seekTo(Math.round(pct * playbackState.durationMs));
        },
        onCancel() {
            isDraggingProgress = false;
            paintPlaybackProgress();
        }
    };
}

function setupDragBar(trackId, { onDrag, onRelease, onCancel }, {pointerEnabled = () => true, feedbackId = trackId, keyboard = true} = {}) {
    const track = document.getElementById(trackId);
    if (!track) return;
    const feedback = document.getElementById(feedbackId) || track;
    const isProgress = !trackId.includes('volume');
    const excluded = 'button, a, input, select, textarea, [contenteditable="true"], [role="button"], .clickable-artist' + (isProgress ? ', .volume-track, .volume-wrap' : '');
    const canSeek = () => !isProgress || (Number.isFinite(playbackState.durationMs) && playbackState.durationMs > 0);
    const preview = (pct) => {
        if (!isProgress) return;
        feedback.setAttribute('data-seek-preview', formatTime(pct * playbackState.durationMs / 1000));
        feedback.style.setProperty('--seek-pointer', `${Math.max(0, Math.min(1, pct)) * 100}%`);
    };
    track.addEventListener('pointermove', event => {
        if (pointerEnabled() && canSeek() && !event.target.closest(excluded)) preview(getPct(event));
    });
    track.addEventListener('pointerleave', () => { if (!isDraggingProgress) feedback.removeAttribute('data-seek-preview'); });

    track.addEventListener('keydown', (event) => {
        if (!keyboard) return;
        // Modified arrows belong to the application's existing hotkeys.
        if (event.ctrlKey || event.metaKey || event.altKey) return;
        if (!canSeek()) return;
        const step = trackId.includes('volume') ? .05 : (playbackState.durationMs > 0 ? 5000 / playbackState.durationMs : 0);
        let pct = Number(track.getAttribute('aria-valuenow') || 0) / 100;
        if (event.key === 'Home') pct = 0;
        else if (event.key === 'End') pct = 1;
        else if (['ArrowRight', 'ArrowUp'].includes(event.key)) pct += step;
        else if (['ArrowLeft', 'ArrowDown'].includes(event.key)) pct -= step;
        else return;
        event.preventDefault();
        event.stopPropagation();
        pct = Math.max(0, Math.min(1, pct));
        onDrag(pct);
        onRelease(pct);
    });

    function getPct(e) {
        const rect = track.getBoundingClientRect();
        if (rect.width <= 0) return 0;
        return Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    }

    track.addEventListener('pointerdown', (event) => {
        if (!pointerEnabled() || !canSeek()) return;
        if (event.button !== 0 && event.pointerType !== 'touch') return;
        if (event.target.closest(excluded)) return;
        event.preventDefault();
        event.stopPropagation?.();
        if (isProgress) cancelProgressDrag?.();
        try { feedback.focus({ preventScroll: true }); } catch (error) { feedback.focus(); }

        const pointerId = event.pointerId;
        try { track.setPointerCapture(pointerId); } catch (error) {}
        let lastPct = getPct(event);
        const dragTrack = playbackState.track;
        preview(lastPct);
        feedback.setAttribute('data-seeking', 'true');
        onDrag(lastPct);

        const onPointerMove = (moveEvent) => {
            if (moveEvent.pointerId !== pointerId) return;
            if (isProgress && playbackState.track !== dragTrack) { cancel(); return; }
            lastPct = getPct(moveEvent);
            preview(lastPct);
            onDrag(lastPct);
        };
        let finished = false;
        const cleanup = () => {
            finished = true;
            document.removeEventListener('pointermove', onPointerMove);
            document.removeEventListener('pointerup', finish);
            document.removeEventListener('pointercancel', cancel);
            track.removeEventListener?.('lostpointercapture', cancel);
            window.removeEventListener?.('blur', cancel);
            feedback.removeAttribute('data-seeking');
            feedback.removeAttribute('data-seek-preview');
            if (isProgress) cancelProgressDrag = null;
            try {
                if (track.hasPointerCapture(pointerId)) track.releasePointerCapture(pointerId);
            } catch (error) {}
        };
        const cancel = (event) => {
            if (finished || (event?.pointerId != null && event.pointerId !== pointerId)) return;
            cleanup();
            onCancel?.();
        };
        const finish = (upEvent) => {
            if (finished || upEvent.pointerId !== pointerId) return;
            if (isProgress && playbackState.track !== dragTrack) { cancel(); return; }
            lastPct = getPct(upEvent);
            cleanup();
            onRelease(lastPct);
        };

        document.addEventListener('pointermove', onPointerMove);
        document.addEventListener('pointerup', finish);
        document.addEventListener('pointercancel', cancel);
        track.addEventListener('lostpointercapture', cancel);
        window.addEventListener?.('blur', cancel);
        if (isProgress) cancelProgressDrag = cancel;
    });
}

function api(method, ...args) {
    const bridge = window.pywebview?.api;
    if (typeof bridge?.[method] !== 'function') return Promise.resolve(null);
    try {
        return Promise.resolve(bridge[method](...args)).catch(error => {
            console.warn(`Player bridge call failed: ${method}`, error);
            return null;
        });
    } catch (error) {
        console.warn(`Player bridge call failed: ${method}`, error);
        return Promise.resolve(null);
    }
}

export function setProgressFill(id, val) {
    const el = document.getElementById(id);
    if (!el) return;
    const pct = typeof val === 'number' ? val : parseFloat(val);
    if (!isNaN(pct)) {
        el.style.transform = `scaleX(${Math.max(0, Math.min(100, pct)) / 100})`;
    }
}

export function setVolumeFill(id, val) {
    const el = document.getElementById(id);
    if (!el) return;
    const pct = typeof val === 'number' ? val : parseFloat(val);
    if (!isNaN(pct)) {
        el.style.width = `${pct}%`;
    }
}

function setEl(id, prop, val) {
    const el = document.getElementById(id);
    if (!el) return;
    if (prop === 'width' && typeof val === 'string' && val.endsWith('%') && id.includes('progress-fill')) {
        setProgressFill(id, parseFloat(val));
        return;
    }
    el.style[prop] = val;
}
function setElText(id, text) {
    const el = document.getElementById(id);
    if (el && el.textContent !== text) el.textContent = text;
}
function setElHtml(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
}
function setElSrc(id, src) {
    const el = document.getElementById(id);
    if (!el) return;
    if (src && typeof src === 'string' && src.trim() !== '') {
        const sameSrc = el.getAttribute('src') === src;
        el.style.display = 'block';
        // BUG-U3-013: drop the previous image BEFORE the new URL starts
        // loading. Assigning el.src alone kept the old cover decoded and
        // visible while the new one travelled the network, so all three
        // players showed the previous artwork under the new title. The
        // caller's onload (colour extraction on pb-cover) is preserved and
        // runs after the new image is actually decoded.
        const callerOnload = el.onload;
        if (!sameSrc) {
            el.removeAttribute('src');
            el.style.opacity = '0';
            el.onload = () => {
                el.style.opacity = '';
                if (typeof callerOnload === 'function') callerOnload.call(el);
            };
        }
        el.onerror = () => {
            el.onerror = null;
            el.style.opacity = '';
            if (el.src && el.src.includes('maxresdefault.jpg')) {
                el.onerror = () => { el.onerror = null; el.style.display = 'none'; el.style.opacity = ''; };
                el.src = el.src.replace('maxresdefault.jpg', 'hqdefault.jpg');
            } else if (el.src && el.src.includes('sddefault.jpg')) {
                el.onerror = () => { el.onerror = null; el.style.display = 'none'; el.style.opacity = ''; };
                el.src = el.src.replace('sddefault.jpg', 'hqdefault.jpg');
            } else {
                el.style.display = 'none';
            }
        };
        el.src = src;
    } else {
        el.onerror = null;
        el.style.opacity = '';
        el.style.display = 'none';
    }
}

// --- Waveform Scrubber Engine ---
let currentWaveformData = null;
let isWaveformScrubberActive = false;
let waveformRequestId = 0;
let waveformAbortController = null;

// C-5: waveform render caches (color, element size) + skip-redraw helpers
let waveColorCache = { color: null, theme: null, custom: null };

function getWaveColor() {
    const root = document.documentElement;
    const theme = root.getAttribute('data-theme');
    const custom = root.style.getPropertyValue('--player-progress-color').trim();
    if (waveColorCache.color === null || waveColorCache.theme !== theme || waveColorCache.custom !== custom) {
        waveColorCache.color = custom || getComputedStyle(root).getPropertyValue('--primary').trim() || '#10b981';
        waveColorCache.theme = theme;
        waveColorCache.custom = custom;
    }
    return waveColorCache.color;
}

function getProgressOpacity() {
    const opacity = Number.parseFloat(document.documentElement.style.getPropertyValue('--player-progress-opacity'));
    return Number.isFinite(opacity) ? Math.max(0, Math.min(1, opacity)) : 0.82;
}

// Invalidate the color cache when theme or custom accent changes
if (typeof MutationObserver !== 'undefined') {
    new MutationObserver(() => { waveColorCache.color = null; })
        .observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'style'] });
}

// Invalidate cached element sizes on window resize
window.addEventListener('resize', () => {
    document.querySelectorAll('.waveform-canvas').forEach(cv => {
        cv._wfW = undefined;
        cv._wfH = undefined;
        cv._wfBw = undefined;
        cv._wfBh = undefined;
    });
});

// A drag between a 100% and a 150% monitor changes devicePixelRatio without a
// resize event. Drop the cached backing-store size too, so the next render
// re-rasterises the waveform at the new scale instead of leaving it soft.
registerCanvasDprListener(() => {
    document.querySelectorAll('.waveform-canvas').forEach(cv => {
        cv._wfBw = undefined;
        cv._wfBh = undefined;
        cv._wfProgressPixel = undefined;
        cv._wfStatic = false;
    });
    try { renderWaveforms(playbackState.positionMs / (playbackState.durationMs || 1)); } catch (e) {}
});

export async function fetchAndRenderWaveform(track) {
    const requestId = ++waveformRequestId;
    waveformAbortController?.abort();
    const controller = typeof AbortController === 'function' ? new AbortController() : null;
    waveformAbortController = controller;
    currentWaveformData = null;
    isWaveformScrubberActive = false;
    const root = document.documentElement;
    const style = root.dataset?.progressStyle || 'bars';
    const isWaveformMode = style === 'bars' || style === 'wave';
    const canvases = ['pb-waveform-canvas', 'pp-waveform-canvas', 'mp-waveform-canvas']
        .map(id => document.getElementById(id)).filter(Boolean);

    // Until actual audio peaks arrive, show an ordinary seekable progress line.
    // A title-derived envelope looks convincing but says nothing about the audio.
    root.classList.toggle('waveform-unavailable', isWaveformMode);
    canvases.forEach(canvas => {
        canvas.classList.add('hidden');
        canvas.getContext?.('2d')?.clearRect(0, 0, canvas.width, canvas.height);
        canvas._wfW = canvas._wfH = canvas._wfBw = canvas._wfBh = undefined;
        canvas._wfProgressPixel = undefined;
        canvas._wfPeaks = null;
        canvas._wfGeometry = null;
        canvas._wfStatic = false;
    });
    if (!isWaveformMode || !track) return;

    try {
        let peaks = null;
        try {
            if (window.pywebview?.api?.get_waveform) peaks = await window.pywebview.api.get_waveform(track);
        } catch (_) { /* A provider waveform failure must not block audio decoding. */ }
        if (requestId !== waveformRequestId) return;
        const valid = values => Array.isArray(values) && values.length > 0 && values.every(Number.isFinite);
        if (!valid(peaks)) {
            const url = track.stream_url || (playbackState.track === track
                ? activeAudio._loadedSourceUrl || activeAudio.currentSrc || activeAudio.src : '');
            peaks = await fetchRealPeaks(track, { signal: controller?.signal, url });
            if (requestId !== waveformRequestId) return;
        }
        if (!valid(peaks)) return;
        currentWaveformData = peaks;
        isWaveformScrubberActive = true;
        root.classList.remove('waveform-unavailable');
        canvases.forEach(canvas => canvas.classList.remove('hidden'));
        renderWaveforms(playbackState.positionMs / (playbackState.durationMs || 1));
    } catch (_) {
        // Keep the progress line when the codec or stream cannot be analyzed.
    } finally {
        if (waveformAbortController === controller) waveformAbortController = null;
    }
}

export function renderWaveforms(progressPct = 0) {
    if (!isWaveformScrubberActive || !currentWaveformData || isPlayerUiHidden()) return;

    ['pb-waveform-canvas', 'pp-waveform-canvas', 'mp-waveform-canvas'].forEach(id => {
        const canvas = document.getElementById(id);
        if (!canvas) return;
        const visible = !canvas.classList.contains('hidden') && (typeof canvas.checkVisibility === 'function'
            // A page can start its entrance animation at opacity zero. Paint
            // its canvas now so paused playback appears as the page fades in.
            ? canvas.checkVisibility({ checkVisibilityCSS: true })
            : canvas.getClientRects().length > 0 && getComputedStyle(canvas).visibility !== 'hidden');
        if (!visible) {
            canvas._wfWasVisible = false;
            return;
        }
        if (canvas._wfWasVisible === false) {
            canvas._wfW = canvas._wfH = canvas._wfProgressPixel = undefined;
        }
        canvas._wfWasVisible = true;
        drawWaveformToCanvas(canvas, currentWaveformData, progressPct);
    });
}

// Paused playback has no animation loop to repaint a newly shown canvas.
function redrawVisibleWaveforms() {
    renderWaveforms(playbackState.positionMs / (playbackState.durationMs || 1));
}
window.addEventListener('nedotify:page_changed', redrawVisibleWaveforms);
window.addEventListener('nedotify:mini_player_toggled', () => requestThrottledWaveformRender());
document.addEventListener('visibilitychange', redrawVisibleWaveforms);
document.addEventListener('nedotify:window_visibility_changed', redrawVisibleWaveforms);
if (typeof MutationObserver === 'function') {
    // Also covers static-preview mini mode and backend class updates.
    const visibilityObserver = new MutationObserver(redrawVisibleWaveforms);
    visibilityObserver.observe(document.body, { attributes: true, attributeFilter: ['class'] });
    visibilityObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
}

if (typeof ResizeObserver === 'function') {
    const waveformResizeObserver = new ResizeObserver(entries => {
        let resized = false;
        entries.forEach(({ target: canvas }) => {
            const width = canvas.clientWidth;
            const height = canvas.clientHeight;
            if (!width || !height || (canvas._wfW === width && canvas._wfH === height)) return;
            canvas._wfW = width;
            canvas._wfH = height;
            canvas._wfBw = undefined;
            canvas._wfBh = undefined;
            canvas._wfProgressPixel = undefined;
            canvas._wfStatic = false;
            resized = true;
        });
        if (resized) renderWaveforms(playbackState.positionMs / (playbackState.durationMs || 1));
    });
    document.querySelectorAll('.waveform-canvas').forEach(canvas => waveformResizeObserver.observe(canvas));
}

// Geometry is independent of playback position and paint colour. Build it once
// per envelope/size/style/hover change, then reuse it for both alpha passes.
function buildWaveformPath(w, h, peaks, style, hoverX) {
    const path = new Path2D();
    const isHoverActive = hoverX >= 0;
    const numBars = Math.max(1, Math.min(640, Math.floor(w / 5)));
    if (style === 'wave') {
        const sampleCount = Math.max(2, Math.min(640, Math.floor(w / 3)));
        const peakAt = (normX) => {
            const position = Math.max(0, Math.min(peaks.length - 1, normX * (peaks.length - 1)));
            const lower = Math.floor(position);
            const upper = Math.min(peaks.length - 1, lower + 1);
            return (peaks[lower] ?? 0) + ((peaks[upper] ?? 0) - (peaks[lower] ?? 0)) * (position - lower);
        };
        const traceEnvelope = () => {
            for (let i = 0; i < sampleCount; i++) {
                const normX = i / (sampleCount - 1);
                const amp = Math.max(0, Math.min(1, peakAt(normX)));
                const dist = isHoverActive ? Math.abs(normX - hoverX) : 1;
                const magneticAmp = dist < 0.15 ? 1 + 0.45 * Math.cos((dist / 0.15) * (Math.PI / 2)) : 1;
                const halfHeight = Math.min(h / 2 - 1, Math.max(1, amp * magneticAmp * (h / 2 - 2)));
                const x = normX * w;
                const y = (h / 2) - halfHeight;
                if (i === 0) path.moveTo(x, y);
                else path.lineTo(x, y);
            }
            for (let i = sampleCount - 1; i >= 0; i--) {
                const normX = i / (sampleCount - 1);
                const amp = Math.max(0, Math.min(1, peakAt(normX)));
                const dist = isHoverActive ? Math.abs(normX - hoverX) : 1;
                const magneticAmp = dist < 0.15 ? 1 + 0.45 * Math.cos((dist / 0.15) * (Math.PI / 2)) : 1;
                const halfHeight = Math.min(h / 2 - 1, Math.max(1, amp * magneticAmp * (h / 2 - 2)));
                path.lineTo(normX * w, (h / 2) + halfHeight);
            }
            path.closePath();
        };

        traceEnvelope();
        return path;
    }
    const step = w / numBars;
    const barWidth = Math.max(1, Math.min(4, step * 0.68));
    const peakAt = (normX) => {
        const position = Math.max(0, Math.min(peaks.length - 1, normX * (peaks.length - 1)));
        const lower = Math.floor(position);
        const upper = Math.min(peaks.length - 1, lower + 1);
        const lowerPeak = peaks[lower] ?? 0;
        return lowerPeak + ((peaks[upper] ?? 0) - lowerPeak) * (position - lower);
    };
    const traceBars = () => {

        for (let i = 0; i < numBars; i++) {
            const normBarX = (i + 0.5) / numBars;
            const amp = Math.max(0, Math.min(1, peakAt(normBarX)));
            let magneticAmp = 1;
            if (isHoverActive) {
                const dist = Math.abs(normBarX - hoverX);
                if (dist < 0.15) magneticAmp = 1 + 0.45 * Math.cos((dist / 0.15) * (Math.PI / 2));
            }

            const barHeight = Math.min(h - 2, Math.max(3, amp * magneticAmp * (h - 4)));
            const x = i * step + (step - barWidth) / 2;
            const y = (h - barHeight) / 2;
            if (path.roundRect) path.roundRect(x, y, barWidth, barHeight, Math.min(2, barWidth / 2));
            else path.rect(x, y, barWidth, barHeight);
        }

    };

    traceBars();
    return path;
}

function drawWaveformToCanvas(canvas, peaks, progressPct) {
    if (!canvas || !peaks || peaks.length === 0) return;
    const ctx = canvas.getContext('2d');

    // C-5: cached element size (invalidated on window resize / track change)
    // These are CSS pixels; the backing store is derived from them below.
    const parent = canvas.parentElement;
    let w = canvas._wfW;
    if (w === undefined || w === 0) {
        w = canvas._wfW = canvas.clientWidth || parent.clientWidth || 300;
    }
    let h = canvas._wfH;
    if (h === undefined || h === 0) {
        h = canvas._wfH = canvas.clientHeight || parent.clientHeight || 20;
    }

    // Backing store follows devicePixelRatio; every drawing call below keeps
    // using the CSS-pixel w/h, and the context carries the dpr scale. At
    // dpr === 1 the backing store is exactly w x h, as it was before.
    const sized = sizeCanvasForDpr(canvas, ctx, w, h);
    if (canvas._wfBw !== sized.bw || canvas._wfBh !== sized.bh) {
        canvas._wfBw = sized.bw;
        canvas._wfBh = sized.bh;
        canvas._wfProgressPixel = undefined;
        canvas._wfStatic = false;
    }

    const normalizedProgress = Math.max(0, Math.min(1, Number(progressPct) || 0));
    const dpr = window.devicePixelRatio || 1;
    const progressPixel = Math.round(normalizedProgress * w * dpr);
    const hoverPixel = !document.documentElement.classList.contains('perf-low') && hoveredWaveformNormX >= 0
        ? Math.round(hoveredWaveformNormX * w * dpr) : -1;
    const style = document.documentElement.dataset?.progressStyle || 'bars';
    const color = canvas.id === 'pp-waveform-canvas' ? '#eeeef2' : getWaveColor();
    const opacity = getProgressOpacity();

    // Redraw when the played edge advances by a physical pixel, or while the
    // pointer is moving the magnetic hover effect.
    const isHoverActive = hoverPixel >= 0;
    if (canvas._wfProgressPixel === progressPixel && canvas._wfHoverPixel === hoverPixel && canvas._wfPeaks === peaks
        && canvas._wfStyle === style && canvas._wfColor === color && canvas._wfOpacity === opacity) return;

    canvas._wfPeaks = peaks;
    canvas._wfProgressPixel = progressPixel;
    canvas._wfHoverPixel = hoverPixel;
    canvas._wfStyle = style;
    canvas._wfColor = color;
    canvas._wfOpacity = opacity;

    ctx.clearRect(0, 0, w, h);

    const hoverX = isHoverActive ? hoveredWaveformNormX : -1;
    const geometry = canvas._wfGeometry;
    if (!geometry || geometry.peaks !== peaks || geometry.w !== w || geometry.h !== h ||
        geometry.style !== style || geometry.hoverX !== hoverX) {
        canvas._wfGeometry = { peaks, w, h, style, hoverX,
            path: buildWaveformPath(w, h, peaks, style, hoverX) };
    }
    const path = canvas._wfGeometry.path;
    ctx.fillStyle = color;
    ctx.globalAlpha = opacity * 0.18;
    ctx.fill(path);
    if (normalizedProgress > 0) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(0, 0, w * normalizedProgress, h);
        ctx.clip();
        ctx.globalAlpha = opacity;
        ctx.fill(path);
        ctx.restore();
    }
    ctx.globalAlpha = 1;
}

document.addEventListener('nedotify:slider_type_changed', () => {
    paintPlaybackProgress();
    fetchAndRenderWaveform(playbackState.track);
});

document.addEventListener('nedotify:progress_appearance_changed', () => {
    paintPlaybackProgress();
    waveColorCache.color = null;
    document.querySelectorAll('.waveform-canvas').forEach(canvas => {
        canvas._wfProgressPixel = undefined;
        canvas._wfStatic = false;
    });
    try { renderWaveforms(playbackState.positionMs / (playbackState.durationMs || 1)); } catch (e) {}
});

// ==========================================================================
// Reactive Orbit Glow & Magnetic Waveform Capsule System
// ==========================================================================
let orbitGlowRafId = null;
let orbitGlowDominantColor = { r: 244, g: 63, b: 94 }; // Cyber Blossom default
let isOrbitGlowRunning = false;
let hoveredWaveformNormX = -1; // -1 when not hovered

export function updateOrbitGlowPalette(color) {
    if (!color) return;
    orbitGlowDominantColor = color;
    const secColor = {
        r: Math.min(255, color.r + 35),
        g: Math.max(0, color.g - 20),
        b: Math.min(255, color.b + 40)
    };
    
    document.documentElement.style.setProperty('--orbit-glow-1', `rgba(${color.r}, ${color.g}, ${color.b}, 0.25)`);
    document.documentElement.style.setProperty('--orbit-glow-2', `rgba(${secColor.r}, ${secColor.g}, ${secColor.b}, 0.18)`);
    document.documentElement.style.setProperty('--orbit-glow-border', `rgba(${color.r}, ${color.g}, ${color.b}, 0.35)`);
    
    syncOrbitGlowState();
}

export function syncOrbitGlowState() {
    const isPerfLow = document.documentElement.classList.contains('perf-low') || 
                      document.documentElement.classList.contains('battery-saver-active') ||
                      document.documentElement.dataset?.uiStyle === 'macos';
    const isPerfMed = document.documentElement.classList.contains('perf-medium');
    const isWindowFocused = !isPlayerUiHidden() && !document.body.classList.contains('unfocused-animations-disabled');
    
    // Low / Battery Saver: completely kill rAF loop, static border only (0% GPU)
    if (isPerfLow) {
        stopOrbitGlowLoop();
        document.documentElement.classList.add('orbit-glow-low');
        document.documentElement.classList.remove('orbit-glow-high', 'orbit-glow-med');
        return;
    }
    
    // Medium: static smooth dual-color gradient glow derived from cover, NO rAF loop (0% GPU)
    if (isPerfMed) {
        stopOrbitGlowLoop();
        document.documentElement.classList.add('orbit-glow-med');
        document.documentElement.classList.remove('orbit-glow-high', 'orbit-glow-low');
        return;
    }
    
    // High: active Web Audio bass FFT loop only when playing & focused
    document.documentElement.classList.add('orbit-glow-high');
    document.documentElement.classList.remove('orbit-glow-med', 'orbit-glow-low');
    
    if ((playbackState.status === 'playing') && isWindowFocused && !document.body.classList.contains('mini-player-active')) {
        startOrbitGlowLoop();
    } else {
        stopOrbitGlowLoop();
    }
}

window.addEventListener('nedotify:appearance_changed', syncOrbitGlowState);
window.addEventListener('nedotify:mini_player_toggled', syncOrbitGlowState);

function startOrbitGlowLoop() {
    if (isOrbitGlowRunning) return;
    isOrbitGlowRunning = true;
    
    const pb = document.getElementById('player-bar');
    const ppCard = document.querySelector('.player-glass-card');
    let lastTime = performance.now();
    const dataArray = new Uint8Array(16);
    let lastOpacity = '';
    let lastScale = '';
    
    function loop(now) {
        if (!isOrbitGlowRunning) return;
        
        // 30 FPS throttle
        if (now - lastTime >= 33) {
            lastTime = now;
            let bassFactor = 0.5;
            
            if (analyserNode) {
                try {
                    analyserNode.getByteFrequencyData(dataArray);
                    const bassSum = dataArray[0] + dataArray[1] + dataArray[2] + dataArray[3];
                    bassFactor = bassSum / 1020; // 0.0 to 1.0
                } catch(e) {}
            }
            
            const opacity = (0.25 + (bassFactor * 0.55)).toFixed(2);
            const scale = (1.0 + (bassFactor * 0.015)).toFixed(3);
            
            if (pb) {
                if (opacity !== lastOpacity) pb.style.setProperty('--orbit-glow-opacity', opacity);
                if (scale !== lastScale) pb.style.setProperty('--orbit-glow-scale', scale);
            }
            if (ppCard) {
                if (opacity !== lastOpacity) ppCard.style.setProperty('--orbit-glow-opacity', opacity);
                if (scale !== lastScale) ppCard.style.setProperty('--orbit-glow-scale', scale);
            }
            lastOpacity = opacity;
            lastScale = scale;
        }
        
        orbitGlowRafId = requestAnimationFrame(loop);
    }
    
    orbitGlowRafId = requestAnimationFrame(loop);
}

function stopOrbitGlowLoop() {
    isOrbitGlowRunning = false;
    if (orbitGlowRafId) {
        cancelAnimationFrame(orbitGlowRafId);
        orbitGlowRafId = null;
    }
    const pb = document.getElementById('player-bar');
    const ppCard = document.querySelector('.player-glass-card');
    if (pb) {
        pb.style.removeProperty('--orbit-glow-opacity');
        pb.style.removeProperty('--orbit-glow-scale');
        pb.style.boxShadow = '';
    }
    if (ppCard) {
        ppCard.style.removeProperty('--orbit-glow-opacity');
        ppCard.style.removeProperty('--orbit-glow-scale');
        ppCard.style.boxShadow = '';
    }
}

// Window visibility & optimization events
window.addEventListener('blur', syncOrbitGlowState);
window.addEventListener('focus', syncOrbitGlowState);
document.addEventListener('visibilitychange', syncOrbitGlowState);
document.addEventListener('nedotify:window_visibility_changed', syncOrbitGlowState);
document.addEventListener('nedotify:performance_preset_changed', syncOrbitGlowState);

// Magnetic Waveform Scrubber Listeners
let isWaveformRenderPending = false;
let bottomWaveformBoundsFrame = 0;
let bottomWaveformBoundsObserver = null;
let bottomWaveformStyleObserver = null;
function requestThrottledWaveformRender() {
    if (isWaveformRenderPending) return;
    isWaveformRenderPending = true;
    requestAnimationFrame(() => {
        isWaveformRenderPending = false;
        renderWaveforms(playbackState.positionMs / (playbackState.durationMs || 1));
    });
}

function syncBottomWaveformBounds() {
    const playerBar = document.getElementById('player-bar');
    const likeButton = document.getElementById('pb-btn-like');
    const volumeButton = document.getElementById('pb-volume-btn');
    if (!playerBar || !likeButton || !volumeButton) return;

    const playerRect = playerBar.getBoundingClientRect();
    const likeRect = likeButton.getBoundingClientRect();
    const volumeRect = volumeButton.getBoundingClientRect();
    if (!playerRect.width || !volumeRect.width) return;

    // Narrow layouts hide the like button. Use the metadata edge instead of
    // retaining offsets from a previous wider window (or the initial fallback).
    const metadata = playerBar.querySelector('.pb-info')?.getBoundingClientRect();
    const waveformStart = likeRect.width ? likeRect.left
        : metadata?.width ? metadata.right + 12 : playerRect.left;

    const borderLeft = parseFloat(getComputedStyle(playerBar).borderLeftWidth) || 0;
    const borderRight = parseFloat(getComputedStyle(playerBar).borderRightWidth) || 0;
    const contentLeft = playerRect.left + borderLeft;
    const contentRight = playerRect.right - borderRight;
    const left = Math.max(0, waveformStart - contentLeft);
    const right = Math.max(0, contentRight - volumeRect.left);

    playerBar.style.setProperty('--pb-waveform-left', `${left.toFixed(1)}px`);
    playerBar.style.setProperty('--pb-waveform-right', `${right.toFixed(1)}px`);
}

function scheduleBottomWaveformBoundsSync() {
    if (bottomWaveformBoundsFrame) return;
    bottomWaveformBoundsFrame = requestAnimationFrame(() => {
        bottomWaveformBoundsFrame = 0;
        syncBottomWaveformBounds();
    });
}

function setupMagneticWaveformListeners() {
    syncBottomWaveformBounds();
    window.addEventListener('resize', scheduleBottomWaveformBoundsSync);

    if (typeof ResizeObserver === 'function') {
        bottomWaveformBoundsObserver = new ResizeObserver(scheduleBottomWaveformBoundsSync);
        ['player-bar', 'pb-track', 'pb-right', 'pb-btn-like', 'pb-volume-btn'].forEach(id => {
            const element = document.getElementById(id);
            if (element) bottomWaveformBoundsObserver.observe(element);
        });
    }

    if (typeof MutationObserver === 'function') {
        bottomWaveformStyleObserver = new MutationObserver(scheduleBottomWaveformBoundsSync);
        bottomWaveformStyleObserver.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ['data-ui-style', 'data-macos-mode']
        });
    }

    ['pb-progress-track', 'pp-progress-track', 'mp-progress-track'].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;

        el.addEventListener('mousemove', (e) => {
            const rect = el.getBoundingClientRect();
            if (rect.width > 0) {
                hoveredWaveformNormX = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
                requestThrottledWaveformRender();
            }
        });

        el.addEventListener('mouseleave', () => {
            hoveredWaveformNormX = -1;
            requestThrottledWaveformRender();
        });
    });
}
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupMagneticWaveformListeners);
} else {
    setupMagneticWaveformListeners();
}




