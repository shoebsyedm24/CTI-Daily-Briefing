"""Thread-safe token bucket for API pacing."""
from __future__ import annotations
import threading
import time


class TokenBucket:
    """rate tokens replenish over period seconds. acquire() blocks until available."""
    def __init__(self, rate: int, period: float):
        self.rate = rate
        self.period = period
        self.tokens = float(rate)
        self.last = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self, n: int = 1) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                elapsed = now - self.last
                self.tokens = min(self.rate, self.tokens + elapsed * (self.rate / self.period))
                self.last = now
                if self.tokens >= n:
                    self.tokens -= n
                    return
                deficit = n - self.tokens
                wait = deficit * (self.period / self.rate)
            time.sleep(min(wait, 1.0))
