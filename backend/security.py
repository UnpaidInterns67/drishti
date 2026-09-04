"""Focused application security controls with no external service dependency."""

from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import RLock


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after: int = 0


class SlidingWindowRateLimiter:
    """Thread-safe fixed-capacity sliding windows for a single-worker service."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit = max(1, int(limit))
        self.window_seconds = max(1, int(window_seconds))
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = RLock()

    def check(self, key: str, now: float | None = None) -> RateLimitResult:
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                retry_after = max(1, int(events[0] + self.window_seconds - current) + 1)
                return RateLimitResult(False, retry_after)
            events.append(current)
            return RateLimitResult(True)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


def client_ip(scope_client) -> str:
    """Return the peer IP accepted by the ASGI server/proxy trust policy."""
    if not scope_client:
        return "unknown"
    return str(scope_client.host)


def request_id(candidate: str | None = None) -> str:
    if candidate:
        clean = "".join(character for character in candidate if character.isalnum() or character in "-_")
        if 8 <= len(clean) <= 64:
            return clean
    return secrets.token_hex(16)


SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' blob: data:; media-src 'self' blob:; "
        "connect-src 'self'; object-src 'none'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}
