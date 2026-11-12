"""The URL this API is publicly reachable at, for links handed to browsers
(SCORM launch/commit URLs) and callbacks handed to QStash.

`API_BASE_URL` wins when it is set to a real address. When it is left at its
localhost default (or set to any loopback address) on a deployed environment,
links built from it point at the visitor's own machine ("localhost refused to
connect"), so we fall back to the base URL of the request currently being
served. Uvicorn runs with --proxy-headers, so behind Railway's proxy that is
the public https:// host the caller used.
"""

from __future__ import annotations

from contextvars import ContextVar
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}

_request_base_url: ContextVar[str | None] = ContextVar("request_base_url", default=None)


def _is_loopback(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return not host or host in _LOOPBACK_HOSTS or host.endswith(".localhost")


def public_api_base_url() -> str:
    """Base URL (no trailing slash) to put in links that leave this server."""
    configured = (settings.api_base_url or "").rstrip("/")
    if configured and not _is_loopback(configured):
        return configured
    from_request = _request_base_url.get()
    if from_request:
        return from_request
    return configured or "http://localhost:8000"


class RequestBaseURLMiddleware:
    """Records the current request's base URL for `public_api_base_url()`."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = _request_base_url.set(str(Request(scope).base_url).rstrip("/"))
        try:
            await self.app(scope, receive, send)
        finally:
            _request_base_url.reset(token)
