"""Native Qt smoke/capture runner for the source app and the Linux package.

Uses a temporary HOME and the real main.py. This verifies GUI/bridge/assets;
it does not substitute for live-provider playback/download acceptance.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import traceback
import wave

ROOT = Path(__file__).resolve().parents[1]
PAGES = ('home', 'search', 'library', 'player', 'profile', 'settings')


def prepare_validation():
    """Seed only a marked temporary profile owned by this validation run."""
    home = Path.home()
    if not (home / '.nedotify-validation-profile').is_file():
        raise RuntimeError('Native validation requires its own marked temporary HOME')
    from core.database import DatabaseManager
    db = DatabaseManager()
    try:
        db.set_setting('personalization.onboarding_completed', True, 'personalization')
        db.set_setting('downloads.auto_update_tools', False, 'downloads')
        db.set_setting('general.minimize_to_tray', False, 'general')
        audio = home / 'validation-audio.wav'
        with wave.open(str(audio), 'wb') as stream:
            stream.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))
            stream.writeframes(b'\0\0' * 22050 * 3)
        for i in range(8):
            db.add_track(title=f'Проверка Linux {i + 1}', artist='NeDotify QA',
                         album='Native validation fixture', duration=3,
                         file_path=str(audio), source='local', source_id=f'linux-qa-{i}')
    finally:
        db.close()


def _wait(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.15)
    raise TimeoutError('Native GUI validation condition timed out')


def validate_running_app(api, window):
    output = Path(os.environ['NEDOTIFY_VALIDATION_OUTPUT']).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {'platform': sys.platform, 'os': platform.platform(),
              'backend': 'qt', 'python': sys.version, 'mode': 'native-ui-smoke',
              'mocked_providers': False, 'live_provider_checks': 'not performed',
              'audio_output_checks': 'not performed', 'pages': [], 'ok': False}
    try:
        if not sys.platform.startswith('linux'):
            raise RuntimeError('Linux evidence may only be generated on Linux')
        if not api._ui_ready_event.wait(60):
            raise TimeoutError('Frontend did not acknowledge bridge readiness')
        report['bridge_ready'] = True
        window.evaluate_js("window.__linuxQaErrors=[]; addEventListener('error', e => window.__linuxQaErrors.push(String(e.message))); addEventListener('unhandledrejection', e => window.__linuxQaErrors.push(String(e.reason)));")
        # Capture native Qt widget content, including the Chromium surface.
        native = window.native
        capture = native._nedotify_capture
        for style in ('current', 'macos'):
            window.evaluate_js(f"window.NeDotifyAppearance.apply({json.dumps(style)}, 'dark');")
            for page in PAGES:
                window.evaluate_js(f'window.showPage({json.dumps(page)});')
                _wait(lambda: window.evaluate_js(
                    "Boolean(document.getElementById('view-" + page + "')?.classList.contains('active'))"))
                # Wait for font loading/images and entrance transitions to settle.
                window.evaluate_js("window.__linuxQaSettled=false; Promise.all([document.fonts.ready,...Array.from(document.images).filter(i=>i.getBoundingClientRect().width>0).map(i=>i.decode().catch(()=>{}))]).then(()=>requestAnimationFrame(()=>requestAnimationFrame(()=>window.__linuxQaSettled=true)));")
                _wait(lambda: window.evaluate_js('window.__linuxQaSettled === true'))
                time.sleep(.4)
                evidence = window.evaluate_js("""({style:document.documentElement.dataset.uiStyle,
                  fonts:document.fonts.status, width:innerWidth, height:innerHeight,
                  artwork:Array.from(document.images).filter(i=>i.getBoundingClientRect().width>0)
                    .map(i=>({src:i.currentSrc,complete:i.complete,width:i.naturalWidth})),
                  errors:window.__linuxQaErrors.slice()})""")
                path = output / f'{style}-{page}.png'
                capture.requested.emit(str(path))
                _wait(lambda: path.is_file() and path.stat().st_size > 1024)
                if evidence['style'] != style:
                    raise AssertionError('Presentation switch did not apply')
                report['pages'].append({'style': style, 'page': page, 'screenshot': path.name,
                                        'evidence': evidence})
        report['ok'] = not any(row['evidence']['errors'] for row in report['pages'])
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        api._core.settings.set('general', 'minimize_to_tray', False)
        window.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--executable', type=Path)
    parser.add_argument('--timeout', type=int, default=240)
    args = parser.parse_args()
    if not sys.platform.startswith('linux'):
        parser.error('Native validation requires Linux; Windows execution is not Linux evidence')
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        parser.error('A real or Xvfb Linux display is required')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    # Never accept a stale report from a previous successful launch.
    report_path = output / 'report.json'
    report_path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix='nedotify-native-qa-') as profile:
        (Path(profile) / '.nedotify-validation-profile').touch()
        env = dict(os.environ, HOME=profile, USERPROFILE=profile,
                   XDG_CONFIG_HOME=str(Path(profile) / '.config'),
                   XDG_DATA_HOME=str(Path(profile) / '.local/share'),
                   XDG_CACHE_HOME=str(Path(profile) / '.cache'),
                   NEDOTIFY_VALIDATION_OUTPUT=str(output), NEDOTIFY_RESTART_COUNT='1')
        command = [str(args.executable.resolve())] if args.executable else [sys.executable, str(ROOT / 'main.py')]
        with (output / 'app.log').open('w', encoding='utf-8') as log:
            child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                code = child.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                child.terminate()
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=10)
                print('Native validation timed out; see app.log', file=sys.stderr)
                return 1
        if not report_path.is_file():
            print('Application did not produce a native report; see app.log', file=sys.stderr)
            return 1
        report = json.loads(report_path.read_text(encoding='utf-8'))
        report['process_exit_code'] = code
        report['ok'] = report.get('ok', False) and code == 0
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'Native GUI smoke: {len(report.get("pages", []))} captured pages; ok={report["ok"]}')
        return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
