// NeDotify Р Р†Р вЂљ" Player Module
import { formatTime, renderIcons, showToast, getCoverUrl, extractDominantColor } from './utils.js?v=19';

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

// Dual Audio Engine for Crossfade
let audioA = new Audio();
audioA.crossOrigin = "anonymous";
let audioB = new Audio();
audioB.crossOrigin = "anonymous";
let activeAudio = audioA;

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

// Sync time updates to UI
function setupAudioEvents(audio) {
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
        if (audio === activeAudio) {
            console.warn('Audio stream playback error, retrying...', e);
            audio._errorRetries = (audio._errorRetries || 0) + 1;
            if (audio._errorRetries <= 3 && currentTrack) {
                setTimeout(() => {
                    if (window.pywebview?.api?.play_track) {
                        window.pywebview.api.play_track(currentTrack);
                    }
                }, 1000 * audio._errorRetries);
            } else {
                window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Ошибка воспроизведения потока', type: 'error' } }));
                api('next_track');
            }
        }
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

export function playTrack(track, streamUrl) {
    if (!track || !streamUrl) return;
    
    if (audioCtx && audioCtx.state === 'suspended') {
        audioCtx.resume().catch(() => {});
    }
    
    updateMediaSession(track);
    
    const newAudio = activeAudio === audioA ? audioB : audioA;
    const oldAudio = activeAudio;
    
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
    
    newAudio.src = finalSrc;
    newAudio.volume = 0;
    newAudio.play().catch(e => console.error("Audio play error:", e));
    
    activeAudio = newAudio;
    isPlaying = true;
    onStateChanged('playing');
    
    // Smooth Crossfade
    const fadeMs = 2000;
    const steps = 20;
    const stepTime = fadeMs / steps;
    const targetVol = isMuted ? 0 : (currentVolume / 100) * currentReplayGain;
    
    let step = 0;
    const fadeInterval = setInterval(() => {
        step++;
        newAudio.volume = Math.min(targetVol, (step / steps) * targetVol);
        if (oldAudio && oldAudio.src) {
            oldAudio.volume = Math.max(0, targetVol - (step / steps) * targetVol);
        }
        
        if (step >= steps) {
            clearInterval(fadeInterval);
            if (oldAudio) {
                try { oldAudio.pause(); } catch(e) {}
                try { oldAudio.currentTime = 0; } catch(e) {}
                try { oldAudio.removeAttribute('src'); oldAudio.load(); } catch(e) {}
            }
            newAudio.volume = targetVol;
        }
    }, stepTime);
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
    if (window.pywebview?.api?.set_position) {
        try {
            window.pywebview.api.set_position(posMs);
        } catch (e) {}
    }
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

    if (mpPlay) mpPlay.addEventListener('click', togglePlayPause);
    if (mpStop) mpStop.addEventListener('click', stopPlayback);
    if (mpNext) mpNext.addEventListener('click', () => api('next_track'));
    if (mpPrev) mpPrev.addEventListener('click', () => api('prev_track'));

    if (mpLike) mpLike.addEventListener('click', async () => {
        if (!currentTrack) return;
        const res = await api('toggle_favorite', currentTrack);
        if (res && res.success) {
            currentTrack.is_favorite = res.is_favorite;
            updateLikeButtons();
        }
    });

    const mpMinimize = document.getElementById('mp-btn-minimize');
    const mpClose = document.getElementById('mp-btn-close');

    if (mpMinimize) mpMinimize.addEventListener('click', () => {
        if (window.pywebview?.api?.minimize) {
            window.pywebview.api.minimize();
        }
    });

    if (mpClose) mpClose.addEventListener('click', async () => {
        if (window.pywebview?.api?.close) {
            window.pywebview.api.close();
        } else {
            document.body.classList.remove('mini-player-active');
            if (window.pywebview?.api?.toggle_mini_player) {
                setTimeout(() => {
                    try { window.pywebview.api.toggle_mini_player(false); } catch(e) {}
                }, 50);
            }
        }
    });

    if (mpExpand) mpExpand.addEventListener('click', (e) => {
        e.stopPropagation();
        if (window.NeDotify?.toggleMiniPlayerMode) {
            window.NeDotify.toggleMiniPlayerMode(false);
        } else if (window.toggleMiniPlayerMode) {
            window.toggleMiniPlayerMode(false);
        }
    });

    const mpCard = document.getElementById('mini-player-overlay');
    if (mpCard) {
        let mpPressPos = null;
        mpCard.addEventListener('mousedown', (e) => {
            mpPressPos = { x: e.clientX, y: e.clientY };
            if (e.target.closest('button, input, select, a, .btn-ctrl, .icon-btn, .mp-progress-bar-wrap, .progress-track')) {
                return;
            }
            if (window.pywebview?.api?.start_drag) {
                window.pywebview.api.start_drag();
            }
        });

        mpCard.addEventListener('click', (e) => {
            if (e.target.closest('button, input, select, a, .btn-ctrl, .icon-btn, .mp-progress-bar-wrap, .progress-track')) {
                return;
            }
            // A real drag fires click too — don't toggle expanded after dragging.
            if (mpPressPos && (Math.abs(e.clientX - mpPressPos.x) > 5 || Math.abs(e.clientY - mpPressPos.y) > 5)) {
                mpPressPos = null;
                return;
            }
            mpPressPos = null;
            const targetExpanded = !mpCard.classList.contains('expanded');
            mpCard.classList.toggle('expanded', targetExpanded);
            mpCard.classList.remove('mp-pop-in', 'mp-pop-out');
            void mpCard.offsetWidth;
            mpCard.classList.add(targetExpanded ? 'mp-pop-in' : 'mp-pop-out');
            if (window.pywebview?.api?.resize_mini_window) {
                try {
                    window.pywebview.api.resize_mini_window(targetExpanded);
                } catch(err) {}
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
            api('set_volume', currentVolume);
        },
        onRelease: (pct) => {
            isDraggingVolume = false;
            currentVolume = Math.round(pct * 100);
            activeAudio.volume = isMuted ? 0 : (currentVolume / 100) * currentReplayGain;
            api('set_volume', currentVolume);
        }
    });

    window.NeDotify = window.NeDotify || {};
    window.NeDotify.adjustVolume = (delta) => {
        currentVolume = Math.max(0, Math.min(100, currentVolume + delta));
        setEl('pb-volume-fill', 'width', `${currentVolume}%`);
        updateVolumeIcon(currentVolume);
        if (activeAudio) activeAudio.volume = isMuted ? 0 : (currentVolume / 100) * currentReplayGain;
        api('set_volume', currentVolume);
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
                            btn.innerHTML = `<i data-lucide="list-music" style="width:14px;height:14px"></i> ${pl.name}`;
                            btn.addEventListener('click', async () => {
                                await api('add_to_playlist', plId, currentTrack);
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

    if (!isDraggingProgress && activeAudio && currentDuration > 0) {
        currentPosMs = Math.round(activeAudio.currentTime * 1000);
        const pct = Math.max(0, Math.min(100, (currentPosMs / currentDuration) * 100));
        if (!isFinite(pct)) return;

        const pctStr   = `${pct.toFixed(2)}%`;
        const timeStr  = formatTime(currentPosMs / 1000);
        const els = _getProgEls();

        const txVal = `translateX(${pct - 100}%)`;
        if (els.pbFill) els.pbFill.style.transform = txVal;
        if (els.ppFill) els.ppFill.style.transform = txVal;
        if (els.mpFill) els.mpFill.style.transform = txVal;
        if (els.pbTime) els.pbTime.textContent = timeStr;
        if (els.ppTime) els.ppTime.textContent = timeStr;
        if (els.mpTime) els.mpTime.textContent = timeStr;

        // Gapless preloading & Crossfade triggers
        const remainingSec = (currentDuration - currentPosMs) / 1000;
        if (remainingSec <= 15 && !window._isPreloadingNextTrack) {
            window._isPreloadingNextTrack = true;
            if (window.pywebview?.api?.get_next_track) {
                window.pywebview.api.get_next_track().then(nextTrack => {
                    if (nextTrack && nextTrack.stream_url) {
                        const inactiveAudio = activeAudio === audioA ? audioB : audioA;
                        if (inactiveAudio.src !== nextTrack.stream_url) {
                            inactiveAudio.src = nextTrack.stream_url;
                            inactiveAudio.load();
                        }
                    }
                }).catch(() => {}).finally(() => {
                    setTimeout(() => { window._isPreloadingNextTrack = false; }, 10000);
                });
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
        playTrack(track, track.stream_url);
    } else if (track.file_path) {
        playTrack(track, track.file_path);
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
            }
        };
        setElSrc('pb-cover', coverUrl);
    }

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
        el.innerHTML = `<span class="mp-marquee-span">${text || ''}</span>`;
        
        const updateMarquee = () => {
            const span = el.querySelector('.mp-marquee-span');
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
        
        if (durationMs > 0) {
            currentDuration = durationMs;
        }
        targetPosMs = posMs;

        // If audio is actively playing in HTML5 Audio, let animateProgress handle smooth frame updates
        if (isPlaying && activeAudio && !activeAudio.paused) {
            return;
        }

        if (!isDraggingProgress && currentDuration > 0) {
            const pct = Math.max(0, Math.min(100, (posMs / currentDuration) * 100));
            if (isFinite(pct)) {
                const txVal = `translateX(${pct - 100}%)`;
                const els = _getProgEls();
                if (els.pbFill) els.pbFill.style.transform = txVal;
                if (els.ppFill) els.ppFill.style.transform = txVal;
                if (els.mpFill) els.mpFill.style.transform = txVal;
            }
            const timeStr = formatTime(posMs / 1000);
            const els = _getProgEls();
            if (els.pbTime) els.pbTime.textContent = timeStr;
            if (els.ppTime) els.ppTime.textContent = timeStr;
            if (els.mpTime) els.mpTime.textContent = timeStr;
        }
    } catch(e) {
        alert("Player onPositionChanged Error: " + e.message);
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



