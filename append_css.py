# CSS Extensions for NeDotify 2.0

css_append = """
/* ========================================================
   NEODOTIFY 2.0 : GLASSMORPHISM & ANIMATIONS
   ======================================================== */

/* 1. GLASSMORPHISM */
.sidebar, .playback-bar, .top-bar, .context-menu, .modal-content {
    background: rgba(18, 18, 18, 0.6) !important;
    backdrop-filter: blur(25px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(25px) saturate(180%) !important;
    border: 1px solid rgba(255, 255, 255, 0.05);
}

/* Let the main background show through if there are elements behind */
body {
    background: linear-gradient(135deg, #0f0f0f 0%, #1a1a1a 100%) !important;
}

/* 2. MICRO-ANIMATIONS */
.track-item, .album-card, .artist-card {
    transition: transform 0.3s cubic-bezier(0.25, 0.8, 0.25, 1), background 0.2s ease, box-shadow 0.3s ease !important;
}

.track-item:hover {
    transform: translateX(5px) !important;
}

.album-card:hover, .artist-card:hover {
    transform: scale(1.05) translateY(-5px) !important;
    box-shadow: 0 15px 30px rgba(0,0,0,0.4) !important;
}

button, .icon-btn, .play-btn {
    transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.2s, background 0.2s !important;
}

button:active, .icon-btn:active, .play-btn:active {
    transform: scale(0.9) !important;
}

/* 3. SKELETON LOADERS */
@keyframes shimmer {
    0% { background-position: -1000px 0; }
    100% { background-position: 1000px 0; }
}

.skeleton {
    animation: shimmer 2s infinite linear;
    background: linear-gradient(to right, rgba(255,255,255,0.05) 4%, rgba(255,255,255,0.1) 25%, rgba(255,255,255,0.05) 36%);
    background-size: 1000px 100%;
    border-radius: 4px;
}

.skeleton-text {
    height: 14px;
    margin-bottom: 8px;
    border-radius: 4px;
}

.skeleton-cover {
    width: 48px;
    height: 48px;
    border-radius: 4px;
}

/* 4. MINI-PLAYER COMPACT MODE */
@media (max-width: 768px) {
    .playback-bar {
        padding: 8px 12px !important;
    }
    .pb-left .track-info .track-artist {
        display: none !important;
    }
    .pb-center .pb-controls {
        gap: 12px !important;
    }
    .pb-right {
        display: none !important;
    }
    .sidebar {
        width: 60px !important;
    }
    .sidebar span, .sidebar-logo span {
        display: none !important;
    }
}

/* 5. QUEUE DRAWER */
#queue-drawer {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 90px; /* above playback bar */
    width: 350px;
    background: rgba(18, 18, 18, 0.85);
    backdrop-filter: blur(30px);
    border-left: 1px solid rgba(255, 255, 255, 0.05);
    transform: translateX(100%);
    transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1);
    z-index: 1000;
    display: flex;
    flex-direction: column;
    box-shadow: -10px 0 30px rgba(0,0,0,0.5);
}

#queue-drawer.open {
    transform: translateX(0);
}

#queue-drawer-header {
    padding: 20px;
    border-bottom: 1px solid rgba(255,255,255,0.1);
    display: flex;
    justify-content: space-between;
    align-items: center;
}

#queue-drawer-header h2 {
    margin: 0;
    font-size: 18px;
}

#queue-drawer-content {
    flex: 1;
    overflow-y: auto;
    padding: 10px;
}

/* 6. KARAOKE LYRICS OVERLAY */
#lyrics-overlay {
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.85);
    backdrop-filter: blur(50px);
    z-index: 2000;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.5s ease;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    overflow: hidden;
}

#lyrics-overlay.active {
    opacity: 1;
    pointer-events: auto;
}

#lyrics-content {
    max-width: 800px;
    width: 100%;
    max-height: 70vh;
    overflow-y: auto;
    scrollbar-width: none;
    mask-image: linear-gradient(transparent, black 20%, black 80%, transparent);
    -webkit-mask-image: linear-gradient(transparent, black 20%, black 80%, transparent);
}

.lyric-line {
    font-size: 28px;
    font-weight: 700;
    color: rgba(255,255,255,0.3);
    margin: 20px 0;
    transition: color 0.3s ease, transform 0.3s ease;
    cursor: pointer;
}

.lyric-line.active {
    color: #fff;
    transform: scale(1.1);
    text-shadow: 0 0 20px rgba(255,255,255,0.5);
}

#lyrics-close {
    position: absolute;
    top: 30px;
    right: 30px;
    background: rgba(255,255,255,0.1);
    border: none;
    color: white;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
}

#lyrics-close:hover {
    background: rgba(255,255,255,0.2);
}

/* Context Menu */
#custom-context-menu {
    position: fixed;
    background: rgba(30, 30, 30, 0.95);
    backdrop-filter: blur(20px);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 8px;
    padding: 5px 0;
    min-width: 200px;
    z-index: 9999;
    box-shadow: 0 10px 30px rgba(0,0,0,0.5);
    opacity: 0;
    pointer-events: none;
    transform: scale(0.95);
    transition: opacity 0.2s, transform 0.2s;
}

#custom-context-menu.active {
    opacity: 1;
    pointer-events: auto;
    transform: scale(1);
}

.context-menu-item {
    padding: 10px 20px;
    color: #eee;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 10px;
    transition: background 0.2s;
}

.context-menu-item:hover {
    background: rgba(255,255,255,0.1);
}
"""

with open('ui/web_new/css/styles.css', 'a', encoding='utf-8') as f:
    f.write(css_append)

print("CSS appended successfully.")
