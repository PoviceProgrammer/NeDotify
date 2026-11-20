"""WN-16 role B verification script (read-only against the repo)."""
import ast
import os
import sys

ROOT = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

print("=== 1. describe_error behaviour ===")
from core.user_errors import describe_error  # noqa: E402

cases = [
    ("ValueError with an absolute path",
     ValueError("invalid literal for int() with base 10: 'C:\\Users\\artur\\.nedotify\\downloads\\a.mp3'")),
    ("FileNotFoundError with a path",
     FileNotFoundError(2, "No such file or directory", "C:\\Users\\artur\\.nedotify\\downloads\\a.mp3")),
    ("PermissionError with a path",
     PermissionError(13, "Permission denied", "C:\\Users\\artur\\.nedotify\\downloads\\a.mp3")),
    ("generic exception with a path",
     Exception("cannot open C:\\Users\\artur\\.nedotify\\streams\\x.mp3")),
    ("OSError ENOSPC", OSError(28, "disk full")),
    ("plain string 'offline'", "offline"),
]
for label, err in cases:
    out = describe_error(err, "download")
    leak = ("C:\\Users" in out["message"]) or ("artur" in out["message"])
    print(f"  {label:38s} code={out['code']:14s} path_leak={leak}")
    print(f"      message={out['message']!r}")

print()
print("=== 2. does the ValueError branch echo the raw message verbatim? ===")
raw = "invalid literal for int() with base 10: 'C:\\Users\\artur\\.nedotify\\downloads\\a.mp3'"
out = describe_error(ValueError(raw), "download")
print("  contains raw text:", raw[:60] in out["message"])
print("  truncated at 240 chars:", len(raw) > 240 and out["message"] == raw[:240])

print()
print("=== 3. TrayIcon.stop() vs pystray readiness semantics ===")
import core.tray as tray_mod  # noqa: E402


class StubIcon:
    """Mimics pystray._base.Icon: _running becomes True only in _mark_ready()."""

    def __init__(self, *a, **k):
        self._running = False
        self.stop_calls = 0

    def stop(self):
        if self._running:
            self.stop_calls += 1
            self._running = False


t = tray_mod.TrayIcon.__new__(tray_mod.TrayIcon)
t.api = None
t.icon_path = None
t.icon = StubIcon()          # icon created, but run() has not reached _mark_ready()
t._current_track = None
t._is_playing = False
t._last_update_time = 0.0
import threading  # noqa: E402
t._lock = threading.Lock()
t._is_running = True         # TrayIcon's own flag: set before icon.run()

t.stop()                      # <- the "quit" arrives before pystray marked itself ready
print("  after stop(): pystray _running =", t.icon._running,
      "| stop() actually delivered =", t.icon.stop_calls,
      "| TrayIcon._is_running =", t._is_running)
t.stop()                      # second attempt
print("  after 2nd stop(): delivered =", t.icon.stop_calls)

print()
print("=== 4. Is the tray ever started? (AST proof) ===")
src = open("core/api.py", encoding="utf-8").read()
tree = ast.parse(src)
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        for i, stmt in enumerate(node.body):
            if isinstance(stmt, ast.Return) and node.body[i + 1:]:
                for rest in node.body[i + 1:]:
                    for sub in ast.walk(rest):
                        if isinstance(sub, ast.Attribute) and sub.attr == "start":
                            print(f"  UNREACHABLE {sub.attr}() at line {sub.lineno} "
                                  f"inside {node.name}() (return at line {stmt.lineno})")
hits = []
for path in ("core/api.py", "core/app.py", "main.py", "core/tray.py"):
    t2 = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(t2):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "start" and isinstance(node.func.value, ast.Attribute) \
                and node.func.value.attr == "_tray":
            hits.append((path, node.lineno))
print("  call sites of _tray.start():", hits)

print()
print("=== 5. Frozen-mode asset resolution ===")
saved = getattr(sys, "_MEIPASS", None)
sys._MEIPASS = r"C:\fake\meipass"
print("  frozen icon path ->", tray_mod.TrayIcon.__new__(tray_mod.TrayIcon)._resolve_default_icon_path())
if saved is None:
    del sys._MEIPASS
else:
    sys._MEIPASS = saved
print("  source icon path ->", tray_mod.TrayIcon.__new__(tray_mod.TrayIcon)._resolve_default_icon_path())
print("  repo icon.ico exists:", os.path.exists("icon.ico"),
      "| ui/web_new_v2/assets/logo.png exists:", os.path.exists("ui/web_new_v2/assets/logo.png"))
print("  icon.ico in setup_pyinstaller.spec datas:",
      "'icon.ico'" in open("setup_pyinstaller.spec", encoding="utf-8").read().split("datas=")[0])

print()
print("=== 6. MACos_ui pack: is it referenced by the only UI? ===")
html = open("ui/web_new_v2/index.html", encoding="utf-8-sig").read()
for line in html.splitlines():
    if "MACos_ui" in line:
        print("  index.html:", line.strip())
