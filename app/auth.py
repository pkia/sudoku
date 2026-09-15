"""Two-player auth: one shared passcode, identity = the configured roster."""
from __future__ import annotations

import hashlib
import hmac
import time

DEFAULT_PLAYERS = ("one", "two")


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_token(secret: str, player: str) -> str:
    return f"{player}.{_sign(secret, player)}"


def verify_token(secret: str, token: str, players=DEFAULT_PLAYERS):
    if not token or "." not in token:
        return None
    player, _, sig = token.rpartition(".")
    if player not in players:
        return None
    if hmac.compare_digest(sig, _sign(secret, player)):
        return player
    return None


def consteq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


class RateLimiter:
    """Tiny sliding-window limiter for passcode attempts."""

    def __init__(self, max_attempts: int, window_s: float):
        self.max = max_attempts
        self.window = window_s
        self.hits: dict[str, tuple[float, int]] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        t0, n = self.hits.get(key, (now, 0))
        if now - t0 > self.window:
            t0, n = now, 0
        n += 1
        self.hits[key] = (t0, n)
        if len(self.hits) > 10000:
            self.hits.clear()
        return n <= self.max

    def reset(self, key: str):
        self.hits.pop(key, None)
