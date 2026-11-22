import pytest

from core.mini_player_geometry import mini_player_bounds, placement_after_drag, restore_bounds


WORK = (-1600, 40, 1600, 860)


def test_new_mini_player_stays_at_top_center():
    assert mini_player_bounds(WORK, 1) == (-970, 40, 340, 64)
    assert mini_player_bounds(WORK, 1, expanded=True) == (-1030, 40, 460, 244)


@pytest.mark.parametrize("edge,window_x,cursor_x", [
    ("left", -1570, -1540),
    ("right", -540, -60),
])
def test_docked_rail_stays_on_edge_and_expands_inward_at_150_percent(edge, window_x, cursor_x):
    saved = placement_after_drag(WORK, (window_x, 610, 510, 96), 1.5, "secondary", cursor_x)
    assert saved["edge"] == edge
    assert saved["monitor"] == "secondary"
    rail = mini_player_bounds(WORK, 1.5, saved)
    expanded = mini_player_bounds(WORK, 1.5, saved, expanded=True)
    assert rail[2:] == (168, 564)
    assert expanded[2:] == (426, 741)
    assert expanded[1] <= rail[1]
    assert expanded[1] + expanded[3] == rail[1] + rail[3] == 900
    if edge == "left":
        assert rail[0] == expanded[0] == -1600
    else:
        assert rail[0] + rail[2] == expanded[0] + expanded[2] == 0


def test_undock_retains_floating_position_on_the_destination_monitor():
    work = (0, -1000, 1920, 960)
    saved = placement_after_drag(work, (630, -700, 140, 470), 1.25, "upper", 700)
    assert saved["edge"] is None
    assert mini_player_bounds(work, 1.25, saved) == (488, -700, 425, 80)


def test_short_work_area_clamps_the_expanded_window():
    assert mini_player_bounds((10, 30, 380, 580), 1.75, {"edge": "right", "y": 1}, True) == (
        10, 30, 380, 580,
    )


def test_restore_bounds_scales_the_saved_logical_position():
    assert restore_bounds((-970, 40, 340, 64), (1200, 800, 100, 60), 1.5) == (
        150, 90, 1200, 800,
    )


def test_restore_bounds_keeps_the_mini_position_without_saved_coordinates():
    assert restore_bounds((-970, 40, 340, 64), (1200, 800, None, None), 1.0) == (
        -970, 40, 1200, 800,
    )
