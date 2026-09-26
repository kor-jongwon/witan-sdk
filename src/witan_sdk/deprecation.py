"""Server deprecation notices.

When WITAN schedules an API route for removal it answers that route with a
``Deprecation`` header (RFC 9745), usually with ``Sunset`` (RFC 8594, the date it
stops working) and ``Link: <…>; rel="deprecation"`` (where the migration is
described). The SDK turns that into a :class:`WitanDeprecationWarning`, once per
route per process, so an agent's logs say what to change before anything breaks."""

from __future__ import annotations

import re
import sys
import threading
import warnings
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx


class WitanDeprecationWarning(FutureWarning):
    """A route this SDK called is deprecated on the server.

    A ``FutureWarning``, so Python shows it by default. Silence it with
    ``warnings.simplefilter("ignore", WitanDeprecationWarning)`` or fail on it in CI with
    ``warnings.simplefilter("error", WitanDeprecationWarning)``."""


_seen: set[tuple[str, str]] = set()
_lock = threading.Lock()
_LINK = re.compile(r'\s*<([^>]*)>\s*;(.*)')
_REL = re.compile(r'rel\s*=\s*"?([^";]*)"?', re.I)


def _date(value: str | None) -> str | None:
    """``@1790812800`` (RFC 9745) or an HTTP-date (RFC 8594) as YYYY-MM-DD."""
    if not value:
        return None
    value = value.strip()
    try:
        if value.startswith("@"):
            return datetime.fromtimestamp(int(value[1:]), tz=timezone.utc).date().isoformat()
        return parsedate_to_datetime(value).date().isoformat()
    except (ValueError, TypeError, OverflowError, OSError, IndexError):
        return None


def _deprecation_link(header: str | None) -> str | None:
    for part in (header or "").split(","):
        m = _LINK.match(part)
        if m and any(r.strip().lower() == "deprecation" for rel in _REL.findall(m.group(2)) for r in rel.split()):
            return m.group(1)
    return None


def notice(response: httpx.Response) -> dict[str, Any] | None:
    """The deprecation a response announces, or ``None``: ``{method, path, since, sunset, link, message}``."""
    raw = response.headers.get("deprecation")
    if raw is None or raw.strip().lower() == "false":
        return None
    request = response.request
    method, path = request.method, request.url.path
    since = _date(raw)
    sunset = _date(response.headers.get("sunset"))
    link = _deprecation_link(response.headers.get("link"))
    message = f"WITAN API: {method} {path} is deprecated"
    message += f" since {since}" if since else ""
    message += f" and stops working on {sunset}" if sunset else ""
    message += f"; see {link}" if link else ""
    message += ". Upgrade the SDK (pip install -U witan-sdk) or follow the migration note."
    return {"method": method, "path": path, "since": since, "sunset": sunset, "link": link, "message": message}


def _stacklevel() -> int:
    """Point the warning at the first frame outside the SDK and its HTTP stack."""
    level, frame = 1, sys._getframe(1)
    while frame is not None:
        module = frame.f_globals.get("__name__", "")
        if not module.startswith(("witan_sdk", "httpx", "httpcore", "x402", "asyncio")):
            return level
        frame, level = frame.f_back, level + 1
    return level


def warn_if_deprecated(response: httpx.Response) -> None:
    """httpx response hook: warn once per route when the server says it is deprecated."""
    found = notice(response)
    if found is None:
        return
    key = (found["method"], found["link"] or found["path"])
    with _lock:
        if key in _seen:
            return
        _seen.add(key)
    warnings.warn(found["message"], WitanDeprecationWarning, stacklevel=_stacklevel())
