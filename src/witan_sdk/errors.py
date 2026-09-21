"""Typed errors. Every non-2xx answer from WITAN becomes one of these, carrying
the HTTP status, the server's error message and the raw JSON body."""

from __future__ import annotations

from typing import Any

import httpx


class WitanError(Exception):
    """Base class for every error raised by the SDK."""

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None,
                 body: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.body = body

    def __str__(self) -> str:
        return f"{self.message} (HTTP {self.status})" if self.status else self.message


class ValidationError(WitanError):
    """400 — the request body or query did not pass the server's schema."""


class AuthError(WitanError):
    """401/403 — missing, malformed or unauthorized API key."""


class PaymentRequiredError(WitanError):
    """402 — the resource is paid; use ``buy()`` (needs the ``x402`` extra) or a wallet."""


class NotFoundError(WitanError):
    """404 — no such unit, project, contribution or topic."""


class ConflictError(WitanError):
    """409 — e.g. a revision is already pending for this lineage."""


class RateLimitError(WitanError):
    """429 — slow down; limits are per key and per IP."""


class ServerError(WitanError):
    """5xx — WITAN failed; safe to retry after a moment."""


class WaitTimeout(WitanError):
    """A ``wait*`` helper gave up before the pipeline reached a terminal state."""


_BY_STATUS: dict[int, type[WitanError]] = {
    400: ValidationError,
    401: AuthError,
    402: PaymentRequiredError,
    403: AuthError,
    404: NotFoundError,
    409: ConflictError,
    429: RateLimitError,
}


def raise_for(response: httpx.Response) -> None:
    """Turn an httpx error response into the matching WitanError."""
    try:
        body: Any = response.json()
    except ValueError:
        body = {"error": response.text}
    message = None
    if isinstance(body, dict):
        # WITAN's own errors are {error: "..."}; Fastify schema errors carry the generic
        # phrase in `error` and the useful detail in `message`, so prefer `message`.
        message = body.get("message") or body.get("error")
    message = message or response.reason_phrase or f"HTTP {response.status_code}"
    cls = _BY_STATUS.get(response.status_code)
    if cls is None:
        cls = ServerError if response.status_code >= 500 else WitanError
    code = body.get("code") if isinstance(body, dict) else None
    raise cls(str(message), status=response.status_code, code=code, body=body)
