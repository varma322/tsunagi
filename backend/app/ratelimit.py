"""Request rate limiting.

A fixed window per credential. Windows are cheap to reason about and cheap to
store, and the burst-at-a-boundary weakness a sliding window would fix does not
matter here: the limit exists to bound abuse and runaway clients, not to shape
traffic precisely.

Counters live in Redis when it is configured, so replicas share one budget;
otherwise they are per-process, which is correct for a single worker.
"""

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

KEY_PREFIX = "ratelimit"


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class RateLimiter:
    """Fixed-window counter held in process memory."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._counters: dict[tuple[str, int], int] = {}

    def _window(self, now: float) -> int:
        return int(now // self.window_seconds)

    async def check(self, identity: str) -> RateLimitDecision:
        now = time.time()
        window = self._window(now)
        key = (identity, window)

        used = self._counters.get(key, 0) + 1
        self._counters[key] = used

        # Windows are only ever incremented, so anything older than the current
        # one is dead weight; drop it rather than run a background sweep.
        if len(self._counters) > 4096:
            self._counters = {
                entry: value for entry, value in self._counters.items() if entry[1] >= window
            }

        return self._decide(used, now, window)

    def _decide(self, used: int, now: float, window: int) -> RateLimitDecision:
        reset_at = (window + 1) * self.window_seconds
        return RateLimitDecision(
            allowed=used <= self.limit,
            limit=self.limit,
            remaining=max(0, self.limit - used),
            retry_after=max(1, int(reset_at - now)),
        )


class RedisRateLimiter(RateLimiter):
    """Fixed-window counter shared across workers via Redis."""

    def __init__(self, redis: object, limit: int, window_seconds: int) -> None:
        super().__init__(limit, window_seconds)
        self._redis = redis

    async def check(self, identity: str) -> RateLimitDecision:
        now = time.time()
        window = self._window(now)
        key = f"{KEY_PREFIX}:{identity}:{window}"

        try:
            pipeline = self._redis.pipeline()  # type: ignore[attr-defined]
            pipeline.incr(key)
            # Expiry is set every time rather than only on creation: one extra
            # command is cheaper than a key that outlives its window because the
            # EXPIRE raced with the INCR.
            pipeline.expire(key, self.window_seconds + 1)
            used, _ = await pipeline.execute()
        except Exception:
            # A limiter outage must not take the API down with it.
            logger.exception("rate limit backend failed; allowing request")
            return RateLimitDecision(True, self.limit, self.limit, 0)

        return self._decide(int(used), now, window)
