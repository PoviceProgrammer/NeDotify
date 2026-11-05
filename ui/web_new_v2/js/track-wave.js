// A wave owns one listening session. Every refill is tied to that session and
// to the live queue; replacing the queue always wins over a late recommendation.
const LOW_WATER = 5;
const BATCH_SIZE = 15;
const RECENT_LIMIT = 200;
const keyText = value => String(value || '').normalize('NFKC').toLocaleLowerCase().replace(/\s+/g, ' ').trim();
const contentKey = track => `${keyText(track?.artist)}:${keyText(track?.title)}`;
let sessionSequence = 0;

export function createTrackWaveController({api, awaitBridge = async () => {}, onChange = () => {},
    toast = () => {}, setTimer = setTimeout, clearTimer = clearTimeout}) {
    let session = null;
    let requestSequence = 0;
    const state = () => ({active: !!session, status: session?.status || 'off',
        title: session?.seed.title || '', upcoming: session?.upcoming || 0});
    const publish = () => onChange(state());
    const cancelRequest = current => {
        if (current?.pending) clearTimer(current.pending.timer);
        if (current) current.pending = null;
    };
    const stop = () => {
        cancelRequest(session);
        session = null;
        publish();
    };
    const fail = (current, message) => {
        if (session !== current) return;
        cancelRequest(current);
        current.status = 'waiting';
        publish();
        if (message) toast(message, 'warning');
    };
    const remember = (current, tracks) => {
        for (const track of tracks) {
            const key = contentKey(track);
            current.recent.delete(key);
            current.recent.set(key, track);
        }
        while (current.recent.size > RECENT_LIMIT) current.recent.delete(current.recent.keys().next().value);
    };
    const owns = (current, snapshot) => {
        const tracks = snapshot?.tracks || [];
        return tracks.length > 0 && tracks.some(track => track._wave_session === current.token ||
            (track.entry_id && current.entries.has(track.entry_id)));
    };
    const acceptQueue = (current, snapshot) => {
        if (session !== current) return false;
        if (!owns(current, snapshot)) { stop(); return false; }
        current.snapshot = snapshot;
        current.entries = new Set(snapshot.tracks.map(track => track.entry_id).filter(Boolean));
        current.upcoming = Math.max(0, snapshot.tracks.length - Math.max(0, snapshot.current_index + 1));
        remember(current, [...(snapshot.history || []), ...snapshot.tracks.slice(0, snapshot.current_index + 1)]);
        publish();
        return true;
    };
    const exclusions = current => {
        const ids = new Set();
        // Recent first, then the live queue: retain the whole live queue up to
        // the bridge limit even after a long listening session.
        for (const track of [...current.recent.values(), ...(current.snapshot?.tracks || [])]) {
            for (const id of [track.id, track.source_id, contentKey(track)]) {
                if (id !== undefined && id !== null && id !== '') {
                    ids.delete(String(id));
                    ids.add(String(id));
                }
            }
        }
        return [...ids].slice(-1000);
    };
    const allowed = (current, track) => track && !current.blockedTracks.has(contentKey(track)) &&
        !current.blockedArtists.has(keyText(track.artist));
    const continuationTracks = current => {
        const artists = new Set();
        const played = (current.snapshot?.tracks || []).slice(0, current.snapshot.current_index + 1).reverse();
        return played.filter(track => {
            const artist = keyText(track.artist);
            if (track._wave_session !== current.token || track.recommendation_origin !== 'wave' ||
                !(Number(track.recommendation_relevance) >= .5) || !allowed(current, track) ||
                contentKey(track) === contentKey(current.seed) || !artist || artists.has(artist)) return false;
            artists.add(artist);
            return true;
        }).slice(0, 2).map(track => Object.fromEntries(
            ['id', 'source', 'source_id', 'title', 'artist', 'duration', 'recommendation_origin', 'recommendation_seed_artists', 'recommendation_relevance']
                .filter(field => track[field] !== undefined).map(field => [field, track[field]])));
    };

    async function requestRefill(current, force = false) {
        if (session !== current || current.starting || current.pending || current.adjusting ||
            (!force && (current.status === 'waiting' || current.upcoming > LOW_WATER))) return;
        const requestId = `${current.token}:${++requestSequence}`;
        const pending = {requestId, timer: null};
        current.pending = pending;
        current.status = 'loading';
        publish();
        pending.timer = setTimer(() => {
            if (session === current && current.pending === pending) fail(current, 'Волна пока не загрузилась. Можно повторить в очереди');
        }, 25000);
        try {
            if (!api()?.get_track_wave) throw new Error('Wave bridge unavailable');
            await api().get_track_wave(current.seed, BATCH_SIZE, exclusions(current), requestId,
                continuationTracks(current));
        } catch {
            if (current.pending === pending) fail(current, 'Не удалось продолжить волну. Можно повторить в очереди');
        }
    }

    async function start(seed) {
        if (!seed || !seed.title) return;
        stop();
        const token = `wave-${Date.now()}-${++sessionSequence}`;
        const current = {token, seed: {...seed, _wave_session: token}, status: 'loading', starting: true,
            entries: new Set(), recent: new Map(), blockedTracks: new Set(), blockedArtists: new Set(),
            upcoming: 0, snapshot: null, pending: null, ended: false, adjusting: false};
        session = current;
        remember(current, [seed]);
        publish();
        try {
            await awaitBridge();
            if (session !== current) return;
            if (!api()?.play_track || !api()?.get_queue || !api()?.add_tracks_to_queue) throw new Error('Queue bridge unavailable');
            const result = await api().play_track(current.seed, [current.seed], 0);
            if (session !== current) return;
            if (result === false || result?.success === false) throw new Error('Play rejected');
            const snapshot = await api().get_queue();
            if (!acceptQueue(current, snapshot)) return;
            current.starting = false;
            await requestRefill(current, true);
        } catch {
            if (session !== current) return;
            stop();
            toast('Не удалось запустить волну', 'error');
        }
    }

    async function receiveTracks(current, data) {
        const pending = current.pending;
        if (!pending || pending.receiving || data?.request_id !== pending.requestId) return;
        pending.receiving = true;
        if (data.error) { fail(current, 'Не удалось продолжить волну. Можно повторить в очереди'); return; }
        try {
            // Fetch immediately before append, then let the backend compare its
            // revision/current entry under the playback lock.
            const snapshot = await api().get_queue();
            if (session !== current || current.pending !== pending || !acceptQueue(current, snapshot)) return;
            const seen = new Set([...current.recent.keys(), ...snapshot.tracks.map(contentKey)]);
            const tracks = (Array.isArray(data.tracks) ? data.tracks : []).filter(track => {
                if (!allowed(current, track) || !track.title) return false;
                const key = contentKey(track);
                if (seen.has(key)) return false;
                seen.add(key);
                return true;
            }).slice(0, BATCH_SIZE).map(track => ({...track, _wave_session: current.token, recommendation_origin: 'wave'}));
            if (!tracks.length) { fail(current, 'Похожие треки пока закончились. Можно обновить волну в очереди'); return; }
            const playing = snapshot.tracks[snapshot.current_index];
            const result = await api().add_tracks_to_queue(tracks, playing?.entry_id ?? null, snapshot.queue_revision ?? null);
            if (session !== current || current.pending !== pending) return;
            if (result === false || result?.success === false) throw new Error('Queue changed before append');
            remember(current, tracks);
            cancelRequest(current);
            current.status = 'ready';
            const live = await api().get_queue();
            if (!acceptQueue(current, live)) return;
            if (current.ended) {
                current.ended = false;
                // Resume only after a natural queue end, never after Pause.
                await api().next_track?.();
            }
        } catch {
            if (current.pending === pending) fail(current, 'Не удалось добавить продолжение. Повторите в очереди');
        }
    }

    async function handlePythonEvent(name, data) {
        const current = session;
        if (!current) return;
        if (name === 'track_wave_ready') await receiveTracks(current, data);
        else if (name === 'queue_updated') {
            if (acceptQueue(current, data)) await requestRefill(current);
        } else if (name === 'track_changed') {
            if (data?.entry_id && !current.entries.has(data.entry_id) && data._wave_session !== current.token) stop();
        } else if (name === 'queue_ended') {
            current.ended = true;
            await requestRefill(current);
        } else if (name === 'state_changed' && (data?.state || data) === 'paused') current.ended = false;
    }

    async function retry() {
        const current = session;
        if (!current || current.pending || current.adjusting) return;
        try {
            const snapshot = await api().get_queue();
            if (acceptQueue(current, snapshot)) await requestRefill(current, true);
        } catch { fail(current); }
    }

    async function adjustFuture(current, predicate) {
        if (session !== current) return;
        cancelRequest(current);
        current.adjusting = true;
        current.status = 'loading';
        publish();
        try {
            const snapshot = await api().get_queue();
            if (!acceptQueue(current, snapshot)) return;
            // Remove only generated upcoming entries. Explicit user additions
            // and the playing track retain their place.
            for (let index = snapshot.tracks.length - 1; index > snapshot.current_index; index--) {
                const track = snapshot.tracks[index];
                if (session !== current) return;
                if (track._wave_session === current.token && predicate(track)) {
                    const result = await api().remove_from_queue(index, track.entry_id ?? null);
                    if (result === false || result?.success === false) throw new Error('Queue changed');
                }
            }
            const live = await api().get_queue();
            if (!acceptQueue(current, live)) return;
            current.adjusting = false;
            current.status = 'ready';
            await requestRefill(current);
        } catch { fail(current); }
        finally { current.adjusting = false; publish(); }
    }

    function refreshFuture(predicate = () => true) {
        const current = session;
        if (!current) return Promise.resolve();
        // Mode changes and feedback can arrive while removals are awaiting the
        // bridge. Apply them serially so indices never race each other.
        current.adjustments = (current.adjustments || Promise.resolve()).then(() => adjustFuture(current, predicate));
        return current.adjustments;
    }

    async function feedbackChanged({track, kind} = {}) {
        const current = session;
        if (!current || !track) return;
        try {
            const feedback = await api().get_recommendation_feedback(track);
            if (session !== current) return;
            const keys = kind === 'artist' ? current.blockedArtists : current.blockedTracks;
            const key = kind === 'artist' ? keyText(track.artist) : contentKey(track);
            if (feedback?.[kind]) keys.add(key); else keys.delete(key);
            await refreshFuture(candidate => !allowed(current, candidate));
        } catch { fail(current); }
    }
    return {start, stop, retry, state, handlePythonEvent, feedbackChanged, refreshFuture};
}

let controller = null;
const getController = () => controller ||= createTrackWaveController({
    api: () => window.pywebview?.api, awaitBridge: () => window.awaitBridge(),
    onChange: detail => window.dispatchEvent(new CustomEvent('nedotify:track_wave_state_changed', {detail})),
    toast: (msg, type) => window.dispatchEvent(new CustomEvent('nedotify:toast', {detail: {msg, type}})),
});
export const startTrackWave = seed => getController().start(seed);
export const stopTrackWave = () => getController().stop();
export const retryTrackWave = () => getController().retry();
export const getTrackWaveState = () => getController().state();
let initialized = false;
export function initTrackWave(subscribe) {
    if (initialized) return;
    initialized = true;
    const wave = getController();
    subscribe((name, data) => { wave.handlePythonEvent(name, data).catch(() => wave.stop()); });
    window.addEventListener('nedotify:recommendation_feedback_changed', event => { void wave.feedbackChanged(event.detail); });
    window.addEventListener('nedotify:recommendation_mode_changed', () => { void wave.refreshFuture(); });
    window.addEventListener('pagehide', () => wave.stop(), {once: true});
}
