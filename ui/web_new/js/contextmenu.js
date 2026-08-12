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
        }
    });
}
