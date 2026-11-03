"""One shared application resolves its assets plus the scoped macOS pack."""
import ast
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / 'ui' / 'web_new_v2'


def _local_target(owner, reference):
    if not reference or reference.startswith(('#', 'data:', 'blob:', 'javascript:')) or '${' in reference:
        return None
    url = urlsplit(reference)
    if url.scheme or url.netloc:
        return None
    if url.path.lstrip('/').startswith('MACos_ui/'):
        return (ROOT / 'ui' / unquote(url.path).lstrip('/')).resolve()
    return ((UI if url.path.startswith('/') else owner.parent) / unquote(url.path).lstrip('/')).resolve()


def test_ui_v2_resolves_all_static_assets_without_other_ui_trees():
    references = []

    class Assets(HTMLParser):
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            attr = 'src' if tag in ('script', 'img') else 'href' if tag == 'link' else None
            if attr and attrs.get(attr):
                references.append((UI / 'index.html', attrs[attr]))

    Assets().feed((UI / 'index.html').read_text(encoding='utf-8-sig'))
    for file in UI.rglob('*.js'):
        if file.name.endswith('.min.js'):
            continue
        source = file.read_text(encoding='utf-8-sig')
        references.extend((file, value) for value in re.findall(r'(?:from\s*|import\s*\(\s*)[\'\"]([^\'\"]+)[\'\"]', source))
    for file in UI.rglob('*.css'):
        source = re.sub(r'/\*.*?\*/', '', file.read_text(encoding='utf-8-sig'), flags=re.S)
        references.extend((file, value) for value in re.findall(r'url\(\s*[\'\"]?([^\)\'\"]+)', source))
        references.extend((file, value) for value in re.findall(r'@import\s+[\'\"]([^\'\"]+)[\'\"]', source))
    checked = 0
    for owner, reference in references:
        target = _local_target(owner, reference)
        if target is None:
            continue
        checked += 1
        assert target.is_relative_to(UI.resolve()) or target.is_relative_to((ROOT / 'ui/MACos_ui').resolve()), (owner, reference)
        assert target.is_file(), (owner, reference)
    assert checked > 50, 'Asset discovery missed the UI module graph'


def test_v2_is_the_only_active_and_packaged_ui():
    assert {p.name for p in (ROOT / 'ui').iterdir() if p.is_dir() and (p / 'index.html').is_file()} == {'web_new_v2'}
    tree = ast.parse((ROOT / 'setup_pyinstaller.spec').read_text(encoding='utf-8'))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {'_is_ui_cover_cache', '_collect_ui_datas'}]
    namespace = {'Path': Path}
    exec(compile(ast.Module(body=functions, type_ignores=[]), '<spec-data-helpers>', 'exec'), namespace)
    data = namespace['_collect_ui_datas'](UI)
    published = {(Path(destination) / Path(source).name).as_posix() for source, destination in data}
    assert 'ui/web_new_v2/index.html' in published
    assert 'ui/web_new_v2/js/player.js' in published
    assert any(path.endswith('.webp') for path in published)
    assert not any('/covers/' in path or path.endswith('/SOURCES.json') for path in published)
    assert not any('/backgrounds/' in path and path.endswith(('.jpg', '.jpeg')) for path in published)
    for source, destination in data:
        assert Path(source).is_relative_to(UI)
        assert (Path(destination) / Path(source).name).as_posix() == 'ui/web_new_v2/' + Path(source).relative_to(UI).as_posix()
    # The presentation pack is explicitly retained beside the sole application.
    assert any(isinstance(node, ast.Constant) and node.value == 'ui/MACos_ui' for node in ast.walk(tree))


def test_frozen_tray_icon_resolves_from_v2_without_legacy_assets(tmp_path, monkeypatch):
    from core.tray import TrayIcon
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    logo = tmp_path / 'ui' / 'web_new_v2' / 'assets' / 'logo.png'
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b'fixture')
    assert TrayIcon.__new__(TrayIcon)._resolve_default_icon_path() == str(logo)
