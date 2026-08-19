// NeDotify Р Р†Р вЂљ" Player Module
import { formatTime, renderIcons, showToast, getCoverUrl, extractDominantColor, escapeHtml } from './utils.js?v=20260817_3';

let currentTrack = null;
let isPlaying = false;
let currentDuration = 0;
let isDraggingProgress = false;
let isDraggingVolume = false;
let lastSeekTime = 0;
let currentPosMs = 0;
let targetPosMs = 0;
let lastAnimTimestamp = 0;
let animFrameId = null;
let currentVolume = 70;
let isMuted = false;
let currentReplayGain = 1.0;
const TARGET_LUFS = -14.0;
let isInitialLoad = true;
let currentPlaybackRate = 1.0;
let currentPreservesPitch = true;
let currentQueueVersion = 0;

// M-1: throttle volume RPC to 100ms (last value wins); flush immediately on release
let volumeRpcTimer = null;

function scheduleVolumeRpc(volume, immediate) {
    if (volumeRpcTimer !== null) clearTimeout(volumeRpcTimer);
    volumeRpcTimer = setTimeout(() => {
        volumeRpcTimer = null;
        api('set_volume', volume);
    }, immediate ? 0 : 100);
}

export function getQueueVersion() {
    return currentQueueVersion;
}

export function incrementQueueVersion() {
    currentQueueVersion++;
    return currentQueueVersion;
}

export function setPlaybackRate(rate) {
    currentPlaybackRate = parseFloat(rate) || 1.0;
    if (activeAudio) {
        activeAudio.playbackRate = currentPlaybackRate;
    }
}

export function setPreservesPitch(enabled) {
    currentPreservesPitch = Boolean(enabled);
    if (activeAudio) {
        if ('preservesPitch' in activeAudio) activeAudio.preservesPitch = currentPreservesPitch;
        else if ('webkitPreservesPitch' in activeAudio) activeAudio.webkitPreservesPitch = currentPreservesPitch;
        else if ('mozPreservesPitch' in activeAudio) activeAudio.mozPreservesPitch = currentPreservesPitch;
    }
}

// Dual Audio Engine for Crossfade
let audioA = new Audio();
audioA.crossOrigin = "anonymous";
let audioB = new Audio();
audioB.crossOrigin = "anonymous";
let activeAudio = audioA;
let hlsInstance = null;

function loadAudioSource(audioEl, src) {
    if (hlsInstance) {
        try { hlsInstance.destroy(); } catch(e) {}
        hlsInstance = null;
    }

    const isHls = typeof src === 'string' && (src.includes('.m3u8') || src.includes('/playlist') || src.includes('format=m3u8'));
    if (isHls && window.Hls && window.Hls.isSupported()) {
        try {
            hlsInstance = new window.Hls({
                enableWorker: true,
                lowLatencyMode: false
            });
            hlsInstance.loadSource(src);
            hlsInstance.attachMedia(audioEl);
            return;
        } catch(he) {
            console.warn('HLS.js initialization error, falling back to direct src:', he);
        }
    }
    audioEl.src = src;
    try { audioEl.load(); } catch(e) {}
}

// Flow Autoplay & Prefetch State (Phase 3 & Phase 4)
let isFlowEnabled = localStorage.getItem('nedotify_player_flow_enabled') !== 'false';
let lastFlowFetchTime = 0;
let flowSessionCount = 0;
const flowHistoryKeys = new Set();
let isFlowFetching = false;

let lastPrefetchedTrackId = null;
let isPreloadingNextTrack = false;

export function updateFlowButtons() {
    const pbFlow = document.getElementById('pb-btn-flow');
    const ppFlow = document.getElementById('pp-btn-flow');
    if (pbFlow) pbFlow.classList.toggle('active', isFlowEnabled);
    if (ppFlow) ppFlow.classList.toggle('active', isFlowEnabled);
}

export function toggleFlow() {
    isFlowEnabled = !isFlowEnabled;
    localStorage.setItem('nedotify_player_flow_enabled', isFlowEnabled ? 'true' : 'false');
    updateFlowButtons();
    window.dispatchEvent(new CustomEvent('nedotify:toast', {
        detail: {
            msg: isFlowEnabled ? '📻 «Бесконечная волна (Flow)» включена' : '📻 «Бесконечная волна (Flow)» выключена',
            type: 'info'
        }
    }));
}


// Web Audio API for Equalizer
let audioCtx = null;
let mediaSourcesCreated = false;
let eqNodes = [];
let preampNode = null;
let srcA = null;
let srcB = null;
let compressorNode = null;
let analyserNode = null;

function initAudioContext() {
    if (audioCtx) return;
    try {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        
        analyserNode = audioCtx.createAnalyser();
        analyserNode.fftSize = 256; // 128 frequency bins — smoother visualizer
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
        compressorNode.threshold.value = -6.0;
        compressorNode.knee.value = 12;
        compressorNode.ratio.value = 4;
        compressorNode.attack.value = 0.003;
        compressorNode.release.value = 0.25;
        
        prevNode.connect(compressorNode);
        compressorNode.connect(analyserNode);
        analyserNode.connect(audioCtx.destination);
        
        // Connect both audio elements safely
        if (!mediaSourcesCreated) {
            srcA = audioCtx.createMediaElementSource(audioA);
            srcB = audioCtx.createMediaElementSource(audioB);
            mediaSourcesCreated = true;
        }
        
        if (srcA) srcA.connect(preampNode);
        if (srcB) srcB.connect(preampNode);
    } catch(e) {
        console.error("AudioContext initialization failed:", e);
    }
}

export function applyVolumeNormalization(enabled) {
    if (!audioCtx) initAudioContext();
    if (!compressorNode) return;
    try {
        if (enabled) {
            compressorNode.threshold.value = -14.0;
            compressorNode.knee.value = 8;
            compressorNode.ratio.value = 6;
            compressorNode.attack.value = 0.005;
            compressorNode.release.value = 0.2;
        } else {
            compressorNode.threshold.value = -3.0;
            compressorNode.knee.value = 20;
            compressorNode.ratio.value = 2;
        }
    } catch(e) {}
}

