"""Login throttling.

A fixed-window counter keyed by ``(email, client ip)``. Both halves are needed:
keying only on the address punishes everyone behind a NAT, and keying only on the
address's target lets a distributed attacker spread across it.

**Known limitation.** The default backend is a dict in this process. With more
than one API worker the effective limit is ``workers x login_max_attempts``, and
a restart clears it. That is a real weakening, accepted for now because the
alternative — a Redis counter — makes the login path depend on the queue being
up. :class:`RedisLoginRateLimiter` is provided for when the deployment wants the
stricter guarantee; swap it in at application startup.

Counting happens on *failure* only, so a user who logs in successfully never
consumes budget, and a locked-out account still unlocks after the window rather
than needing an operator.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from app.core.config import Settings


@dataclass
class _Window:
    count: int = 0
    started_at: float = field(default_factory=time.monotonic)


class LoginRateLimiter:
    """In-process fixed-window limiter. See the module docstring's limitation."""

    def __init__(self, *, max_attempts: int, window_seconds: int) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._windows: dict[str, _Window] = defaultdict(_Window)

    def _key(self, email: str, client_ip: str) -> str:
        return f"{email.strip().lower()}|{client_ip}"

    def is_blocked(self, email: str, client_ip: str) -> bool:
        window = self._windows.get(self._key(email, client_ip))
        if window is None:
            return False
        if time.monotonic() - window.started_at > self._window:
            return False
        return window.count >= self._max

    def record_failure(self, email: str, client_ip: str) -> None:
        key = self._key(email, client_ip)
        window = self._windows[key]
        if time.monotonic() - window.started_at > self._window:
            window.count = 0
            window.started_at = time.monotonic()
        window.count += 1

    def reset(self, email: str, client_ip: str) -> None:
        self._windows.pop(self._key(email, client_ip), None)


class RedisLoginRateLimiter(LoginRateLimiter):
    """Shared-state variant, correct across API workers and restarts.

    Uses INCR with an EXPIRE on first write, which is the standard fixed-window
    counter. Not wired in by default: see the module docstring.
    """

    def __init__(self, redis_client, *, max_attempts: int, window_seconds: int) -> None:
        super().__init__(max_attempts=max_attempts, window_seconds=window_seconds)
        self._redis = redis_client

    def _redis_key(self, email: str, client_ip: str) -> str:
        return f"irtboss:login:{self._key(email, client_ip)}"

    def is_blocked(self, email: str, client_ip: str) -> bool:
        raw = self._redis.get(self._redis_key(email, client_ip))
        return raw is not None and int(raw) >= self._max

    def record_failure(self, email: str, client_ip: str) -> None:
        key = self._redis_key(email, client_ip)
        count = self._redis.incr(key)
        if count == 1:
            self._redis.expire(key, self._window)

    def reset(self, email: str, client_ip: str) -> None:
        self._redis.delete(self._redis_key(email, client_ip))


_limiter: LoginRateLimiter | None = None


def get_login_rate_limiter(settings: Settings) -> LoginRateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = LoginRateLimiter(
            max_attempts=settings.login_max_attempts,
            window_seconds=settings.login_window_seconds,
        )
    return _limiter


def set_login_rate_limiter(limiter: LoginRateLimiter | None) -> None:
    """Install a limiter (or clear it, for tests)."""

    global _limiter
    _limiter = limiter
