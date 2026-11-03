import pytest

from utils.search_query import suggest_search_queries


@pytest.mark.parametrize(("query", "expected"), [("vjkxfn", "молчат"), ("МЩКШДЩЯ", "VORILOZ"), ("RADIOHEAD", "КФВШЩРУФВ")])
def test_keyboard_layout_suggestions_are_explicit_and_local(tmp_db, query, expected):
    suggestions = suggest_search_queries(tmp_db, query)
    assert suggestions[0] == {"query": expected, "reason": "layout"}


def test_typo_and_adjacent_transposition_find_local_artist(tmp_db):
    tmp_db.add_track("Paranoid Android", artist="Radiohead")
    assert {"query": "Radiohead", "reason": "typo"} in suggest_search_queries(tmp_db, "Radiohed")
    assert {"query": "Radiohead", "reason": "typo"} in suggest_search_queries(tmp_db, "Raidohead")


def test_valid_query_is_not_replaced(tmp_db):
    tmp_db.add_track("Судно", artist="Молчат Дома")
    assert suggest_search_queries(tmp_db, "Молчат Дома") == []
    assert suggest_search_queries(tmp_db, "Судно") == []


@pytest.mark.parametrize("query", ["", "ab", "11..22", "x" * 121, None, ["music"]])
def test_invalid_queries_do_not_scan_library(tmp_db, query):
    statements = []
    tmp_db.conn.set_trace_callback(statements.append)
    try:
        assert suggest_search_queries(tmp_db, query) == []
    finally:
        tmp_db.conn.set_trace_callback(None)
    assert statements == []


def test_suggestions_are_bounded_and_preserve_original_input(tmp_db):
    for name in ("Radiohead", "Radioheed", "Radiohood", "Radioheads"):
        tmp_db.add_track("Song", artist=name)
    query = "Radiohed"
    assert len(suggest_search_queries(tmp_db, query, limit=2)) == 2
    assert len(suggest_search_queries(tmp_db, query, limit=99)) <= 3
    assert query == "Radiohed"
    assert suggest_search_queries(tmp_db, query, limit=0) == []


def test_unicode_transposition_and_mixed_layout_typo(tmp_db):
    tmp_db.add_track("Песня", artist="Молчат")
    assert {"query": "Молчат", "reason": "typo"} in suggest_search_queries(tmp_db, "Молчта")
    mixed = suggest_search_queries(tmp_db, "Mолчат")
    assert all(row["reason"] != "layout" for row in mixed)


def test_layout_and_typo_can_be_corrected_together(tmp_db):
    tmp_db.add_track("Song", artist="Молчат")
    assert {"query": "Молчат", "reason": "layout"} in suggest_search_queries(tmp_db, "vjkrfn")
