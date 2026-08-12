from typing import Any, Dict, List, Optional


class SessionManager:
    """Manages session persistence - remembers last state on close and restores on start."""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
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
        self.settings.set("session", "last_track_id", track_id)
        self.settings.set("session", "last_position", position)
        self.settings.set("session", "last_volume", volume)
        self.settings.set("session", "last_queue", queue or [])
        self.settings.set("session", "last_queue_index", queue_index)
        self.settings.set("session", "shuffle", shuffle)
        self.settings.set("session", "repeat", repeat)

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
