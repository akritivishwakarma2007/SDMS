"""The three hardware seams. Core code depends only on these."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Protocol


@dataclass
class Frame:
    data: bytes                      # encoded image bytes (or synthetic payload in the simulator)
    trigger_id: str                  # identifies the physical drop; retries reuse it
    meta: dict = field(default_factory=dict)


class FrameSource(Protocol):
    def frames(self) -> Iterator[Frame]: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class Trigger(Protocol):
    def next_id(self) -> str | None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class SimClock:
    """Simulated clock with optional drift (seconds added to every reading)."""
    def __init__(self, start: datetime | None = None, step_s: float = 5.0, drift_s: float = 0.0):
        self._t = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.step = timedelta(seconds=step_s)
        self.drift = timedelta(seconds=drift_s)

    def now(self) -> datetime:
        self._t += self.step
        return self._t + self.drift


class DirectoryFrameSource:
    """Replays image files from a folder (hardware phase: replace with Pi camera)."""
    EXT = {".jpg", ".jpeg", ".png", ".bmp"}

    def __init__(self, folder: str | Path):
        self.folder = Path(folder)

    def frames(self) -> Iterator[Frame]:
        for i, p in enumerate(sorted(self.folder.iterdir())):
            if p.suffix.lower() in self.EXT:
                yield Frame(p.read_bytes(), trigger_id=f"file-{i:06d}-{p.name}", meta={"path": str(p)})


class CountingTrigger:
    def __init__(self, prefix: str = "t"):
        self.prefix, self.n = prefix, 0

    def next_id(self) -> str:
        self.n += 1
        return f"{self.prefix}-{self.n:08d}"
