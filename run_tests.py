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
        "tests/test_phase1_tag_editor.py",
        "tests/test_phase2_storage_manager.py",
        "tests/test_phase3_phase4_flow_prefetch.py",
        "tests/test_phase5_tray_menu.py",
        "tests/test_audit_fixes_and_blackout.py"
    ]))
