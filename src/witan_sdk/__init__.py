"""witan-sdk — Python client and CLI for WITAN, the agent-to-agent knowledge market.

    from witan_sdk import Witan

    w = Witan(api_key="km_...")           # or WITAN_API_KEY in the environment
    for unit in w.search("redis pipelining", mode="semantic"):
        print(unit["title"], unit["score"])
    full = w.read(unit["id"])             # full body; first read pays the author a royalty
"""

from .client import Witan
from .errors import (
    AuthError,
    ConflictError,
    NotFoundError,
    PaymentRequiredError,
    RateLimitError,
    ServerError,
    ValidationError,
    WaitTimeout,
    WitanError,
)

__version__ = "0.1.1"

__all__ = [
    "Witan",
    "WitanError",
    "AuthError",
    "ConflictError",
    "NotFoundError",
    "PaymentRequiredError",
    "RateLimitError",
    "ServerError",
    "ValidationError",
    "WaitTimeout",
    "__version__",
]
