"""Configurable per-peer rate limiting middleware for the A2A server.

Tracks requests by SHA256 hash of the Authorization header (bearer token).
Returns HTTP 429 with Retry-After header when a peer exceeds its rate limit.
Only applies to the /a2a/jsonrpc path.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Paths subject to rate limiting
_A2A_RPC_PATHS = {"/a2a/jsonrpc"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate-limit requests per peer on A2A JSON-RPC paths.

    Tracks peers by SHA256 hash of the ``Authorization`` header value.
    Uses a fixed 1-minute sliding window. When the limit is exceeded,
    returns HTTP 429 with a ``Retry-After`` header set to 60 seconds.

    Set ``rate_limit`` to 0 or a negative value to disable rate limiting.
    When disabled, all requests pass through without tracking.
    """

    def __init__(self, app, rate_limit: int = 0):
        super().__init__(app)
        self._rate_limit = rate_limit  # 0 or negative = disabled
        self._buckets: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    async def dispatch(self, request, call_next):
        if self._rate_limit <= 0:
            return await call_next(request)

        path = request.url.path.rstrip("/")
        if path not in _A2A_RPC_PATHS:
            return await call_next(request)

        # Extract token hash for peer identification
        auth = request.headers.get("Authorization", "")
        if auth:
            token_hash = hashlib.sha256(auth.encode()).hexdigest()
        else:
            token_hash = "anonymous"

        now = time.time()
        with self._lock:
            timestamps = self._buckets.get(token_hash, [])
            # Prune timestamps older than 60 seconds
            cutoff = now - 60
            timestamps = [t for t in timestamps if t > cutoff]

            if len(timestamps) >= self._rate_limit:
                logger.warning(
                    "Rate limit exceeded for peer %s... (limit: %d req/min)",
                    token_hash[:12],
                    self._rate_limit,
                )
                return JSONResponse(
                    status_code=429,
                    headers={"Retry-After": "60"},
                    content={"error": "Rate limit exceeded"},
                )

            timestamps.append(now)
            self._buckets[token_hash] = timestamps

        return await call_next(request)
