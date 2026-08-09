import pytest
from core.services.recommendation import RecommendationEngine, run_recommendation

@pytest.fixture
def mock_catalog():
    return [
        {"id": f"t{i}", "genre": "rock" if i % 2 == 0 else "electronic", "energy": i/20.0, "bpm": 100 + i*5}
        for i in range(20)
    ]

@pytest.fixture
def mock_profile():
    return {
        "history": ["t1", "t3", "t5", "t13", "t15", "t17"],
        "favorites": ["t7", "t9"],
        "subscriptions": ["a1"],
        "skips": {"t11": 5, "t12": 2},
        "repeats": {"t1": 10, "t3": 2}
    }

@pytest.fixture
def mock_context():
    return {
        "activity": "workout"
    }


def test_ratio_enforcement(mock_profile, mock_context, mock_catalog):
    engine = RecommendationEngine(mock_profile, mock_context, mock_catalog)
    # Get 10 tracks
    mixes = engine.generate_dynamic_mixes()
    
    daily_mix = next(m for m in mixes if m["name"] == "Daily Mix 1")
    tracks = daily_mix["tracks"]
    
    assert len(tracks) == 10
    familiar_count = sum(1 for t in tracks if t in engine.history_set or t in engine.favorites_set)
    discovery_count = 10 - familiar_count
    
    # 60-70% should be 6 or 7
    assert familiar_count in [6, 7]
    assert discovery_count in [3, 4]

def test_discover_weekly_integrity(mock_profile, mock_context, mock_catalog):
    engine = RecommendationEngine(mock_profile, mock_context, mock_catalog)
    mixes = engine.generate_dynamic_mixes()
    
    dw_mix = next(m for m in mixes if m["name"] == "Discover Weekly")
    tracks = dw_mix["tracks"]
    
    # Ensure no track in Discover Weekly is in history
    for t in tracks:
        assert t not in engine.history_set

def test_skip_penalty(mock_profile, mock_context, mock_catalog):
    engine = RecommendationEngine(mock_profile, mock_context, mock_catalog)
    eligible = engine._get_eligible_tracks()
    eligible_ids = [t['id'] for t in eligible]
    
    # t11 and t12 should be excluded because skips > 1
    assert "t11" not in eligible_ids
    assert "t12" not in eligible_ids
    assert "t1" in eligible_ids

def test_full_run(mock_profile, mock_context, mock_catalog):
    res = run_recommendation(mock_profile, mock_context, mock_catalog)
    
    assert "dynamic_mixes" in res
    assert "smart_recs" in res
    assert "dynamic_charts" in res
    assert "artist_spotlights" in res
    
    assert len(res["dynamic_mixes"]) == 3
    assert "global_top_50" in res["dynamic_charts"]
