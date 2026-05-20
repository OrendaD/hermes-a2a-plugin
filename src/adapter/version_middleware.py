"""A2A version negotiation middleware for Starlette.

Rejects requests without ``A2A-Version: 1.0`` header on the
``/a2a/jsonrpc`` endpoint by returning a JSON-RPC error response.
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Paths that require A2A-Version header validation
_A2A_RPC_PATHS = {"/a2a/jsonrpc"}

# Error code per A2A spec: VersionNotSupportedError
VERSION_NOT_SUPPORTED_CODE = -32009


class A2AVersionMiddleware(BaseHTTPMiddleware):
    """Reject requests without A2A-Version 1.0 on A2A JSON-RPC paths.

    Per the A2A spec, clients MUST send ``A2A-Version: 1.0`` with every
    JSON-RPC request. Missing or unsupported versions are rejected with
    a JSON-RPC error response (code -32009).
    """

    async def dispatch(self, request, call_next):
        path = request.url.path.rstrip("/")
        if path in _A2A_RPC_PATHS:
            version = request.headers.get("A2A-Version", "")
            if not version.startswith("1.0"):
                raw_header = request.headers.get("A2A-Version")
                detail = raw_header if raw_header else "missing"
                logger.warning(
                    "Rejected A2A request with unsupported version '%s' (path: %s)",
                    detail, path,
                )
                return JSONResponse(
                    status_code=200,  # JSON-RPC always returns 200
                    content={
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": VERSION_NOT_SUPPORTED_CODE,
                            "message": (
                                f"Version not supported: {detail}. "
                                "Expected: 1.0"
                            ),
                        },
                    },
                )
        return await call_next(request)
