// Decode real audio only. Retain small envelopes, never encoded/decoded audio.
const BUCKETS = 600;
const CACHE_LIMIT = 24;
const FETCH_TIMEOUT_MS = 20000;
const MAX_AUDIO_BYTES = 24 * 1024 * 1024;
const MAX_DURATION_MS = 10 * 60 * 1000;
const MAX_QUEUED_JOBS = 2;

const peaksCache = new Map();
const pending = new Map();
const queue = [];
let activeJob = null;

function trackKey(track, url) {
    const id = track?.source_id ?? track?.id;
    const identity = id !== undefined && id !== null ? `${track?.source || ''}:${id}` : url;
    return identity ? `${identity}:${track?.duration_ms ?? track?.duration ?? ''}` : '';
}

function readCache(key) {
    const peaks = peaksCache.get(key);
    if (peaks) {
        peaksCache.delete(key);
        peaksCache.set(key, peaks);
    }
    return peaks || null;
}

// Equal time intervals cover the entire recording, including its final sample.
// Taking the maximum across channels avoids cancelling opposite-phase stereo.
export function audioBufferToPeaks(audio, bucketCount = BUCKETS) {
    if (!audio?.length || !audio.numberOfChannels || !Number.isInteger(bucketCount) || bucketCount < 1) return null;
    const channels = Array.from({ length: audio.numberOfChannels }, (_, i) => audio.getChannelData(i));
    const peaks = new Array(bucketCount).fill(0);
    let norm = 0;
    for (let i = 0; i < bucketCount; i++) {
        const start = Math.floor(i * audio.length / bucketCount);
        const end = Math.min(audio.length, Math.max(start + 1, Math.floor((i + 1) * audio.length / bucketCount)));
        let peak = 0;
        for (const samples of channels) {
            for (let j = start; j < end; j++) {
                const value = Math.abs(samples[j]);
                if (Number.isFinite(value) && value > peak) peak = value;
            }
        }
        peaks[i] = peak;
        if (peak > norm) norm = peak;
    }
    return norm ? peaks.map(peak => peak / norm) : peaks;
}

async function cancelBody(response) {
    try { await response.body?.cancel(); } catch (_) { /* already aborted/locked */ }
}

async function readAudioBytes(response, signal) {
    const size = Number(response.headers?.get('content-length'));
    if (size > MAX_AUDIO_BYTES) {
        await cancelBody(response);
        return null;
    }
    if (!response.body?.getReader) {
        // Without a stream reader a length is required before allocation.
        if (!Number.isFinite(size) || size <= 0) return null;
        const bytes = await response.arrayBuffer();
        return !signal.aborted && bytes.byteLength <= MAX_AUDIO_BYTES ? bytes : null;
    }
    const reader = response.body.getReader();
    const chunks = [];
    let total = 0;
    try {
        while (!signal.aborted) {
            const { done, value } = await reader.read();
            if (done) {
                const bytes = new Uint8Array(total);
                let offset = 0;
                for (const chunk of chunks) {
                    bytes.set(chunk, offset);
                    offset += chunk.byteLength;
                }
                return bytes.buffer;
            }
            total += value.byteLength;
            if (total > MAX_AUDIO_BYTES) return null;
            chunks.push(value);
        }
        return null;
    } finally {
        try { await reader.cancel(); } catch (_) { /* fetch abort already closed it */ }
        reader.releaseLock();
    }
}

async function computePeaks(job) {
    const signal = job.controller.signal;
    const OfflineCtx = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    const LiveCtx = window.AudioContext || window.webkitAudioContext;
    if (!OfflineCtx && !LiveCtx) return null;
    let ctx;
    const timer = setTimeout(() => job.controller.abort(), FETCH_TIMEOUT_MS);
    try {
        const response = await fetch(job.url, { signal });
        if (!response.ok || signal.aborted) {
            await cancelBody(response);
            return null;
        }
        const bytes = await readAudioBytes(response, signal);
        if (!bytes || signal.aborted) return null;
        ctx = OfflineCtx ? new OfflineCtx(1, 1, 44100) : new LiveCtx();
        const audio = await ctx.decodeAudioData(bytes);
        if (signal.aborted || audio.duration * 1000 > MAX_DURATION_MS) return null;
        return audioBufferToPeaks(audio);
    } catch (_) {
        return null;
    } finally {
        clearTimeout(timer);
        try { await ctx?.close?.(); } catch (_) { /* offline contexts need no close */ }
    }
}

function settleJob(job, peaks) {
    for (const consumer of job.consumers) consumer.finish(peaks);
    job.consumers.clear();
}

function pumpQueue() {
    if (activeJob) return;
    const job = queue.shift();
    if (!job) return;
    if (job.controller.signal.aborted) {
        pumpQueue();
        return;
    }
    activeJob = job;
    computePeaks(job).catch(() => null).then(peaks => {
        if (!job.controller.signal.aborted && peaks) {
            peaksCache.set(job.key, peaks);
            if (peaksCache.size > CACHE_LIMIT) peaksCache.delete(peaksCache.keys().next().value);
        }
        if (pending.get(job.key) === job) pending.delete(job.key);
        settleJob(job, job.controller.signal.aborted ? null : peaks);
    }).finally(() => {
        if (pending.get(job.key) === job) pending.delete(job.key);
        activeJob = null;
        pumpQueue();
    });
}

function subscribe(job, signal) {
    return new Promise(resolve => {
        const consumer = {
            finish(value) {
                signal?.removeEventListener('abort', abort);
                job.consumers.delete(consumer);
                resolve(value);
            },
        };
        const abort = () => {
            consumer.finish(null);
            if (job.consumers.size) return;
            job.controller.abort();
            if (pending.get(job.key) === job) pending.delete(job.key);
            const index = queue.indexOf(job);
            if (index >= 0) queue.splice(index, 1);
        };
        job.consumers.add(consumer);
        signal?.addEventListener('abort', abort, { once: true });
        if (signal?.aborted) abort();
    });
}

export function fetchRealPeaks(track, { signal, url = track?.stream_url } = {}) {
    if (signal?.aborted || typeof url !== 'string' || !url || track?.duration_ms > MAX_DURATION_MS) return Promise.resolve(null);
    const key = trackKey(track, url);
    const cached = readCache(key);
    if (cached) return Promise.resolve(cached);
    let job = pending.get(key);
    if (!job) {
        if (queue.length >= MAX_QUEUED_JOBS) return Promise.resolve(null);
        job = { key, url, controller: new AbortController(), consumers: new Set() };
        job.controller.signal.addEventListener('abort', () => settleJob(job, null), { once: true });
        pending.set(key, job);
        queue.push(job);
    }
    const result = subscribe(job, signal);
    pumpQueue();
    return result;
}

export function peekCachedPeaks(track, { url = track?.stream_url } = {}) {
    return readCache(trackKey(track, url));
}
