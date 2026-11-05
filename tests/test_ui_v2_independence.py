"""One shared application resolves its assets plus the scoped macOS pack."""
from html.parser import HTMLParser
from pathlib import Path
import re
import runpy
import sys
from types import SimpleNamespace
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
    support = runpy.run_path(str(ROOT / 'packaging/linux_support.py'))
    data = support['collect_ui_datas'](ROOT)
    published = {(Path(destination) / Path(source).name).as_posix() for source, destination in data}
    assert 'ui/web_new_v2/index.html' in published
    assert 'ui/web_new_v2/js/player.js' in published
    assert any(path.endswith('.webp') for path in published)
    assert not any('/covers/' in path for path in published)
    assert not any('/backgrounds/' in path and path.lower().endswith('/sources.json') for path in published)
    assert not any('/backgrounds/' in path and path.endswith(('.jpg', '.jpeg')) for path in published)
    for source, destination in data:
        assert Path(source).is_relative_to(UI) or Path(source).is_relative_to(ROOT / 'ui/MACos_ui')
        assert (Path(destination) / Path(source).name).as_posix() == Path(source).relative_to(ROOT).as_posix()
    # The presentation pack is explicitly retained beside the sole application.
    assert any(path.startswith('ui/MACos_ui/') for path in published)


def test_frozen_linux_tray_icon_resolves_the_bundled_png(tmp_path, monkeypatch):
    from core.tray import TrayIcon
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    monkeypatch.setattr(sys, 'platform', 'linux')
    logo = tmp_path / 'icon.png'
    logo.write_bytes(b'fixture')
    tray = TrayIcon(SimpleNamespace(_window=None))
    assert tray.icon_path == str(logo)