export function getAudioFrequencyData(dataArray) {
    if (!audioCtx) initAudioContext();
    if (audioCtx && audioCtx.state === 'suspended') {
        audioCtx.resume();
    }
    if (analyserNode && dataArray) {
        analyserNode.getByteFrequencyData(dataArray);
        return true;
    }
    return false;
}

export function setEq(preamp, bands) {
    if (!audioCtx) initAudioContext();
    if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
    
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
let lastRetriedTrackId = null;
const STALL_FALLBACK_MS = 10000;

function handleStreamError(audio, reason) {
    if (audio !== activeAudio || !currentTrack) return;
    disarmStallFallback(audio);
    
    const trackIdKey = String(currentTrack.id || currentTrack.source_id || currentTrack.title || '');
    if (lastRetriedTrackId !== trackIdKey) {
        lastRetriedTrackId = trackIdKey;
        currentTrackRetries = 0;
    }
    
    currentTrackRetries++;
    console.warn(`Audio stream error (${reason}), retry attempt ${currentTrackRetries} for:`, currentTrack.title);
    
    if (currentTrackRetries <= 2) {
        setTimeout(() => {
            if (audio === activeAudio && currentTrack && String(currentTrack.id || currentTrack.source_id || currentTrack.title || '') === trackIdKey) {
                if (window.pywebview?.api?.play_track) {
                    // Force full re-resolution: drop cached stream/file urls so backend re-resolves
                    const cleanTrack = { ...currentTrack, file_path: undefined, stream_url: undefined };
                    window.pywebview.api.play_track(cleanTrack);
                }
            }
        }, 1500 * currentTrackRetries);
    } else {
        console.error(`Audio stream failed after ${currentTrackRetries} attempts. Stopping playback.`);
        currentTrackRetries = 0;
        lastRetriedTrackId = null;
        window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: `Не удалось воспроизвести: ${currentTrack.title || 'трек'}`, type: 'error' } }));
        if (activeAudio) {
            try { activeAudio.pause(); } catch(e) {}
            try { activeAudio.currentTime = 0; } catch(e) {}
            activeAudio.src = '';
            try { activeAudio.load(); } catch(e) {}
        }
        isPlaying = false;
        onStateChanged('stopped');
    }
}

