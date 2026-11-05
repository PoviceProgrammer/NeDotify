"""Per-play listening measurements; the caller owns the API's existing lock."""
from dataclasses import dataclass, field
import math
import time
import uuid


@dataclass
class ListeningSession:
    track: dict
    token: str = field(default_factory=lambda: uuid.uuid4().hex)
    history_id: int | None = None
    seconds: float = 0.0
    media_seconds: float = 0.0
    playback_rate: float = 1.0
    audible: bool = False
    completed: bool = False
    closed: bool = False
    last_tick: float = field(default_factory=lambda: time.monotonic())
    last_saved: tuple | None = None

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        if self.audible and not self.closed:
            # Position heartbeats arrive every 5s. Do not turn a suspended
            # computer or unresponsive renderer into hours of listening.
            elapsed = now - self.last_tick
            delta = max(0.0, elapsed) if math.isfinite(elapsed) and elapsed <= 300.0 else 0.0
            self.seconds += delta
            self.media_seconds += delta * self.playback_rate
        self.last_tick = now

    def state(self, audible, ended=False, now=None):
        self.tick(now)
        self.audible = bool(audible) and not self.closed
        try:
            duration = float(self.track.get('duration') or 0)
        except (TypeError, ValueError):
            duration = 0
        if ended and math.isfinite(duration) and duration > 0:
            # Seeking to the last second does not prove a completed listen.
            self.completed = self.completed or self.media_seconds >= duration * 0.8
        if ended:
            self.closed = True
            self.audible = False
