"""Windows source settings must not expose a retired connection flow."""
from pathlib import Path
import re


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


def test_search_offers_categories_without_a_platform_selector():
    html = (ROOT / 'ui/web_new_v2/index.html').read_text(encoding='utf-8')
    assert 'search-platform-btn' not in html
    assert 'search-platform-dropdown' not in html
    categories = re.findall(r'<button class="type-filter-btn[^"]*" data-type="([^"]+)"', html)
    assert categories == ['all', 'tracks', 'artists', 'albums', 'playlists']


def test_lastfm_disclosure_does_not_claim_credentials_are_never_sent_to_lastfm():
    html = (ROOT / 'ui/web_new_v2/index.html').read_text(encoding='utf-8')
    assert 'пароли и ключи API не передаются' not in html
    assert 'API-ключ передаётся самому Last.fm' in html
