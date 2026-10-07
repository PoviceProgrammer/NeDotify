"""Deterministic in-page fixtures for the visual guard.

Design principle: the goldens must guard the *shipping* render code, so we do
not replace the UI. Instead we

* seed the real SQLite database (library + FTS5 search work fully offline), and
* dispatch the same synthetic bridge events the backend would emit, so the real
  event handlers and renderers execute against fixed data.

localStorage is seeded with ``Page.addScriptToEvaluateOnNewDocument`` so it is
in place *before* ``js/main.js`` runs its synchronous ``restorePreferences()``;
doing it afterwards would race the first paint.

Known, deliberate deviation: rAF-driven canvases (particle background,
visualizer) are hidden during capture. Their content depends on how many frames
elapsed before the shutter, which is not reproducible. Their *appearance* is
instead guarded by ``animation_declarations.json`` + the CSS declaration diff.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# localStorage seeding (runs before any page script)
# --------------------------------------------------------------------------
def localstorage_seed_script(theme: dict) -> str:
    import json
    payload = json.dumps(theme["localstorage"], ensure_ascii=False)
    return f"""
    (function () {{
      var cfg = {payload};
      try {{
        Object.keys(cfg).forEach(function (k) {{
          localStorage.setItem(k, cfg[k]);
        }});
        localStorage.setItem('aura_onboarding_done', 'true');
        localStorage.setItem('nedotify_general_first_launch_done', 'true');
        localStorage.setItem('nedotify_personalization_onboarding_completed', 'true');
      }} catch (e) {{}}
    }})();
    """


# --------------------------------------------------------------------------
# capture-mode styling: freeze anything that is time-dependent
# --------------------------------------------------------------------------
CAPTURE_CSS = """
/* injected by tools/visual_guard - capture determinism only */
*, *::before, *::after {
  caret-color: transparent !important;
  scroll-behavior: auto !important;
  animation-play-state: paused !important;
}
html, body { cursor: default !important; }
/* rAF-driven canvases have no reproducible content; hidden in every capture */
#particles-bg, #visualizer-canvas, #player-visualizer,
canvas[data-bench-volatile] { visibility: hidden !important; }
/* freeze the karaoke/lyrics clock */
.lyrics-line, .lyric-line { transition: none !important; }
"""


def apply_capture_mode_js() -> str:
    return """
    (function () {
      if (!document.getElementById('__bench_capture_css')) {
        var s = document.createElement('style');
        s.id = '__bench_capture_css';
        s.textContent = %s;
        (document.head || document.documentElement).appendChild(s);
      }
      return true;
    })();
    """ % (repr(CAPTURE_CSS).replace("'", '"'),)


# --------------------------------------------------------------------------
# fixture payloads
# --------------------------------------------------------------------------
def _track(i: int) -> dict:
    return {
        "id": i,
        "title": f"Fixture Track {i:03d}",
        "artist": f"Fixture Artist {i % 12:02d}",
        "album": f"Fixture Album {i % 7:02d}",
        "duration": 150.0 + (i % 90),
        "source": ["local", "youtube", "soundcloud", "spotify"][i % 4],
        "source_id": f"fixture-{i:05d}",
        "cover_url": None,
        "cover_path": None,
        "is_favorite": bool(i % 17 == 0),
        "is_downloaded": bool(i % 29 == 0),
        "play_count": i % 40,
        "genre": ["pop", "rock", "electronic", "jazz"][i % 4],
        "year": 2015 + (i % 10),
        "track_number": (i % 12) + 1,
    }


TRACKS = [_track(i) for i in range(1, 41)]

QUEUE = {
    "tracks": TRACKS[:12],
    "index": 2,
    "current": TRACKS[2],
    "is_playing": True,
    "shuffle": False,
    "repeat": "off",
}

LYRICS_TEXT = "\n".join([
    "First line of the fixture lyric sheet",
    "A second line that should be highlighted",
    "Third line, plain",
    "Fourth line arrives a little later",
    "Fifth line closes the fixture",
])

LYRICS_PAYLOAD = {
    "status": "ok",
    "lyrics": LYRICS_TEXT,
    "track_name": TRACKS[2]["title"],
    "artist_name": TRACKS[2]["artist"],
    "translated": None,
    "offset_ms": 0,
    "synced": False,
    "source": "fixture",
}

ARTIST_PAYLOAD = {
    "status": "ok",
    "artist": {
        "name": "Fixture Artist",
        "image": None,
        "subscribers": "1.2M",
        "bio": "Fixture biography used only for deterministic screenshots.",
        "verified": True,
        "monthly_listeners": 1234567,
    },
    "top_tracks": TRACKS[:8],
    "albums": [
        {"title": "Fixture Album A", "year": 2021, "cover": None,
         "track_count": 11, "id": "alb-a"},
        {"title": "Fixture Album B", "year": 2019, "cover": None,
         "track_count": 9, "id": "alb-b"},
    ],
    "related": [
        {"name": "Fixture Artist Two", "image": None, "subscribers": "300K"},
        {"name": "Fixture Artist Three", "image": None, "subscribers": "88K"},
    ],
}

HOME_SECTIONS = {
    "popular_results": {"tracks": TRACKS[:10], "source": "fixture"},
    "feed_ready": {"tracks": TRACKS[10:20], "source": "fixture"},
    "releases_ready": {"items": [
        {"title": "Fixture Single A", "artist": "Fixture Artist 01", "cover": None},
        {"title": "Fixture Single B", "artist": "Fixture Artist 02", "cover": None},
    ]},
    "mixes_ready": {"items": [
        {"title": "Fixture Mix 1", "subtitle": "Based on your listening", "cover": None},
        {"title": "Fixture Mix 2", "subtitle": "Fixture energy", "cover": None},
    ]},
}


# --------------------------------------------------------------------------
# screen driver: runs inside the page, returns a status object
# --------------------------------------------------------------------------
SCREEN_DRIVERS = {
    "home": """
      (async () => {
        window.showPage('home');
        await new Promise(r => setTimeout(r, 250));
        return { view: 'home' };
      })()
    """,
    "search": """
      (async () => {
        window.showPage('search');
        await new Promise(r => setTimeout(r, 150));
        const inp = document.getElementById('search-input');
        if (inp) {
          // 'Neon' is a token that really exists in the seeded fixture titles
          // ("Neon Harbour #0000"), so this exercises the real FTS5 local-search
          // path end to end instead of rendering an empty result list.
          inp.value = 'Neon';
          inp.dispatchEvent(new Event('input', { bubbles: true }));
          await window.pywebview.api.search('Neon', 'local');
        }
        await new Promise(r => setTimeout(r, 900));
        const res = document.getElementById('search-results');
        return { view: 'search', resultChildren: res ? res.children.length : -1 };
      })()
    """,
    "library": """
      (async () => {
        window.showPage('library');
        await new Promise(r => setTimeout(r, 1200));
        const el = document.getElementById('lib-active-tracks');
        return { view: 'library', rows: el ? el.children.length : -1 };
      })()
    """,
    "player": """
      (async () => {
        window.onPythonEvent('track_changed', %s);
        window.onPythonEvent('queue_updated', %s);
        window.showPage('player');
        await new Promise(r => setTimeout(r, 700));
        return { view: 'player' };
      })()
    """,
    "queue": """
      (async () => {
        window.onPythonEvent('queue_updated', %s);
        window.showPage('player');
        await new Promise(r => setTimeout(r, 400));
        const d = document.getElementById('queue-drawer');
        if (d) d.classList.add('open');
        await new Promise(r => setTimeout(r, 500));
        return { view: 'queue' };
      })()
    """,
    "lyrics": """
      (async () => {
        window.onPythonEvent('track_changed', %s);
        window.onPythonEvent('lyrics_ready', %s);
        const ov = document.getElementById('lyrics-overlay');
        if (ov) ov.classList.add('active');
        await new Promise(r => setTimeout(r, 900));
        return { view: 'lyrics' };
      })()
    """,
    "artist": """
      (async () => {
        window.showPage('search');
        await new Promise(r => setTimeout(r, 200));
        try { await window.pywebview.api.get_artist_profile('Fixture Artist'); }
        catch (e) {}
        window.onPythonEvent('artist_profile_ready', %s);
        await new Promise(r => setTimeout(r, 900));
        return { view: 'artist' };
      })()
    """,
    "settings": """
      (async () => {
        window.showPage('settings');
        await new Promise(r => setTimeout(r, 900));
        return { view: 'settings' };
      })()
    """,
}

import json as _json


def driver_js(screen: str) -> str:
    """Return the fully-formatted driver expression for `screen`."""
    import json
    tmpl = SCREEN_DRIVERS[screen]
    if screen == "player":
        tmpl = tmpl % (_json.dumps(TRACKS[2]), _json.dumps(QUEUE))
    elif screen == "queue":
        tmpl = tmpl % _json.dumps(QUEUE)
    elif screen == "lyrics":
        tmpl = tmpl % (_json.dumps(TRACKS[2]), _json.dumps(LYRICS_PAYLOAD))
    elif screen == "artist":
        tmpl = tmpl % _json.dumps(ARTIST_PAYLOAD)
    return tmpl


ALL_SCREENS = list(SCREEN_DRIVERS.keys())


# --------------------------------------------------------------------------
# theme matrix
# --------------------------------------------------------------------------
def _ls(theme: str, glass: bool, blur: int, primary: str, accent: str,
        font: str) -> dict:
    return {
        "nedotify_ui_theme": _json.dumps(theme),
        "nedotify_theme_glass_blur": _json.dumps(blur),
        "nedotify_theme_transparency_enabled": _json.dumps(glass),
        "nedotify_theme_transparency_level": _json.dumps(80),
        "nedotify_theme_custom_primary": _json.dumps(primary),
        "nedotify_theme_custom_accent": _json.dumps(accent),
        "nedotify_optimization_performance_preset": _json.dumps("high"),
        "nedotify_optimization_limit_state": _json.dumps("minimize"),
        "nedotify_optimization_blur_quality": _json.dumps("hq"),
        "nedotify_optimization_glow_quality": _json.dumps("full"),
        "nedotify_theme_custom_bg_image": _json.dumps(""),
        "nedotify_theme_custom_bg_blur": _json.dumps(0),
        "nedotify_theme_custom_bg_dim": _json.dumps(30),
        "nedotify_interface_font_family": _json.dumps(font),
    }


def _settings(**theme_kwargs) -> dict:
    """Wrap flat theme keys into the ``{category: {key: value}}`` shape.

    ``tools.bench.profile.seed_db`` persists overrides as
    ``f"{category}.{key}"`` and expects each top-level value to be a mapping
    of that category's keys. The theme fixtures below are naturally written as
    a flat ``theme.*`` dict (``theme_mode``, ``theme``, ``glass_blur``, ...),
    so they are nested here instead of being repeated at every call site.
    """
    return {"theme": dict(theme_kwargs)}


THEMES = {
    "dark": {
        "localstorage": _ls("dark", False, 15, "", "", "system"),
        "settings": _settings(
            theme_mode="dark", theme="dark", name="Dark",
            transparency_enabled="false", glass_blur="15",
            accent_color="#a855f7", font_family="system",
        ),
    },
    "light": {
        "localstorage": _ls("light", False, 15, "", "", "system"),
        "settings": _settings(
            theme_mode="light", theme="light", name="Light",
            transparency_enabled="false", glass_blur="15",
            accent_color="#a855f7", font_family="system",
        ),
    },
    "custom": {
        "localstorage": _ls("dark", True, 28, "#ff6b6b", "#22d3ee", "Georgia"),
        "settings": _settings(
            theme_mode="dark", theme="dark", name="Fixture Custom",
            transparency_enabled="true", glass_blur="28",
            accent_color="#ff6b6b", custom_primary="#ff6b6b",
            custom_accent="#22d3ee", font_family="Georgia",
            transparency_level="80",
        ),
    },
}

VIEWPORTS = [(1280, 800), (1920, 1080)]
DPRS = [1, 2]
