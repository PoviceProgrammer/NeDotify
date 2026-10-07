"""Golden-screenshot capture for the NeDotify visual guard.

Runs inside the app process, driven over CDP. One app launch per *theme*
(``main.py`` reads ``transparency_enabled`` before ``create_window``, so
transparency is fixed for the lifetime of a window), and every
screen x viewport x DPR combination is captured in that single session via
``Emulation.setDeviceMetricsOverride``.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from tools.visual_guard import fixtures

SETTLE_AFTER_DRIVER_MS = 700


def _reset_js() -> str:
    """Return every screen to a known state before the next capture."""
    return """
    (async () => {
      try {
        const d = document.getElementById('queue-drawer');
        if (d) d.classList.remove('open');
        const ovs = ['lyrics-overlay', 'mini-player-overlay', 'queue-drawer'];
        for (const id of ovs) {
          const el = document.getElementById(id);
          if (el) el.classList.remove('active', 'open');
        }
        document.getElementById('toast-container') &&
          (document.getElementById('toast-container').innerHTML = '');
        window.showPage('home');
        document.querySelectorAll('.view-page').forEach(v => {
          if (v.id !== 'view-home') v.classList.remove('active');
        });
        document.getElementById('view-home').classList.add('active');
        window.scrollTo(0, 0);
        await new Promise(r => setTimeout(r, 220));
      } catch (e) {}
      return true;
    })()
    """


_SETTLE_JS = """
(async () => {
  // fonts first: a fallback font changes every glyph position
  try { await document.fonts.ready; } catch (e) {}
  // then images: a half-decoded cover is a pixel diff
  const imgs = Array.from(document.images || []);
  await Promise.all(imgs.map(i => i.complete
    ? Promise.resolve()
    : new Promise(r => { i.addEventListener('load', r, {once:true});
                          i.addEventListener('error', r, {once:true}); })));
  // two rAFs so style/layout/paint settle before the shutter
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  await new Promise(r => setTimeout(r, %d));
  return {
    images: imgs.length,
    incomplete: imgs.filter(i => !i.complete).length,
    fonts: (document.fonts ? document.fonts.status : 'n/a'),
    dpr: window.devicePixelRatio,
    w: window.innerWidth, h: window.innerHeight,
  };
})()
""" % SETTLE_AFTER_DRIVER_MS


class Capturer:
    def __init__(self, sess, out_dir: Path, theme_name: str):
        self.sess = sess
        self.out_dir = Path(out_dir)
        self.theme_name = theme_name
        self.records: list[dict] = []

    def name_for(self, screen: str, w: int, h: int, dpr: int) -> str:
        return f"{self.theme_name}__{screen}__{w}x{h}@{dpr}x"

    def capture_one(self, screen: str, w: int, h: int, dpr: int) -> dict:
        self.sess.set_viewport(w, h, dpr)
        self.sess.js(_reset_js(), timeout=30.0, await_promise=True)

        # capture-mode CSS must exist before the driver paints anything
        self.sess.js(fixtures.apply_capture_mode_js(), timeout=15.0)

        t0 = time.monotonic()
        try:
            status = self.sess.js(fixtures.driver_js(screen), timeout=90.0,
                                  await_promise=True)
            err = None
        except Exception as e:  # a broken screen must not kill the whole run
            status, err = None, f"{type(e).__name__}: {e}"[:300]

        info = self.sess.js(_SETTLE_JS, timeout=60.0, await_promise=True) or {}
        png = self.sess.screenshot_png()
        elapsed = round((time.monotonic() - t0) * 1000, 1)

        self.out_dir.mkdir(parents=True, exist_ok=True)
        fname = self.name_for(screen, w, h, dpr) + ".png"
        path = self.out_dir / fname
        path.write_bytes(png)

        rec = {
            "theme": self.theme_name,
            "screen": screen,
            "viewport": f"{w}x{h}",
            "dpr": dpr,
            "file": fname,
            "bytes": len(png),
            "sha256": hashlib.sha256(png).hexdigest(),
            "capture_ms": elapsed,
            "driver_status": status,
            "driver_error": err,
            "page_info": info,
        }
        self.records.append(rec)
        return rec

    def capture_all(self, screens, viewports, dprs) -> list[dict]:
        for screen in screens:
            for (w, h) in viewports:
                for dpr in dprs:
                    rec = self.capture_one(screen, w, h, dpr)
                    flag = "!" if rec["driver_error"] else " "
                    print(f"  [{flag}] {rec['file']}  {rec['bytes']}B  "
                          f"{rec['capture_ms']}ms", flush=True)
        return self.records


def capture_theme(sess, out_dir: Path, theme_name: str, screens, viewports,
                  dprs) -> list[dict]:
    cap = Capturer(sess, out_dir, theme_name)
    recs = cap.capture_all(screens, viewports, dprs)
    (Path(out_dir) / f"_records_{theme_name}.json").write_text(
        json.dumps(recs, indent=2, ensure_ascii=False), encoding="utf-8")
    return recs
