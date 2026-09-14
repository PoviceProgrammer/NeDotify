export function initContextMenu() {
    document.addEventListener('contextmenu', (e) => {
        const trackItem = e.target.closest('.track-item, .album-track-item, .queue-item');
        if (trackItem) {
            let track = trackItem._trackData;
            if (!track && trackItem.dataset.track) {
                try {
                    track = JSON.parse(trackItem.dataset.track);
                } catch (err) {}
            }
            if (track && window.NeDotify?.showTrackContextMenu) {
                e.preventDefault();
                window.NeDotify.showTrackContextMenu(track, e);
            }
            return;
        }

        const playlistItem = e.target.closest('.playlist-card, .sidebar-playlist-item, .lib-playlist-item');
        if (playlistItem) {
            let playlist = playlistItem._playlistData;
            if (!playlist && playlistItem.dataset.playlist) {
                try {
                    playlist = JSON.parse(playlistItem.dataset.playlist);
                } catch (err) {}
            }
            if (!playlist) {
                playlist = {
                    id: playlistItem.dataset.plId || playlistItem.dataset.id || '',
                    name: playlistItem.dataset.title || playlistItem.querySelector('.truncate, .feed-card-title, .playlist-title')?.textContent?.trim() || 'Плейлист',
                    source: playlistItem.dataset.source || 'youtube',
                    source_id: playlistItem.dataset.sourceId || playlistItem.dataset.plId || playlistItem.dataset.id || ''
                };
            }
            if (playlist) {
                if (window.NeDotify?.showPlaylistContextMenu) {
                    e.preventDefault();
                    window.NeDotify.showPlaylistContextMenu(playlist, e);
                } else if (window.showPlaylistContextMenu) {
                    e.preventDefault();
                    window.showPlaylistContextMenu(playlist, e);
                }
            }
        }
    });
}

