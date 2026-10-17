"""
app/core/rate_limit.py — In-memory sliding-window rate limiter and inference concurrency protection.

Security Guarantees:
1. Principal-Bound Keys: Rate limits are keyed strictly on verified identities:
   - Authenticated User: 'user:<uid>'
   - Authenticated Device: 'device:<device_id>'
   - Unauthenticated / Discovery: 'ip:<client_host>'
   Client-supplied spoofable headers (X-Forwarded-For, user-agent) are never trusted for authenticated actors.
2. Memory Bounded: Automatically evicts stale sliding-window records to prevent unbounded memory growth.
3. Compute Engine Protection: Inference concurrency semaphore prevents CPU saturation from parallel ECAPA-TDNN extractions.
4. Multi-Instance Limitation: This in-memory implementation is process-local. Distributed horizontal
   deployments will transition to Redis in Milestone 3C.
"""

import asyncio
import threading
import time
from typing import Optional, Union, Tuple
from fastapi import HTTPException, Request

from app.core.config import MAX_CONCURRENT_INFERENCES
from app.core.auth import AuthenticatedUser
from app.core.device_auth import AuthenticatedDevice


class InMemoryRateLimiter:
    """
    Thread-safe, sliding-window in-memory rate limiter with automatic pruning.
    """
    def __init__(self, default_limit: int = 60, window_seconds: float = 60.0, cleanup_interval: float = 60.0):
        self.default_limit = default_limit
        self.window_seconds = window_seconds
        self.cleanup_interval = cleanup_interval
        self._lock = threading.Lock()
        self._records: dict[str, list[float]] = {}
        self._last_cleanup = time.time()

    def check_rate_limit(
        self,
        key: str,
        limit: Optional[int] = None,
        window: Optional[float] = None,
    ) -> Tuple[bool, int, float]:
        """
        Record request and check against limit.
        Returns: (is_allowed, remaining_requests, retry_after_seconds)
        """
        max_reqs = limit if limit is not None else self.default_limit
        window_sec = window if window is not None else self.window_seconds
        now = time.time()

        with self._lock:
            # Periodic cleanup of completely stale entries
            if now - self._last_cleanup > self.cleanup_interval:
                self._prune(now, window_sec)

            timestamps = self._records.get(key, [])
            cutoff = now - window_sec
            valid_timestamps = [ts for ts in timestamps if ts > cutoff]

            if len(valid_timestamps) >= max_reqs:
                oldest = valid_timestamps[0]
                retry_after = max(1.0, round(window_sec - (now - oldest), 1))
                self._records[key] = valid_timestamps
                return False, 0, retry_after

            valid_timestamps.append(now)
            self._records[key] = valid_timestamps
            remaining = max_reqs - len(valid_timestamps)
            return True, remaining, 0.0

    def _prune(self, now: float, window_sec: float) -> None:
        cutoff = now - window_sec
        stale_keys = [k for k, ts_list in self._records.items() if not ts_list or ts_list[-1] <= cutoff]
        for k in stale_keys:
            del self._records[k]
        self._last_cleanup = now

    def reset_for_testing(self) -> None:
        with self._lock:
            self._records.clear()


# Global rate limiter instances for endpoints
_challenge_limiter = InMemoryRateLimiter(default_limit=30, window_seconds=60.0)
_verify_limiter = InMemoryRateLimiter(default_limit=30, window_seconds=60.0)
_identify_limiter = InMemoryRateLimiter(default_limit=15, window_seconds=60.0)

# Concurrency semaphore for CPU-intensive SpeechBrain inference
_inference_semaphore = asyncio.Semaphore(MAX_CONCURRENT_INFERENCES)


def get_actor_rate_key(actor: Optional[Union[AuthenticatedUser, AuthenticatedDevice]], request: Request) -> str:
    """Derive rate limit key strictly from verified identity."""
    if isinstance(actor, AuthenticatedUser):
        return f"user:{actor.uid}"
    if isinstance(actor, AuthenticatedDevice):
        return f"device:{actor.device_id}"
    client_host = request.client.host if request.client else "anonymous"
    return f"ip:{client_host}"


def enforce_rate_limit(limiter: InMemoryRateLimiter, key: str, limit: Optional[int] = None) -> None:
    """Enforce rate limit; raises HTTP 429 Too Many Requests if exceeded."""
    allowed, remaining, retry_after = limiter.check_rate_limit(key, limit=limit)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too Many Requests: Rate limit exceeded. Please retry after {int(retry_after)} seconds.",
            headers={"Retry-After": str(int(retry_after))},
        )


async def acquire_inference_slot(timeout: float = 10.0):
    """
    Concurrency control guard. Prevents CPU starvation by bounding parallel
    SpeechBrain ECAPA-TDNN feature extractions to MAX_CONCURRENT_INFERENCES.
    """
    try:
        await asyncio.wait_for(_inference_semaphore.acquire(), timeout=timeout)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=503,
            detail="Service Busy: Maximum biometric inference concurrency reached. Please retry shortly.",
        )


def release_inference_slot():
    """Release acquired inference concurrency slot."""
    _inference_semaphore.release()
