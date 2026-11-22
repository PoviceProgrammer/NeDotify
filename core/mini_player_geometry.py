"""Geometry for the shared mini-player window, in physical screen pixels."""

FLOATING_SIZE = (340, 64)
FLOATING_EXPANDED_SIZE = (460, 244)
RAIL_SIZE = (112, 376)
RAIL_EXPANDED_SIZE = (284, 494)
SNAP_DISTANCE = 26


def placement_after_drag(work, bounds, scale, monitor, cursor_x):
    x, y, width, height = work
    left, top, actual_width, _ = bounds
    distances = (min(abs(left - x), abs(cursor_x - x)),
                 min(abs(x + width - left - actual_width), abs(x + width - cursor_x)))
    edge = None
    if min(distances) <= SNAP_DISTANCE * scale:
        edge = "left" if distances[0] <= distances[1] else "right"
    # Save the center and top relative to the selected monitor work area.
    return {"monitor": monitor, "edge": edge,
            "x": max(0, min(1, (left + actual_width / 2 - x) / width)),
            "y": max(0, min(1, (top - y) / height))}


def mini_player_bounds(work, scale, placement=None, expanded=False):
    """Keep both layouts inside the monitor work area, with a stable edge."""
    x, y, work_width, work_height = work
    anchor = placement if isinstance(placement, dict) else {}
    edge = anchor.get("edge")

    def fraction(key, default):
        value = anchor.get(key, default)
        return max(0, min(1, value)) if isinstance(value, (int, float)) else default

    if edge in ("left", "right"):
        size = RAIL_EXPANDED_SIZE if expanded else RAIL_SIZE
    else:
        size = FLOATING_EXPANDED_SIZE if expanded else FLOATING_SIZE
    width = min(work_width, round(size[0] * scale))
    height = min(work_height, round(size[1] * scale))
    left = round(fraction("x", .5) * work_width - width / 2)
    if edge == "left":
        left = 0
    elif edge == "right":
        left = work_width - width
    top = round(fraction("y", 0) * work_height)
    return (x + max(0, min(work_width - width, left)),
            y + max(0, min(work_height - height, top)), width, height)


def restore_bounds(current, saved, scale):
    """Physical WinForms bounds for the saved main window.

    ``saved`` stores the physical size and the logical top-left position, the
    same tuple returned by ``AppApi._native_window_geometry``. If the old
    position could not be read, keep the mini-player's current position so the
    restored window still appears on the monitor the user is looking at.
    """
    width, height, x, y = saved
    left = current[0] if x is None else round(x * scale)
    top = current[1] if y is None else round(y * scale)
    return int(left), int(top), max(1, int(width)), max(1, int(height))
