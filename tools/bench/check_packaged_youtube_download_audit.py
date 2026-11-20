"""Run the production download API in an isolated diagnostic PyInstaller EXE.

Uses the production spec, imports product modules from its frozen archive and
exits before the GUI entry point. The diagnostic hook is never shipped in the
real installer. It does not modify VPN or start winws.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    test_root = (ROOT / '.test_runs').resolve()
    with tempfile.TemporaryDirectory(prefix='frozen-download-audit-', dir=test_root) as folder:
        scratch = Path(folder).resolve()
        assert scratch.is_relative_to(test_root)
        hook = scratch / 'audit_hook.py'
        hook.write_text('''import builtins, os, runpy, sys
original_import = builtins.__import__
def audit_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == 'webview':
        builtins.__import__ = original_import
        try:
            runpy.run_path(os.path.join(sys._MEIPASS, 'check_youtube_download_audit.py'), run_name='__main__')
        except SystemExit as error:
            os._exit(error.code or 0)
        except BaseException as error:
            import json, traceback
            frames = [{'file': os.path.basename(f.filename), 'line': f.lineno, 'function': f.name} for f in traceback.extract_tb(error.__traceback__)]
            with open(os.path.join(os.environ['NEDOTIFY_AUDIT_ROOT'], '.test_runs', 'packaged-audit-error.json'), 'w') as output:
                json.dump({'type': type(error).__name__, 'frames': frames}, output)
            os._exit(1)
        os._exit(0)
    return original_import(name, globals, locals, fromlist, level)
builtins.__import__ = audit_import
''', encoding='utf-8')
        spec = (ROOT / 'setup_pyinstaller.spec').read_text(encoding='utf-8')
        replacements = {
            'ROOT = SPECPATH': 'ROOT = ' + repr(str(ROOT)),
            'runtime_hooks=[]': 'runtime_hooks=[' + repr(str(hook)) + ']',
            "name='NeDotify'": "name='NeDotify_Audit'",
            'extra_datas = [': 'extra_datas = [\n    (' + repr(str(ROOT / 'tools/bench/check_youtube_download_audit.py')) + ", '.'),",
        }
        for before, after in replacements.items():
            if before not in spec:
                raise RuntimeError('Production spec changed: ' + before)
            spec = spec.replace(before, after)
        spec_path = scratch / 'audit.spec'
        spec_path.write_text(spec, encoding='utf-8')
        build = subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
                                '--distpath', str(scratch / 'dist'), '--workpath', str(scratch / 'build'),
                                str(spec_path)], cwd=ROOT, capture_output=True)
        (test_root / 'packaged-youtube-audit-build.log').write_bytes(build.stdout + build.stderr)
        if build.returncode:
            return build.returncode
        env = dict(os.environ, NEDOTIFY_AUDIT_ROOT=str(ROOT))
        for name, arguments in ([('clean-pc-mp3', [])] if os.environ.get('NEDOTIFY_AUDIT_CLEAN_PC') == '1' else [('direct', []), ('query', ['--source-id', 'ytsearch1:Rick Astley Never Gonna Give You Up', '--duration', '0'])]):
            result = subprocess.run([str(scratch / 'dist/NeDotify_Audit.exe'), *arguments], cwd=scratch,
                                    env=env, capture_output=True, timeout=360)
            (test_root / ('packaged-youtube-audit-' + name + '.log')).write_bytes(result.stdout + result.stderr)
            print('packaged ' + name + ' exit=' + str(result.returncode), flush=True)
            if result.returncode:
                return result.returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
