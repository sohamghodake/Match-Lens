"""Per-IP rate limits for the endpoints that call the LLM.

Groq's free tier blocks rather than bills at its limits, so this isn't about cost: it
keeps one visitor from using up the day's shared allowance (1,000 requests per model).
In-process sliding windows suit one free-tier server; several instances would need a
shared store such as Redis.
"""

import time
from collections import deque
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings

MAX_TRACKED = 10_000  # (action, ip) pairs kept in memory before old ones are dropped


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = {}

    def hit(self, action: str, ip: str, limit: int, window: float, now: float) -> float | None:
        """Record a request; return seconds to wait if it's over the limit, else None."""
        key = (action, ip)
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) >= limit:
            return hits[0] + window - now
        hits.append(now)
        if len(self._hits) > MAX_TRACKED:
            self._prune(now, window)
        return None

    def _prune(self, now: float, window: float) -> None:
        stale = [k for k, v in self._hits.items() if not v or v[-1] <= now - window]
        for key in stale:
            del self._hits[key]


def rate_limit(action: str, setting: str) -> Callable:
    """A FastAPI dependency allowing `settings.<setting>` requests per IP per hour."""

    async def check(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> None:
        if not settings.rate_limit_enabled:
            return
        limiter: RateLimiter = request.app.state.rate_limiter
        ip = request.client.host if request.client else "unknown"
        wait = limiter.hit(action, ip, getattr(settings, setting), 3600.0, time.monotonic())
        if wait is not None:
            minutes = max(1, round(wait / 60))
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"This free demo allows a limited number of AI requests per hour. "
                f"Please try again in about {minutes} minute{'s' if minutes != 1 else ''}.",
                headers={"Retry-After": str(int(wait) + 1)},
            )

    return check
