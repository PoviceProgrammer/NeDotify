export function initContextMenu() {
    document.addEventListener('contextmenu', (e) => {
        const trackItem = e.target.closest('.track-item, .album-track-item, .queue-item');
        if (trackItem && trackItem.dataset.track) {
            e.preventDefault();
            try {
                const track = JSON.parse(trackItem.dataset.track);
                if (window.NeDotify?.showTrackContextMenu) {
                    window.NeDotify.showTrackContextMenu(track, e);
                }
            } catch (err) {
                console.error("Failed to parse track data for context menu", err);
            }
        }
    });
}
