"""Artist choices cross the real persistence/recommendation boundaries."""
from types import SimpleNamespace

from services.taste_profile import UserTasteProfile


def test_artist_selected_outside_quick_list_is_saved(api):
    artists = ['Radiohead', 'Massive Attack', 'Portishead']
    result = api.complete_onboarding({'favorite_artists': artists})
    assert result['success']
    assert result['settings']['personalization']['favorite_artists'] == artists


def test_artist_choices_drive_empty_profile_seeds(recommendations):
    chosen = ['9mice', 'Heronwater', 'Radiohead']
    recommendations.settings = SimpleNamespace(get=lambda category, key, default=None:
        chosen if (category, key) == ('personalization', 'favorite_artists') else default)
    assert recommendations._get_merged_seed_artists(UserTasteProfile(), limit=3) == chosen
    assert recommendations._get_merged_seed_artists(UserTasteProfile(), limit=10) == chosen


def test_invalid_artist_payload_does_not_complete_setup(api):
    assert not api.complete_onboarding({'favorite_artists': ['9mice', {'name':'bad'}]})['success']
