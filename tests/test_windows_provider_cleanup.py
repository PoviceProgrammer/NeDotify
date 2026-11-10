"""Windows source settings must not expose a retired connection flow."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_retired_source_has_no_settings_controls_or_browser_auth_events():
    files = (
        'ui/web_new_v2/index.html',
        'ui/web_new_v2/js/settings-panel.js',
        'ui/web_new_v2/js/events.js',
    )
    for name in files:
        text = (ROOT / name).read_text(encoding='utf-8')
        for retired in ('Яндекс Музы', 'input-yandex-token', 'btn-yandex-auth',
                        'yandex_device_auth_code', 'yandex_device_auth_result'):
            assert retired not in text, f'{name}: {retired}'


def test_readme_describes_the_actual_metadata_catalogue():
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    assert 'Яндекс.Музы' not in readme
    assert 'iTunes' in readme


def test_catalogue_selector_does_not_promise_a_spotify_audio_source():
    html = (ROOT / 'ui/web_new_v2/index.html').read_text(encoding='utf-8')
    import re
    selector = re.search(r'<button[^>]+data-source="spotify"[^>]*>', html).group(0)
    assert 'Apple Music / iTunes' in selector
    assert 'YouTube' in selector


def test_lastfm_disclosure_does_not_claim_credentials_are_never_sent_to_lastfm():
    html = (ROOT / 'ui/web_new_v2/index.html').read_text(encoding='utf-8')
    assert 'пароли и ключи API не передаются' not in html
    assert 'API-ключ передаётся самому Last.fm' in html
