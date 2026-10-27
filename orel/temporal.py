"""Bounded evidence over distinct observations, independent of ML/HTTP/storage."""

from collections import deque

MIN_FRAMES = 6
MIN_SECONDS = 2.0
WINDOW_SECONDS = 3.0
MIN_RATIO = 0.8
CLEAR_FRAMES = 3
CLEAR_SECONDS = 0.6


class TemporalCondition:
    def __init__(self):
        self.samples: deque[tuple[float, bool]] = deque(maxlen=30)
        self.since: float | None = None
        self.clearing: list[float] = []
        self.critical = False

    @property
    def pending(self) -> bool:
        return self.since is None and bool(self.samples) and self.samples[-1][1]

    def observe(self, timestamp: float, violation: bool | None) -> bool:
        if violation is None:
            self.samples.clear()
            self.clearing.clear()
            self.since = None
            self.critical = False
            return False
        if self.samples and timestamp - self.samples[-1][0] < 0.1 - 1e-6:
            return self.since is not None
        self.samples.append((timestamp, violation))
        while self.samples and timestamp - self.samples[0][0] > WINDOW_SECONDS:
            self.samples.popleft()
        if self.since is not None:
            if violation:
                self.clearing.clear()
            else:
                self.clearing.append(timestamp)
                if (
                    len(self.clearing) >= CLEAR_FRAMES
                    and timestamp - self.clearing[0] >= CLEAR_SECONDS - 1e-6
                ):
                    self.since = None
                    self.critical = False
                    self.samples.clear()
                    self.clearing.clear()
            return self.since is not None
        positives = [time for time, present in self.samples if present]
        if (
            len(positives) >= MIN_FRAMES
            and timestamp - positives[0] >= MIN_SECONDS - 1e-6
            and len(positives) / len(self.samples) >= MIN_RATIO
            and len(self.samples) >= 2
            and self.samples[-1][1]
            and self.samples[-2][1]
        ):
            self.since = positives[0]
        return self.since is not None