function armStallFallback(audio) {
    disarmStallFallback(audio);
    audio._stallTimer = setTimeout(() => {
        audio._stallTimer = null;
        if (audio === activeAudio && currentTrack && !audio.paused && audio.src && audio.src !== '' && audio.src !== 'about:blank') {
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
    audio.addEventListener('loadstart', () => armStallFallback(audio));
    audio.addEventListener('stalled', () => armStallFallback(audio));
    audio.addEventListener('waiting', () => armStallFallback(audio));
    audio.addEventListener('playing', () => {
        disarmStallFallback(audio);
        currentTrackRetries = 0;
    });
    audio.addEventListener('canplay', () => disarmStallFallback(audio));
    audio.addEventListener('progress', () => disarmStallFallback(audio));
    audio.addEventListener('timeupdate', () => {
        if (audio === activeAudio && !isDraggingProgress) {
            // Prefer HTML5 duration if backend didn't provide one
            if (audio.duration && audio.duration !== Infinity) {
                const audioDurMs = Math.round(audio.duration * 1000);
                if (audioDurMs > 0 && Math.abs(currentDuration - audioDurMs) > 2000) {
                    currentDuration = audioDurMs;
                    setElText('pb-time-total', formatTime(currentDuration / 1000));
                    setElText('pp-time-total', formatTime(currentDuration / 1000));
                }
            }
            
            currentPosMs = Math.round(audio.currentTime * 1000);
            
            // UI updates are handled smoothly by animateProgress (60fps)
            // But we still need to handle 0-duration Edge Cases
            if (currentDuration === 0) {
                setEl('pb-progress-fill', 'transform', `translateX(-100%)`);
                setEl('pp-progress-fill', 'transform', `translateX(-100%)`);
                setElText('pb-time-current', formatTime(currentPosMs / 1000));
                setElText('pp-time-current', formatTime(currentPosMs / 1000));
            }
            
            // Dispatch locally for lyrics
            document.dispatchEvent(new CustomEvent('nedotify:position_changed', { detail: { pos: currentPosMs, duration: currentDuration } }));
            
            // Periodically report to backend for scrobbling
            const now = performance.now();
            if (now - (window._lastReportTime || 0) > 5000) {
                window._lastReportTime = now;
                api('report_position', currentPosMs, currentDuration);
            }
        }
    });
    audio.addEventListener('play', () => { 
        if (audio === activeAudio) {
            api('report_state', 'playing'); 
            onStateChanged('playing');
        }
    });
    audio.addEventListener('pause', () => { 
        if (audio === activeAudio) {
            api('report_state', 'paused'); 
            onStateChanged('paused');
        }
    });
    audio.addEventListener('ended', () => {
        if (audio === activeAudio) {
            api('next_track');
        }
    });
    audio.addEventListener('error', (e) => {
        // Ignore synthetic or background cleanup errors
        if (audio !== activeAudio || !audio.src || audio.src === '' || audio.src === 'about:blank' || audio.src === window.location.href) {
            return;
        }
        handleStreamError(audio, 'error_event');
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
        
        navigator.mediaSession.setActionHandler('play', () => api('play_pause'));
        navigator.mediaSession.setActionHandler('pause', () => api('play_pause'));
        navigator.mediaSession.setActionHandler('previoustrack', () => api('prev_track'));
        navigator.mediaSession.setActionHandler('nexttrack', () => api('next_track'));
    }
}

let currentFadeInterval = null;

export function playTrack(track, streamUrl) {
    if (!track || !streamUrl) return;
    
    if (audioCtx && audioCtx.state === 'suspended') {
        audioCtx.resume().catch(() => {});
    }
    
    updateMediaSession(track);
    
    if (currentFadeInterval) {
        clearInterval(currentFadeInterval);
        currentFadeInterval = null;
    }

    const trackIdKey = String(track.id || track.source_id || track.title || '');
    if (lastRetriedTrackId !== trackIdKey) {
        lastRetriedTrackId = trackIdKey;
        currentTrackRetries = 0;
    }

    const newAudio = activeAudio === audioA ? audioB : audioA;
    const oldAudio = activeAudio;
    
    // Switch activeAudio immediately FIRST to prevent old audio error handlers from firing
    activeAudio = newAudio;
    currentTrack = track;
    isPlaying = true;
    disarmStallFallback(newAudio);
    
    // Instantly stop and clean up old audio
    if (oldAudio) {
        disarmStallFallback(oldAudio);
        try { oldAudio.pause(); } catch(e) {}
        try { oldAudio.currentTime = 0; } catch(e) {}
        oldAudio.src = '';
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
    if (dur && dur > 0) {
        if (dur > 50000) {
            currentDuration = dur;
        } else {
            currentDuration = dur * 1000;
        }
    } else {
        currentDuration = 0;
    }

    let finalSrc = streamUrl;
    if (finalSrc && finalSrc.match(/^[a-zA-Z]:\\/)) {
        finalSrc = 'file:///' + finalSrc.replace(/\\/g, '/');
    }
    
    loadAudioSource(newAudio, finalSrc);
    newAudio.playbackRate = currentPlaybackRate;
    if ('preservesPitch' in newAudio) newAudio.preservesPitch = currentPreservesPitch;
    else if ('webkitPreservesPitch' in newAudio) newAudio.webkitPreservesPitch = currentPreservesPitch;
    else if ('mozPreservesPitch' in newAudio) newAudio.mozPreservesPitch = currentPreservesPitch;

    const targetVol = isMuted ? 0 : (currentVolume / 100) * currentReplayGain;
    newAudio.volume = targetVol;
    
    const playPromise = newAudio.play();
    if (playPromise !== undefined) {
        playPromise.catch(e => {
            console.warn("Audio play promise error:", e);
        });
    }
    
    onStateChanged('playing');
}

export function seekTo(posMs) {
    currentPosMs = posMs;
    targetPosMs = posMs;
    lastSeekTime = performance.now();
    
    if (currentDuration > 0) {
        const pct = Math.max(0, Math.min(100, (posMs / currentDuration) * 100));
        const txVal = `translateX(${pct - 100}%)`;
        setEl('pb-progress-fill', 'transform', txVal);
        setEl('pp-progress-fill', 'transform', txVal);
        setEl('mp-progress-fill', 'transform', txVal);
        setElText('pb-time-current', formatTime(posMs / 1000));
        setElText('pp-time-current', formatTime(posMs / 1000));
        setElText('mp-time-current', formatTime(posMs / 1000));
    }

    if (activeAudio) {
        try {
            activeAudio.currentTime = posMs / 1000;
        } catch (e) {
            console.error("Error seeking audio:", e);
        }
    }
    // M-1: single RPC with the final value (set_position is a no-op on the backend)
    api('report_position', posMs, currentDuration);
}


export function getCurrentTrack() { return currentTrack; }
export function getIsPlaying() { return isPlaying; }
window.getIsPlaying = getIsPlaying;
export function getVolume() { return isMuted ? 0 : currentVolume; }

export function togglePlayPause() {
    if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();

    const hasValidSrc = activeAudio && activeAudio.src && activeAudio.src !== '' && !activeAudio.src.endsWith('about:blank');
    if (!hasValidSrc) {
        if (currentTrack) {
            if (window.pywebview?.api?.play_track) {
                window.pywebview.api.play_track(currentTrack);
            }
        }
        return;
    }

    if (activeAudio.paused) {
        activeAudio.play().catch(e => console.error("Play error:", e));
    } else {
        activeAudio.pause();
        // Also pause the inactive audio if it's currently crossfading
        const inactiveAudio = activeAudio === audioA ? audioB : audioA;
        if (!inactiveAudio.paused) {
            inactiveAudio.pause();
        }
    }
}

export function initPlayer() {
    // Bottom bar controls
    const btnPlay = document.getElementById('pb-btn-play');
    const btnNext = document.getElementById('pb-btn-next');
    const btnPrev = document.getElementById('pb-btn-prev');
    const btnShuffle = document.getElementById('pb-btn-shuffle');
    const btnRepeat = document.getElementById('pb-btn-repeat');
    const btnLike = document.getElementById('pb-btn-like');

    /* keydown moved to hotkeys.js */

    if (btnPlay) btnPlay.addEventListener('click', togglePlayPause);
    if (btnNext) btnNext.addEventListener('click', () => api('next_track'));
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
        if (!currentTrack) return;
        const res = await api('toggle_favorite', currentTrack);
        if (res && res.success) {
            currentTrack.is_favorite = res.is_favorite;
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
    if (ppNext) ppNext.addEventListener('click', () => api('next_track'));
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
        if (!currentTrack) return;
        const res = await api('toggle_favorite', currentTrack);
        if (res && res.success) {
            currentTrack.is_favorite = res.is_favorite;
            updateLikeButtons();
        }
    });

    const ppFlow = document.getElementById('pp-btn-flow');
    const pbFlow = document.getElementById('pb-btn-flow');
    if (ppFlow) ppFlow.addEventListener('click', toggleFlow);
    if (pbFlow) pbFlow.addEventListener('click', toggleFlow);
    updateFlowButtons();

    const ppQueue = document.getElementById('pp-btn-queue');
    if (ppQueue) ppQueue.addEventListener('click', () => {
        const queueDrawer = document.getElementById('queue-drawer') || document.getElementById('queue-overlay');
        if (queueDrawer) queueDrawer.classList.toggle('open');
    });

    // Mini Player Controls
    const mpPlay = document.getElementById('mp-btn-play');
    const mpStop = document.getElementById('mp-btn-stop');
    const mpNext = document.getElementById('mp-btn-next');
    const mpPrev = document.getElementById('mp-btn-prev');
    const mpLike = document.getElementById('mp-btn-like');
    const mpExpand = document.getElementById('mp-btn-expand');

    function stopPlayback() {
        if (activeAudio) {
            activeAudio.pause();
            audioA.pause();
            audioB.pause();
            try { activeAudio.currentTime = 0; } catch(e) {}
        }
        currentPosMs = 0;
        targetPosMs = 0;
        isPlaying = false;
        onStateChanged('stopped');
        api('stop_track');
    }

    if (mpPlay) mpPlay.addEventListener('click', (e) => {
        e.stopPropagation();
        togglePlayPause();
    });
    if (mpStop) mpStop.addEventListener('click', (e) => {
        e.stopPropagation();
        stopPlayback();
    });
    if (mpNext) mpNext.addEventListener('click', (e) => {
        e.stopPropagation();
        api('next_track');
    });
    if (mpPrev) mpPrev.addEventListener('click', (e) => {
        e.stopPropagation();
        api('prev_track');
    });

    if (mpLike) mpLike.addEventListener('click', async (e) => {
        e.stopPropagation();
        const trk = currentTrack || (queue && queue[queueIndex]);
        if (!trk) return;
        const res = await api('toggle_favorite', trk);
        if (res && res.success) {
            trk.is_favorite = res.is_favorite;
            if (currentTrack) currentTrack.is_favorite = res.is_favorite;
            updateLikeButtons();
        }
    });

    const mpMinimize = document.getElementById('mp-btn-minimize');
    const mpClose = document.getElementById('mp-btn-close');

    if (mpMinimize) mpMinimize.addEventListener('click', (e) => {
        e.stopPropagation();
        if (window.pywebview?.api?.minimize_window) {
            window.pywebview.api.minimize_window();
        } else if (window.pywebview?.api?.minimize) {
            window.pywebview.api.minimize();
        }
    });

    if (mpExpand) mpExpand.addEventListener('click', (e) => {
        e.stopPropagation();
        if (window.toggleMiniPlayerMode) {
            window.toggleMiniPlayerMode(false);
        } else if (window.NeDotify?.toggleMiniPlayerMode) {
            window.NeDotify.toggleMiniPlayerMode(false);
        }
    });

    if (mpClose) mpClose.addEventListener('click', (e) => {
        e.stopPropagation();
        if (window.pywebview?.api?.close_window) {
            window.pywebview.api.close_window();
        } else if (window.pywebview?.api?.close) {
            window.pywebview.api.close();
        }
    });

    const mpCard = document.getElementById('mini-player-overlay');
    if (mpCard) {
        mpCard.addEventListener('mousedown', (e) => {
            if (e.target.closest('button, input, select, a, .btn-ctrl, .icon-btn, .mp-progress-bar-wrap, .progress-track')) {
                return;
            }
            if (window.pywebview?.api?.start_drag) {
                window.pywebview.api.start_drag();
            }
        });
    }

    setupDragBar('mp-progress-track', {
        onDrag: (pct) => {
            isDraggingProgress = true;
            setEl('mp-progress-fill', 'width', `${pct * 100}%`);
            setElText('mp-time-current', formatTime((pct * currentDuration) / 1000));
        },
        onRelease: (pct) => {
            isDraggingProgress = false;
            const targetMs = Math.round(pct * currentDuration);
            seekTo(targetMs);
        }
    });

    // Progress bar drag (bottom bar)
    setupDragBar('pb-progress-track', {
        onDrag: (pct) => {
            isDraggingProgress = true;
            setEl('pb-progress-fill', 'transform', `translateX(${pct * 100 - 100}%)`);
            setElText('pb-time-current', formatTime((pct * currentDuration) / 1000));
            // Also update player page & mini player
            setEl('pp-progress-fill', 'transform', `translateX(${pct * 100 - 100}%)`);
            setElText('pp-time-current', formatTime((pct * currentDuration) / 1000));
            setEl('mp-progress-fill', 'transform', `translateX(${pct * 100 - 100}%)`);
            setElText('mp-time-current', formatTime((pct * currentDuration) / 1000));
        },
        onRelease: (pct) => {
            isDraggingProgress = false;
            const targetMs = Math.round(pct * currentDuration);
            seekTo(targetMs);
        }
    });

    // Progress bar drag (player page)
    setupDragBar('pp-progress-track', {
        onDrag: (pct) => {
            isDraggingProgress = true;
            setEl('pp-progress-fill', 'transform', `translateX(${pct * 100 - 100}%)`);
            setElText('pp-time-current', formatTime((pct * currentDuration) / 1000));
            setEl('pb-progress-fill', 'transform', `translateX(${pct * 100 - 100}%)`);
            setElText('pb-time-current', formatTime((pct * currentDuration) / 1000));
        },
        onRelease: (pct) => {
            isDraggingProgress = false;
            const targetMs = Math.round(pct * currentDuration);
            seekTo(targetMs);
        }
    });

    // Volume bar drag
    setupDragBar('pb-volume-track', {
        onDrag: (pct) => {
            isDraggingVolume = true;
            currentVolume = Math.round(pct * 100);
            setEl('pb-volume-fill', 'width', `${pct * 100}%`);
            updateVolumeIcon(currentVolume);
            activeAudio.volume = isMuted ? 0 : (currentVolume / 100) * currentReplayGain;
            // M-1: throttle RPC while dragging — last value wins
            scheduleVolumeRpc(currentVolume, false);
        },
        onRelease: (pct) => {
            isDraggingVolume = false;
            currentVolume = Math.round(pct * 100);
            activeAudio.volume = isMuted ? 0 : (currentVolume / 100) * currentReplayGain;
            // M-1: flush the final value immediately
            scheduleVolumeRpc(currentVolume, true);
        }
    });

    window.NeDotify = window.NeDotify || {};
    window.NeDotify.adjustVolume = (delta) => {
        currentVolume = Math.max(0, Math.min(100, currentVolume + delta));
        setEl('pb-volume-fill', 'width', `${currentVolume}%`);
        updateVolumeIcon(currentVolume);
        if (activeAudio) activeAudio.volume = isMuted ? 0 : (currentVolume / 100) * currentReplayGain;
        // M-1: discrete event — send immediately
        scheduleVolumeRpc(currentVolume, true);
    };

    // Volume icon mute toggle
    const volBtn = document.getElementById('pb-volume-btn');
    if (volBtn) volBtn.addEventListener('click', () => {
        isMuted = !isMuted;
        activeAudio.volume = isMuted ? 0 : (currentVolume / 100) * currentReplayGain;
        const vfill = document.getElementById('pb-volume-fill');
        if (vfill) vfill.style.opacity = isMuted ? '0.3' : '1';
        updateVolumeIcon(currentVolume, isMuted);
    });

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

            // Update track title in header
            const header = document.getElementById('track-options-header');
            if (header && currentTrack) {
                header.textContent = currentTrack.title || 'ОПЦИИ ТРЕКА';
            }

            // Load playlists into menu
            const itemsEl = document.getElementById('track-options-playlist-items');
            if (itemsEl && currentTrack) {
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
                                await api('add_to_playlist', plId, currentTrack);
                                optMenu.classList.remove('visible');
                                const { showToast } = await import('./utils.js?v=20260817_3');
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
            if (currentTrack && window.NeDotify?.downloadTrack) {
                window.NeDotify.downloadTrack(currentTrack);
            }
        });

        // Copy track title
        document.getElementById('track-options-copy')?.addEventListener('click', () => {
            optMenu.classList.remove('visible');
            if (currentTrack) {
                const text = `${currentTrack.title} — ${currentTrack.artist || ''}`.trim();
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

    // Start smooth progress animation if playing
    if (isPlaying && !animFrameId) {
        animFrameId = requestAnimationFrame(animateProgress);
    }
}

let lastProgressFrame = 0;

// Pre-cache progress DOM elements once (avoids getElementById on every frame)
const _prog = {};
function _getProgEls() {
    if (!_prog.pbFill) {
        _prog.pbFill   = document.getElementById('pb-progress-fill');
        _prog.ppFill   = document.getElementById('pp-progress-fill');
        _prog.mpFill   = document.getElementById('mp-progress-fill');
        _prog.pbTime   = document.getElementById('pb-time-current');
        _prog.ppTime   = document.getElementById('pp-time-current');
        _prog.mpTime   = document.getElementById('mp-time-current');
    }
    return _prog;
}

function animateProgress(timestamp) {
    if (!isPlaying) {
        animFrameId = null;
        return;
    }
    animFrameId = requestAnimationFrame(animateProgress);
    if (document.hidden) return;

    // Throttle progress bar updates to ~15 FPS (66ms) — imperceptible and saves GPU
    if (timestamp - lastProgressFrame < 66) return;
    lastProgressFrame = timestamp;

    if (!isDraggingProgress && activeAudio) {
        if (activeAudio.duration && !isNaN(activeAudio.duration) && activeAudio.duration > 0) {
            currentDuration = Math.round(activeAudio.duration * 1000);
        }
        if (currentDuration > 0) {
            currentPosMs = Math.round(activeAudio.currentTime * 1000);
            const pct = Math.max(0, Math.min(100, (currentPosMs / currentDuration) * 100));
            if (!isFinite(pct)) return;

            const timeStr  = formatTime(currentPosMs / 1000);
            const els = _getProgEls();

            const txVal = `translateX(${pct - 100}%)`;
            if (els.pbFill) els.pbFill.style.transform = txVal;
            if (els.ppFill) els.ppFill.style.transform = txVal;
            if (els.mpFill) els.mpFill.style.transform = txVal;
            if (els.pbTime) els.pbTime.textContent = timeStr;
            if (els.ppTime) els.ppTime.textContent = timeStr;
            if (els.mpTime) els.mpTime.textContent = timeStr;

            // Waveform scrubber update
            renderWaveforms(pct / 100);

            const remainingSec = (currentDuration - currentPosMs) / 1000;

            // 1. Next Track Prefetching (Phase 4: at 20s remaining, single-flight pre-warm)
            if (remainingSec <= 20 && currentDuration > 25000 && !isPreloadingNextTrack) {
                const prefetchEnabled = localStorage.getItem('nedotify_player_player_prefetch') !== 'false';
                if (prefetchEnabled && window.pywebview?.api?.get_next_track) {
                    isPreloadingNextTrack = true;
                    const capturedQueueVer = currentQueueVersion;

                    window.pywebview.api.get_next_track().then(nextTrack => {
                        if (nextTrack && capturedQueueVer === currentQueueVersion) {
                            const trackKey = nextTrack.id || nextTrack.source_id;
                            if (trackKey && lastPrefetchedTrackId !== trackKey) {
                                lastPrefetchedTrackId = trackKey;
                                if (window.pywebview?.api?.prefetch_track) {
                                    window.pywebview.api.prefetch_track(nextTrack);
                                }
                                if (nextTrack.stream_url) {
                                    const inactiveAudio = activeAudio === audioA ? audioB : audioA;
                                    if (inactiveAudio && inactiveAudio.src !== nextTrack.stream_url) {
                                        try {
                                            inactiveAudio.src = nextTrack.stream_url;
                                            inactiveAudio.load();
                                        } catch (preErr) {
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

            // 2. Queue Flow / Autoplay Trigger (Phase 3: at 15s remaining on the LAST track of queue)
            const now = Date.now();
            if (isFlowEnabled && remainingSec <= 15 && !isFlowFetching && (now - lastFlowFetchTime > 30000) && flowSessionCount < 200) {
                if (window.pywebview?.api?.get_queue && window.pywebview?.api?.get_flow_tracks && currentTrack) {
                    isFlowFetching = true;
                    lastFlowFetchTime = now;

                    window.pywebview.api.get_queue().then(async q => {
                        if (q && q.tracks && (q.current_index >= q.tracks.length - 1)) {
                            const queueIds = (q.tracks || []).map(t => t.id || t.source_id).filter(Boolean);
                            const excludeIds = [...queueIds, ...Array.from(flowHistoryKeys)];

                            try {
                                const newTracks = await window.pywebview.api.get_flow_tracks(currentTrack, 6, excludeIds);
                                if (newTracks && Array.isArray(newTracks) && newTracks.length > 0) {
                                    const filtered = newTracks.filter(nt => {
                                        const k1 = nt.id || nt.source_id;
                                        const k2 = `${(nt.artist || '').toLowerCase()}:${(nt.title || '').toLowerCase()}`;
                                        if (k1 && flowHistoryKeys.has(k1)) return false;
                                        if (flowHistoryKeys.has(k2)) return false;
                                        if (queueIds.includes(k1)) return false;
                                        return true;
                                    });

                                    if (filtered.length > 0) {
                                        incrementQueueVersion();
                                        for (const nt of filtered) {
                                            const k1 = nt.id || nt.source_id;
                                            const k2 = `${(nt.artist || '').toLowerCase()}:${(nt.title || '').toLowerCase()}`;
                                            if (k1) flowHistoryKeys.add(k1);
                                            flowHistoryKeys.add(k2);
                                            if (window.pywebview?.api?.add_to_queue) {
                                                await window.pywebview.api.add_to_queue(nt);
                                            }
                                        }
                                        flowSessionCount += filtered.length;
                                        window.dispatchEvent(new CustomEvent('nedotify:toast', {
                                            detail: { msg: `📻 «Бесконечная волна»: подобрано ${filtered.length} похожих треков`, type: 'info' }
                                        }));
                                    }
                                }
                            } catch (flowErr) {
                                console.debug('Flow autoplay error:', flowErr);
                            }
                        }
                    }).catch(qErr => {
                        console.debug('Flow get_queue error:', qErr);
                    }).finally(() => {
                        setTimeout(() => { isFlowFetching = false; }, 15000);
                    });
                }
            }
        }
    }
}

// --- Event handlers called from events.js ---

export function onTrackChanged(track) {
    if (!track) return;
    
    currentTrack = track;
    currentPosMs = 0;
    targetPosMs = 0;
    
    if (track.duration && track.duration > 0) {
        if (track.duration > 50000) {
            currentDuration = track.duration;
        } else {
            currentDuration = track.duration * 1000;
        }
    } else {
        currentDuration = 0;
    }
    
    setEl('pb-progress-fill', 'width', '0%');
    setEl('pp-progress-fill', 'width', '0%');
    setEl('mp-progress-fill', 'width', '0%');
    setElText('pb-time-current', '0:00');
    setElText('pp-time-current', '0:00');
    setElText('mp-time-current', '0:00');
    setElText('pb-time-total', formatTime(currentDuration / 1000));
    setElText('pp-time-total', formatTime(currentDuration / 1000));
    setElText('mp-time-total', formatTime(currentDuration / 1000));
    
    // Fresh stream means a fresh attempt: reset retry accounting
    if (track.stream_url) {
        currentTrackRetries = 0;
        lastRetriedTrackId = null;
    }
    
    // Auto-play new track via HTML5 Audio (or pause on initial app launch)
    if (isInitialLoad) {
        isInitialLoad = false;
        if (track.stream_url) {
            activeAudio.src = track.stream_url;
        }
        activeAudio.pause();
        isPlaying = false;
        onStateChanged('paused');
        updateMediaSession(track);
        if ('mediaSession' in navigator) {
            navigator.mediaSession.playbackState = 'paused';
        }
    } else if (track.stream_url) {
        window._pendingResolveKey = null;
        // Avoid restarting playback when backend re-emits the same stream (e.g. double resolution notify)
        if (!activeAudio.src || activeAudio.src !== track.stream_url) {
            playTrack(track, track.stream_url);
        }
    } else if (track.file_path) {
        playTrack(track, track.file_path);
    } else if (track.source && track.source !== 'local' && track.source_id && window.pywebview?.api?.play_track) {
        // Stream not resolved yet: show loading and request background resolution.
        // Backend keeps the queue intact for the current track.
        isPlaying = false;
        onStateChanged('loading');
        const resolveKey = String(track.source) + '|' + String(track.source_id);
        if (window._pendingResolveKey !== resolveKey) {
            window._pendingResolveKey = resolveKey;
            const pendingTrack = { ...track, file_path: undefined, stream_url: undefined };
            window.pywebview.api.play_track(pendingTrack);
        }
    } else {
        isPlaying = false;
        onStateChanged('paused');
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
        pbCover.onload = () => {
            const color = extractDominantColor(pbCover);
            if (color) {
                document.documentElement.style.setProperty('--ambient-glow', `rgb(${color.r}, ${color.g}, ${color.b})`);
                document.documentElement.style.setProperty('--aura-orb-1', `rgb(${color.r}, ${color.g}, ${color.b})`);
                document.documentElement.style.setProperty('--aura-orb-2', `rgb(${Math.min(255, color.r + 40)}, ${Math.max(0, color.g - 25)}, ${Math.min(255, color.b + 50)})`);
            }
        };
        setElSrc('pb-cover', coverUrl);
    }

    fetchAndRenderWaveform(track);

    // Update player page
    const hasArtist = track?.artist && track.artist !== 'Локальный файл' && track.artist !== '...' && track.artist !== 'Unknown Artist';
    const headerTitle = (track?.title || 'Трек не выбран') + (hasArtist ? ' — ' + track.artist : '');
    const headerEl = document.getElementById('pp-header-title');
    if (headerEl) {
        headerEl.textContent = headerTitle;
        headerEl.title = headerTitle;
    }
    // Atomically reset progress bar and position tracking to prevent 100% / ended flicker
    currentPosMs = 0;
    targetPosMs = 0;
    currentDuration = (track?.duration ? track.duration * 1000 : 0);
    setEl('pb-progress-fill', 'width', '0%');
    setEl('pp-progress-fill', 'width', '0%');
    setEl('mp-progress-fill', 'width', '0%');
    setElText('pb-time-current', '0:00');
    setElText('pp-time-current', '0:00');
    setElText('mp-time-current', '0:00');
    setElText('pb-time-total', formatTime(currentDuration / 1000));
    setElText('pp-time-total', formatTime(currentDuration / 1000));
    setElText('mp-time-total', formatTime(currentDuration / 1000));

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

    // Update Player Page ambient background (cover image or fallback to standard ambient background)
    const playerBgGlow = document.getElementById('player-bg-glow');
    if (playerBgGlow) {
        if (coverUrl && coverUrl.trim() !== '') {
            const bgImg = new Image();
            bgImg.onload = () => {
                playerBgGlow.style.backgroundImage = `url("${coverUrl}")`;
                playerBgGlow.style.backgroundSize = 'cover';
                playerBgGlow.style.backgroundPosition = 'center';
                // Use CSS variable --player-glow-blur so settings can control intensity
                playerBgGlow.style.filter = 'blur(var(--player-glow-blur)) brightness(0.35) saturate(1.3)';
                playerBgGlow.style.opacity = `var(--player-glow-opacity, 0.5)`;
                playerBgGlow.style.transform = 'scale(1.1)';
                playerBgGlow.style.transition = 'opacity 0.5s ease-in-out';
            };
            bgImg.onerror = () => {
                playerBgGlow.style.cssText = '';
            };
            bgImg.src = coverUrl;
        } else {
            playerBgGlow.style.cssText = '';
        }
    }

    updateLikeButtons();
    renderIcons();
}

export function onStateChanged(state) {
    isPlaying = state === 'playing';

    document.dispatchEvent(new CustomEvent('nedotify:state_changed', { detail: state }));

    if (isPlaying) {
        if (!animFrameId) {
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

    const playIcon = isPlaying ? pauseIconName : playIconName;

    const coverSection = document.querySelector('.player-cover-section');
    
    const mpPlaySvg = isPlaying 
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
        const pbPlaySvg = isPlaying 
            ? '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" stroke="none"><rect x="5" y="4" width="4" height="16" rx="1"></rect><rect x="15" y="4" width="4" height="16" rx="1"></rect></svg>'
            : '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" stroke="none"><polygon points="6 4 18 12 6 20 6 4"></polygon></svg>';

        const ppPlaySvg = isPlaying 
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
        if (performance.now() - lastSeekTime < 1500) return;
        
        // If audio is actively playing in HTML5 Audio, let animateProgress handle smooth frame updates
        if (isPlaying && activeAudio && !activeAudio.paused) {
            return;
        }

        // Normalize units: ensure durationMs & posMs are strictly in milliseconds
        let realDurationMs = durationMs;
        if (activeAudio && activeAudio.duration > 0 && !isNaN(activeAudio.duration)) {
            realDurationMs = Math.round(activeAudio.duration * 1000);
        } else if (realDurationMs > 0 && realDurationMs < 10000) {
            realDurationMs = Math.round(realDurationMs * 1000);
        }

        if (realDurationMs > 0) {
            currentDuration = realDurationMs;
        }

        let realPosMs = posMs;
        if (realPosMs > 0 && realPosMs < 10000 && currentDuration > 10000) {
            realPosMs = Math.round(realPosMs * 1000);
        }
        targetPosMs = realPosMs;

        if (!isDraggingProgress && currentDuration > 0) {
            const pct = Math.max(0, Math.min(100, (realPosMs / currentDuration) * 100));
            if (isFinite(pct)) {
                const txVal = `translateX(${pct - 100}%)`;
                const els = _getProgEls();
                if (els.pbFill) els.pbFill.style.transform = txVal;
                if (els.ppFill) els.ppFill.style.transform = txVal;
                if (els.mpFill) els.mpFill.style.transform = txVal;
            }
            const timeStr = formatTime(realPosMs / 1000);
            const els = _getProgEls();
            if (els.pbTime) els.pbTime.textContent = timeStr;
            if (els.ppTime) els.ppTime.textContent = timeStr;
            if (els.mpTime) els.mpTime.textContent = timeStr;
        }
    } catch(e) {
        console.error("Player onPositionChanged Error:", e);
    }
}

export function applySettings(settings) {
    const btnShuffle = document.getElementById('pb-btn-shuffle');
    const btnRepeat = document.getElementById('pb-btn-repeat');
    const ppShuffle = document.getElementById('pp-btn-shuffle');
    const ppRepeat = document.getElementById('pp-btn-repeat');
    const volFill = document.getElementById('pb-volume-fill');

    if (btnShuffle) btnShuffle.classList.toggle('active', settings.shuffle);
    if (ppShuffle) ppShuffle.classList.toggle('active', settings.shuffle);
    if (btnRepeat) btnRepeat.classList.toggle('active', settings.repeat !== 'off');
    if (ppRepeat) ppRepeat.classList.toggle('active', settings.repeat !== 'off');
    
    if (settings.volume !== undefined) {
        currentVolume = settings.volume;
    }
    
    if (volFill) volFill.style.width = `${currentVolume}%`;
    updateVolumeIcon(currentVolume);
}

// --- Helpers ---

function updateLikeButtons() {
    const isFav = currentTrack?.is_favorite;
    ['pb-btn-like', 'pp-btn-like'].forEach(id => {
        const btn = document.getElementById(id);
        if (!btn) return;
        btn.classList.toggle('active', !!isFav);
        const size = id.startsWith('pp') ? '20px' : '14px';
        btn.innerHTML = `<i data-lucide="heart" style="width:${size};height:${size};${isFav ? 'fill:currentColor' : ''}"></i>`;
    });

    const mpLike = document.getElementById('mp-btn-like');
    if (mpLike) {
        mpLike.classList.toggle('active', !!isFav);
        mpLike.innerHTML = `<svg viewBox="0 0 24 24" width="16" height="16" fill="${isFav ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"></path></svg>`;
    }

    renderIcons();
}

export async function downloadTrack(track) {
    if (!track) return;
    if (window.pywebview?.api?.download_track) {
        window.pywebview.api.download_track(track);
    }
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

function updateVolumeIcon(volume, isMuted) {
    const btn = document.getElementById('pb-volume-btn');
    if (!btn) return;
    let icon = 'volume-2';
    if (isMuted || volume === 0) icon = 'volume-x';
    else if (volume <= 50) icon = 'volume-1';
    btn.innerHTML = `<i data-lucide="${icon}" style="width:16px;height:16px"></i>`;
    renderIcons();
}

function setupDragBar(trackId, { onDrag, onRelease }) {
    const track = document.getElementById(trackId);
    if (!track) return;

    let dragging = false;

    function getPct(e) {
        const rect = track.getBoundingClientRect();
        return Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    }

    track.addEventListener('mousedown', (e) => {
        dragging = true;
        onDrag(getPct(e));
    });

    document.addEventListener('mousemove', (e) => {
        if (dragging) onDrag(getPct(e));
    });

    document.addEventListener('mouseup', (e) => {
        if (dragging) {
            dragging = false;
            onRelease(getPct(e));
        }
    });
}

function api(method, ...args) {
    if (window.pywebview && window.pywebview.api) {
        return window.pywebview.api[method](...args);
    }
    return Promise.resolve(null);
}

export function setProgressFill(id, val) {
    const el = document.getElementById(id);
    if (!el) return;
    const pct = typeof val === 'number' ? val : parseFloat(val);
    if (!isNaN(pct)) {
        el.style.transform = `translateX(${pct - 100}%)`;
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
    if (el) el.textContent = text;
}
function setElHtml(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
}
function setElSrc(id, src) {
    const el = document.getElementById(id);
    if (el) {
        if (src && typeof src === 'string' && src.trim() !== '') {
            el.style.display = 'block';
            el.src = src;
            el.onerror = () => {
                if (el.src && el.src.includes('maxresdefault.jpg')) {
                    el.src = el.src.replace('maxresdefault.jpg', 'hqdefault.jpg');
                } else if (el.src && el.src.includes('sddefault.jpg')) {
                    el.src = el.src.replace('sddefault.jpg', 'hqdefault.jpg');
                } else {
                    el.style.display = 'none';
                }
            };
        } else {
            el.style.display = 'none';
        }
    }
}

// --- Waveform Scrubber Engine ---
let currentWaveformData = null;
let isWaveformScrubberActive = false;

// C-5: waveform render caches (color, element size) + skip-redraw helpers
let waveColorCache = { color: null, theme: null };

function getWaveColor() {
    const theme = document.documentElement.getAttribute('data-theme');
    if (waveColorCache.color === null || waveColorCache.theme !== theme) {
        waveColorCache.color = getComputedStyle(document.documentElement).getPropertyValue('--primary').trim() || '#3b82f6';
        waveColorCache.theme = theme;
    }
    return waveColorCache.color;
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
    });
});

export async function fetchAndRenderWaveform(track) {
    currentWaveformData = null;
    const sliderType = localStorage.getItem('nedotify_player_slider_type') || 'default';
    const isWaveMode = sliderType === 'wave';
    
    const pbCanvas = document.getElementById('pb-waveform-canvas');
    const ppCanvas = document.getElementById('pp-waveform-canvas');
    
    if (!isWaveMode) {
        if (pbCanvas) pbCanvas.classList.add('hidden');
        if (ppCanvas) ppCanvas.classList.add('hidden');
        isWaveformScrubberActive = false;
        return;
    }

    if (pbCanvas) pbCanvas.classList.remove('hidden');
    if (ppCanvas) ppCanvas.classList.remove('hidden');
    isWaveformScrubberActive = true;

    if (!track) return;
    
    try {
        if (window.pywebview?.api?.get_waveform) {
            const peaks = await window.pywebview.api.get_waveform(track);
            if (peaks && peaks.length > 0) {
                currentWaveformData = peaks;
            } else {
                currentWaveformData = generatePseudoWaveform(track);
            }
            renderWaveforms(currentPosMs / (currentDuration || 1));
        }
    } catch(e) {
        currentWaveformData = generatePseudoWaveform(track);
        renderWaveforms(currentPosMs / (currentDuration || 1));
    }
}

function generatePseudoWaveform(track) {
    const seed = (track?.title || 'a').split('').reduce((acc, c) => acc + c.charCodeAt(0), 0);
    const peaks = [];
    for (let i = 0; i < 100; i++) {
        const val = 0.2 + 0.65 * Math.abs(Math.sin((i + seed) * 0.18) * Math.cos((i * 0.3) + seed));
        peaks.push(parseFloat(val.toFixed(3)));
    }
    return peaks;
}

export function renderWaveforms(progressPct = 0) {
    if (!isWaveformScrubberActive || !currentWaveformData) return;
    
    const pbCanvas = document.getElementById('pb-waveform-canvas');
    const ppCanvas = document.getElementById('pp-waveform-canvas');
    
    if (pbCanvas && !pbCanvas.classList.contains('hidden')) {
        drawWaveformToCanvas(pbCanvas, currentWaveformData, progressPct);
    }
    if (ppCanvas && !ppCanvas.classList.contains('hidden')) {
        drawWaveformToCanvas(ppCanvas, currentWaveformData, progressPct);
    }
}

function drawWaveformToCanvas(canvas, peaks, progressPct) {
    if (!canvas || !peaks || peaks.length === 0) return;
    const ctx = canvas.getContext('2d');

    // C-5: cached element size (invalidated on window resize / track change)
    const parent = canvas.parentElement;
    let w = canvas._wfW;
    if (w === undefined) {
        w = canvas._wfW = parent.clientWidth || 300;
    }
    let h = canvas._wfH;
    if (h === undefined) {
        h = canvas._wfH = parent.clientHeight || 20;
    }

    if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
        canvas._wfPlayed = -1;
        canvas._wfStatic = false;
    }

    const numBars = Math.min(peaks.length, Math.floor(w / 4));
    const playedCount = Math.round(progressPct * numBars);
    const isPerfLow = document.documentElement.classList.contains('perf-low');

    // C-5: skip redraw unless the played bar boundary moved (>=1px granularity)
    if (!isPerfLow && canvas._wfPlayed === playedCount && canvas._wfPeaks === peaks) return;
    // C-5: perf-low renders a static wave once; progress is shown by the slider overlay
    if (isPerfLow && canvas._wfStatic) return;

    canvas._wfPeaks = peaks;
    canvas._wfPlayed = playedCount;
    if (isPerfLow) canvas._wfStatic = true;

    ctx.clearRect(0, 0, w, h);

    const barWidth = Math.max(2, (w / numBars) - 1.5);
    const primaryColor = getWaveColor();
    const dimColor = 'rgba(255, 255, 255, 0.25)';

    for (let i = 0; i < numBars; i++) {
        const peakIdx = Math.floor((i / numBars) * peaks.length);
        const amp = Math.max(0.15, peaks[peakIdx] || 0.2);
        const barHeight = Math.max(3, amp * (h - 4));
        const x = i * (barWidth + 1.5);
        const y = (h - barHeight) / 2;

        const isPlayed = !isPerfLow && (i / numBars) <= progressPct;
        ctx.fillStyle = isPlayed ? primaryColor : dimColor;
        
        ctx.beginPath();
        if (ctx.roundRect) {
            ctx.roundRect(x, y, barWidth, barHeight, 2);
        } else {
            ctx.rect(x, y, barWidth, barHeight);
        }
        ctx.fill();
    }
}

document.addEventListener('nedotify:slider_type_changed', () => {
    fetchAndRenderWaveform(currentTrack);
});




