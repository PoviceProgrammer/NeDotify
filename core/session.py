from typing import Any, Dict, List, Optional


class SessionManager:
    """Manages session persistence - remembers last state on close and restores on start."""

    # The whole queue lands in a single settings row, so it is capped and the
    # per-track payload is reduced to what restore_session actually needs.
    MAX_PERSISTED_QUEUE = 200
    PERSISTED_TRACK_FIELDS = (
        "id",
        "title",
        "artist",
        "album",
        "duration",
        "source",
        "source_id",
        "cover_url",
    )

    def __init__(self, settings: Any) -> None:
        self.settings = settings

    @classmethod
    def _slim_track(cls, track: Any) -> Any:
        """Reduce a queue entry to the persisted fields.

        file_path is deliberately not persisted: restore_session nulls it for
        cloud sources anyway, and it is the bulkiest field in the row.
        """
        if not isinstance(track, dict):
            return track
        return {k: track.get(k) for k in cls.PERSISTED_TRACK_FIELDS if k in track}

    def save_session(
        self,
        track_id: Optional[Any] = None,
        position: float = 0.0,
        volume: int = 70,
        queue: Optional[List[Dict[str, Any]]] = None,
        queue_index: int = 0,
        shuffle: bool = False,
        repeat: str = "off",
    ) -> None:
        """Save current session state."""
        full_queue = list(queue or [])
        dropped = max(0, len(full_queue) - self.MAX_PERSISTED_QUEUE)
        persisted_queue = [self._slim_track(t) for t in full_queue[dropped:]]
        if dropped and isinstance(queue_index, int):
            # Keep the index pointing at the same track after the head is cut.
            queue_index = max(0, queue_index - dropped)

        self.settings.set("session", "last_track_id", track_id)
        self.settings.set("session", "last_position", position)
        self.settings.set("session", "last_volume", volume)
        self.settings.set("session", "last_queue", persisted_queue)
        self.settings.set("session", "last_queue_index", queue_index)
        self.settings.set("session", "shuffle", shuffle)
        self.settings.set("session", "repeat", repeat)

        # Settings writes are batched; force them out before the process exits.
        flush = getattr(self.settings, "flush", None)
        if callable(flush):
            flush()

    def restore_session(self) -> Dict[str, Any]:
        """Restore the last session state."""
        session = {
            "track_id": self.settings.get("session", "last_track_id"),
            "position": self.settings.get("session", "last_position", 0),
            "volume": self.settings.get("session", "last_volume", 70),
            "queue": self.settings.get("session", "last_queue", []),
            "queue_index": self.settings.get("session", "last_queue_index", 0),
            "shuffle": self.settings.get("session", "shuffle", False),
            "repeat": self.settings.get("session", "repeat", "off"),
        }

        for track in session.get("queue", []):
            if not isinstance(track, dict):
                continue
            if track.get("source") in ("youtube", "soundcloud", "vk"):
                track["file_path"] = None
                track["resolved_at"] = 0

        return session

    @property
    def should_autoplay(self) -> bool:
        """Check if autoplay is enabled and there's a track to resume."""
        autoplay = self.settings.get("audio", "autoplay", False)
        track_id = self.settings.get("session", "last_track_id")
        return autoplay and track_id is not None
