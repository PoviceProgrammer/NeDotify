"""Launch the built EXE with a temporary empty profile and close its window."""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import psutil

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--clean-pc', action='store_true')
    parser.add_argument('--system-webview', action='store_true')
    args = parser.parse_args()
    out = ROOT / 'tools/bench/results' / ('windows-frozen-startup-' + time.strftime('%Y%m%d-%H%M%S') + '.json')
    with tempfile.TemporaryDirectory(prefix='nedotify-frozen-startup-') as folder:
        env = dict(os.environ)
        env.update({key: folder for key in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA')})
        for name in ('LASTFM_API_KEY', 'LASTFM_USERNAME'):
            env.pop(name, None)
        if args.clean_pc:
            env['PATH'] = os.pathsep.join([os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32'), os.environ.get('SystemRoot', r'C:\Windows')])
            for name in ('PYTHONPATH', 'PYTHONHOME', 'WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'):
                env.pop(name, None)
        if args.system_webview:
            # Hide this developer machine's optional pinned runtime from the app.
            env['ProgramFiles(x86)'] = folder
        # Schema/settings creation happens inside the isolated child env.
        setup = r'''
from pathlib import Path
import os
from core.database import DatabaseManager
p=Path(os.environ['USERPROFILE']);(p/'.nedotify').mkdir()
d=DatabaseManager(str(p/'.nedotify/nedotify_storage.db'))
j=p/'empty-cookies.txt';j.write_text('# Netscape HTTP Cookie File\n')
rows=[('general.first_launch_done','true','general'),('personalization.onboarding_completed','true','personalization'),('app.close_to_tray','false','app'),('zapret.enabled','false','zapret'),('zapret.auto_start','false','zapret'),('auth.cookies_file_path',str(j),'auth'),('auth.browser_cookies','none','auth')]
d.conn.executemany('INSERT OR REPLACE INTO settings(key,value,category) VALUES(?,?,?)',rows);d.conn.commit();d.close()
'''
        if not args.clean_pc:
            subprocess.run([sys.executable, '-c', setup], cwd=ROOT, env=env, check=True, capture_output=True)
        proc = subprocess.Popen([str(ROOT / 'dist/NeDotify.exe')], cwd=folder if args.clean_pc else ROOT, env=env)
        windows = []
        app_log = Path(folder) / '.nedotify/logs/app.log'
        text = ''
        started = time.monotonic()
        try:
            while time.monotonic() - started < 45:
                try:
                    pids = {proc.pid, *(p.pid for p in psutil.Process(proc.pid).children(recursive=True))}
                except psutil.NoSuchProcess:
                    pids = set()

                @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
                def visit(hwnd, _):
                    pid = wintypes.DWORD()
                    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if pid.value in pids and ctypes.windll.user32.IsWindowVisible(hwnd):
                        windows.append(int(hwnd))
                    return True

                ctypes.windll.user32.EnumWindows(visit, 0)
                text = app_log.read_text(encoding='utf-8', errors='replace') if app_log.exists() else ''
                if windows and 'frontend acknowledged bridge readiness' in text:
                    break
                if proc.poll() is not None:
                    break
                time.sleep(.25)
            result = {'date': time.strftime('%Y-%m-%d'), 'exe': str(ROOT / 'dist/NeDotify.exe'),
                      'temporaryEmptyProfile': True, 'virginProfile': args.clean_pc,
                      'restrictedPath': args.clean_pc, 'systemWebViewFallback': args.system_webview, 'externalWorkingDirectory': args.clean_pc, 'visibleNativeWindow': bool(windows),
                      'windowLoaded': 'window loaded' in text,
                      'bridgeReady': 'frontend acknowledged bridge readiness' in text,
                      'zapretAutostartSkipped': 'Zapret autostart skipped: disabled' in text,
                      'startupSeconds': round(time.monotonic() - started, 2),
                      'systemWebViewUsed': 'WebView2 runtime setting: default' in text}
            for hwnd in set(windows):
                ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
                result['forcedCleanup'] = True
            result['ok'] = all(result[key] for key in ('visibleNativeWindow', 'windowLoaded', 'bridgeReady', 'zapretAutostartSkipped'))
            if args.system_webview:
                result['ok'] = result['ok'] and result['systemWebViewUsed']
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(result, ensure_ascii=True))
            return 0 if result['ok'] else 1
        finally:
            if proc.poll() is None:
                subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)


if __name__ == '__main__':
    raise SystemExit(main())
