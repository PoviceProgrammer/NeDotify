import sys
import pytest

if __name__ == "__main__":
    sys.exit(pytest.main([
        "tests/test_recommendation.py",
        "tests/test_lastfm_taste_profile.py",
        "tests/test_m3_recommendation.py",
        "tests/test_new_recommendations.py",
        "tests/test_event_delivery_contract.py",
        "tests/test_personalization_p3.py",
        "tests/test_fix4_db_path.py",
        "tests/test_nedotify.py"
    ]))
