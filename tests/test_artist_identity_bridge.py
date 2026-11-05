"""The UI resolves artist credits through the shared backend identity rules."""

from core.bridge import PUBLIC_METHODS


def test_batch_artist_identity_is_exposed_and_uses_settings_aliases(api, settings_stub):
    settings_stub.set("personalization", "artist_aliases", {"группа альфа": "Alpha"})

    assert "get_canonical_artist_names" in PUBLIC_METHODS
    assert api.get_canonical_artist_names(["Фараон", "PHARAOH", "Группа Альфа", None]) == [
        "pharaoh", "pharaoh", "alpha", ""
    ]


def test_batch_artist_identity_caps_bridge_input(api):
    names = ["artist"] * 501
    assert len(api.get_canonical_artist_names(names)) == 500
