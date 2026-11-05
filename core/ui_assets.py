"""Serve the optional presentation pack from a fixed, bundled directory."""
from pathlib import Path


def install_library_artwork(app):
    """Serve read-only managed artwork on the UI origin without media tokens.

    LocalUiServer enforces Host/Origin/fetch metadata before these routes run.
    Reuse the proxy's canonical roots and image suffix checks; this endpoint
    cannot forward network requests or read arbitrary library media.
    """
    import bottle
    from core.proxy import _safe_cover_path, _safe_avatar_path
    from core.ui_server import cached_static_file

    def image(check):
        candidate = bottle.request.query.getunicode('path', '')
        if not candidate or len(candidate) > 4096:
            return bottle.HTTPError(400, 'Invalid artwork path')
        allowed = check(candidate)
        if not allowed:
            return bottle.HTTPError(404, 'Artwork not found')
        path = Path(allowed)
        return cached_static_file(path.name, root=str(path.parent))

    app.get('/api/cover')(lambda: image(_safe_cover_path))
    app.get('/api/avatar')(lambda: image(_safe_avatar_path))


def install_macos_assets(app, base_dir):
    import bottle

    from core.ui_server import cached_static_file

    root = (Path(base_dir) / "ui" / "MACos_ui").resolve()

    def macos_asset(filepath):
        target = (root / filepath).resolve()
        if not target.is_relative_to(root) or target.suffix not in {'.css', '.png', '.svg', '.woff2'}:
            return bottle.HTTPError(404, 'Asset not found')
        return cached_static_file(filepath, root=str(root))

    # pywebview installs /<file:path> before calling the route installer.
    # Bottle tries dynamic routes in insertion order, so another wildcard
    # would never run. Exact asset routes take precedence over that catch-all.
    for file in root.rglob('*'):
        if file.is_file() and file.suffix in {'.css', '.png', '.svg', '.woff2'}:
            relative = file.relative_to(root).as_posix()
            app.get('/MACos_ui/' + relative)(lambda filepath=relative: macos_asset(filepath))
