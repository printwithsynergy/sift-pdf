"""Request-ID middleware and instance identity."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from ulid import ULID

INSTANCE_ID: str = str(ULID())
_HEADER = "X-Sift-Request-Id"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Stamp every response with X-Sift-Request-Id and X-Sift-Instance-Id."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(_HEADER) or str(ULID())
        response: Response = await call_next(request)
        response.headers[_HEADER] = request_id
        response.headers["X-Sift-Instance-Id"] = INSTANCE_ID
        return response


__all__ = ["INSTANCE_ID", "RequestIdMiddleware"]
