"""
NeDotify - Entry Point
Desktop audio player with modern dark UI, streaming integration,
and advanced customization. (PyWebView Edition)
"""

import sys
import os
import webview

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    pass

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# Migrate secrets to AppData on launch
from core.app import AppCore
from core.api import AppApi

def main():
    """Application entry point."""
    print("Starting NeDotify...")


    # Initialize application core
    app_core = AppCore()

    # Initialize API bridge
    api = AppApi(app_core)

    # Restore session state
    try:
        session_data = app_core.session.restore_session()
        queue = session_data.get("queue")
        if queue:
            app_core.engine.queue.set_tracks(queue, session_data.get("queue_index", 0))
            app_core.engine.queue.shuffle = session_data.get("shuffle", False)
            app_core.engine.queue.repeat = session_data.get("repeat", "off")
            
            # Always notify UI about the restored track so it displays it
            if app_core.engine.queue.current_track and hasattr(app_core.engine, '_on_track_changed') and app_core.engine._on_track_changed:
                app_core.engine._on_track_changed(app_core.engine.queue.current_track)

            # If autoplay is enabled, start playback
            if app_core.session.should_autoplay and app_core.engine.queue.current_track:
                pass
    except Exception as e:
        print(f"Failed to restore session: {e}")

    # Get absolute path to index.html
    if hasattr(sys, '_MEIPASS'):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    
    html_path = os.path.join(base_dir, "ui", "web_new", "index.html")

    # Transparency flag (opaque fallback)
    is_transparent = app_core.settings.get("theme", "transparency_enabled", False)

    # Create main app window (solid dark background, 100% stable, no white box)
    window = webview.create_window(
        "NeDotify",
        url=html_path,
        js_api=api,
        width=1100,
        height=800,
        min_size=(100, 40),
        frameless=True,
        fullscreen=False,
        transparent=is_transparent,
        background_color='#000000' if is_transparent else '#0f0f14',
        easy_drag=False
    )

    # Pass window reference to api
    api.set_window(window)

    def on_loaded():
        if app_core.engine.queue.current_track:
            app_core.engine._on_track_changed(app_core.engine.queue.current_track)
            
    window.events.loaded += on_loaded

    # Start the application loop (debug=False to disable DevTools)
    webview.start(http_server=True, debug=False)

    # Save session before exit
    try:
        engine = app_core.engine
        app_volume = app_core.settings.get("audio", "volume", 70)
        app_core.session.save_session(
            track_id=engine.queue.current_track.get("id") if engine.queue.current_track else None,
            position=getattr(engine, '_last_reported_position', 0),
            volume=app_volume,
            queue=engine.queue.tracks,
            queue_index=engine.queue._current_index,
            shuffle=engine.queue.shuffle,
            repeat=engine.queue.repeat
        )
    except Exception as e:
        print(f"Failed to save session: {e}")

    # Cleanup after window closed
    app_core.cleanup()
    sys.exit(0)

if __name__ == "__main__":
    main()
