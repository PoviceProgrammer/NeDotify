import json


def test_search_suggestions_never_call_providers(api, tmp_db, youtube_stub, monkeypatch):
    tmp_db.add_track("Song", artist="Radiohead")

    def unexpected_provider(*args, **kwargs):
        raise AssertionError("A suggestion must not request a provider")

    monkeypatch.setattr(youtube_stub, "search", unexpected_provider, raising=False)
    suggestions = api.get_search_suggestions("Radiohed")
    assert {"query": "Radiohead", "reason": "typo"} in suggestions
    assert youtube_stub.calls == []
    json.dumps(suggestions)
