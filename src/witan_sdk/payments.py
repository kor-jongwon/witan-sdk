"""x402 purchases. Optional: needs ``pip install "witan-sdk[x402]"``.

The wallet key signs an EIP-3009 transfer authorization for the exact price the
pay service quotes in its 402; the x402 facilitator settles it on-chain and the
body of the resource comes back in the same round trip. Nothing is broadcast by
this process and the key is never sent anywhere.

What the 402 asks for is checked before anything is signed: the network must be one
this machine allows (``networks=`` or ``WITAN_X402_NETWORKS``; Base Sepolia only by
default), the asset must be that network's USDC, and the amount must not exceed
``max_price`` (USD, or ``WITAN_MAX_PRICE``; 1.00 by default). Anything else is refused
with ``PaymentRequiredError`` naming the rule."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time as _time
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from typing import Any, Callable, Iterable

import httpx

from .deprecation import warn_if_deprecated
from .errors import PaymentRequiredError, WitanError, brief

# The USDC contract of each network a purchase may pay on (CAIP-2 → address).
USDC = {
    "eip155:84532": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",  # Base Sepolia
    "eip155:8453": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # Base
}
USDC_DECIMALS = 6
DEFAULT_NETWORKS = ("eip155:84532",)
DEFAULT_MAX_PRICE = "1.00"
STATEMENT_WINDOW_S = 300  # how long the pay service accepts a signed statement (pay/src/purchases.ts)
_ATOMIC = re.compile(r"[0-9]+")
_TX = re.compile(r"0x[0-9a-f]{64}")


def _load_x402():
    try:
        from eth_account import Account
        from x402 import x402Client
        from x402.http.clients.httpx import x402_httpx_transport
        from x402.mechanisms.evm.exact import register_exact_evm_client
        from x402.mechanisms.evm.signers import EthAccountSigner
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise PaymentRequiredError(
            'x402 purchases need the extra: pip install "witan-sdk[x402]"'
        ) from exc
    return Account, x402Client, x402_httpx_transport, register_exact_evm_client, EthAccountSigner


def _account(private_key: str | None):
    key = private_key or os.environ.get("WITAN_WALLET_KEY")
    if not key:
        raise PaymentRequiredError("no wallet key: pass private_key= or set WITAN_WALLET_KEY")
    try:
        from eth_account import Account
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise PaymentRequiredError('wallet signatures need the extra: pip install "witan-sdk[x402]"') from exc
    return Account.from_key(key)


def wallet_address(private_key: str | None) -> str:
    """The address of the wallet key (argument or ``WITAN_WALLET_KEY``), lowercase."""
    return _account(private_key).address.lower()


def sign_statement(statement: str, private_key: str | None) -> str:
    """EIP-191 personal_sign of ``statement`` with the wallet key, as 0x-hex. Only the
    signature leaves the process."""
    from eth_account.messages import encode_defunct

    return "0x" + bytes(_account(private_key).sign_message(encode_defunct(text=statement)).signature).hex()


# ---- statements the wallet signs: built here, never taken from the server ----------------

def pay_origin(pay_url: str) -> str:
    """The pay service's origin as its statements name it (PUBLIC_PAY_URL without trailing slash)."""
    from urllib.parse import urlsplit

    from .trust import origin_of

    return origin_of(pay_url) + urlsplit(pay_url.strip()).path.rstrip("/")


def purchase_statement(wallet: str, origin: str, time: int) -> str:
    """What the wallet signs to see its purchase history — pay/src/purchases.ts, character for character."""
    return f"WITAN purchase history\nwallet: {wallet.lower()}\norigin: {origin}\ntime: {time}"


def dispute_statement(transaction: str, wallet: str, origin: str, time: int) -> str:
    """What the paying wallet signs to open a dispute on ``transaction``."""
    return f"WITAN dispute\ntransaction: {transaction.lower()}\nwallet: {wallet.lower()}\norigin: {origin}\ntime: {time}"


def settlement_tx(transaction: str) -> str:
    tx = str(transaction).strip().lower()
    if not _TX.fullmatch(tx):
        raise WitanError("transaction must be the settlement tx hash (0x + 64 hex) — buy*() return it under x402['transaction']")
    return tx


def checked_time(issued: Any, build: Callable[[int], str], *, now: float | None = None) -> int:
    """The ``time`` of a statement the pay service issued, once the statement it sent is exactly the
    one ``build`` makes for that time and the time is within the service's window. The wallet then
    signs the text built here: a server cannot get it to sign anything else."""
    t = issued.get("time") if isinstance(issued, dict) else None
    if not isinstance(t, int) or isinstance(t, bool):
        raise WitanError("the pay service issued a statement without a time")
    skew = abs((_time.time() if now is None else now) - t)
    if skew > STATEMENT_WINDOW_S:
        raise WitanError(f"the pay service's statement is {skew:.0f} s away from this machine's clock "
                         f"(the limit is {STATEMENT_WINDOW_S} s) — check the clock")
    if issued.get("statement") != build(t):
        raise WitanError("the pay service asked the wallet to sign something other than WITAN's statement for "
                         "this origin and wallet — refusing to sign (is pay_url the service's public URL?)")
    return t


# ---- what a 402 may ask for ---------------------------------------------------------------

def allowed_networks(networks: "str | Iterable[str] | None" = None) -> tuple[str, ...]:
    """The networks a purchase may pay on: ``networks`` (a list or a comma list), else
    ``WITAN_X402_NETWORKS``, else Base Sepolia only."""
    if networks is None:
        networks = os.environ.get("WITAN_X402_NETWORKS") or ""
    if isinstance(networks, str):
        networks = networks.split(",")
    chosen = tuple(dict.fromkeys(n.strip() for n in networks if n and n.strip())) or DEFAULT_NETWORKS
    unknown = [n for n in chosen if n not in USDC]
    if unknown:
        raise PaymentRequiredError(f"network {unknown[0]} is not one this SDK pays on (USDC is known on {', '.join(USDC)})")
    return chosen


def price_cap(max_price: "str | Decimal | float | int | None" = None) -> int:
    """The most one purchase may cost, in USDC atomic units: ``max_price`` in USD, else
    ``WITAN_MAX_PRICE``, else 1.00."""
    raw = max_price if max_price is not None else (os.environ.get("WITAN_MAX_PRICE") or DEFAULT_MAX_PRICE)
    try:
        usd = Decimal(str(raw).strip().lstrip("$"))
    except InvalidOperation:
        usd = Decimal("NaN")
    if not usd.is_finite() or usd < 0:
        raise PaymentRequiredError(f"max price must be a USD amount such as 1.00, not {raw!r}")
    return int((usd * 10 ** USDC_DECIMALS).to_integral_value(rounding=ROUND_FLOOR))


def _usdc(atomic: int) -> str:
    return f"{Decimal(atomic).scaleb(-USDC_DECIMALS).normalize():f}"


def refusal(network: str, asset: str, amount: str, networks: tuple[str, ...], cap: int) -> str | None:
    """Why one payment option of a 402 may not be paid, or None when it may."""
    if network not in networks:
        return (f"network {network} is not allowed here (allowed: {', '.join(networks)}; "
                "opt in with networks= or WITAN_X402_NETWORKS)")
    if asset.lower() != USDC[network].lower():
        return f"asset {asset} is not USDC on {network} ({USDC[network]})"
    if not _ATOMIC.fullmatch(amount):
        return f"amount {amount!r} is not a USDC amount"
    if int(amount) > cap:
        return (f"the price, {_usdc(int(amount))} USDC, is above the cap of {_usdc(cap)} USDC "
                "(raise it with max_price= / --max-price / WITAN_MAX_PRICE)")
    return None


def _policy(networks: tuple[str, ...], cap: int) -> Callable[[int, list], list]:
    """An x402 policy: keeps the payment options ``refusal`` allows and refuses the purchase, with
    the reasons, when none is left — x402 runs policies before it signs anything."""
    def policy(version: int, requirements: list) -> list:
        ok, reasons = [], []
        for r in requirements:
            why = refusal(str(getattr(r, "network", "")), str(getattr(r, "asset", "")), str(r.get_amount()), networks, cap)
            if why is None:
                ok.append(r)
            else:
                reasons.append(why)
        if not ok:
            raise PaymentRequiredError("refusing to pay: " + "; ".join(dict.fromkeys(reasons)))
        return ok

    return policy


def purchase(pay_url: str, path: str, params: dict[str, Any], private_key: str | None, *,
             max_price: "str | Decimal | float | None" = None, networks: "str | Iterable[str] | None" = None,
             transport: Any = None) -> dict[str, Any]:
    key = private_key or os.environ.get("WITAN_WALLET_KEY")
    if not key:
        raise PaymentRequiredError("no wallet key: pass private_key= or set WITAN_WALLET_KEY")
    allowed = allowed_networks(networks)
    cap = price_cap(max_price)
    Account, x402Client, x402_httpx_transport, register_exact_evm_client, EthAccountSigner = _load_x402()

    async def run() -> dict[str, Any]:
        client = x402Client()
        register_exact_evm_client(client, EthAccountSigner(Account.from_key(key)))
        # The policy is the whole limit (USDC only, allowed networks, max_price): x402's own spend
        # controls would only get in first with a vaguer refusal, or cap max_price at their $1.
        client.set_spend_controls(False)
        client.register_policy(_policy(allowed, cap))
        async with httpx.AsyncClient(transport=x402_httpx_transport(client, transport), base_url=pay_url,
                                     timeout=90.0) as http:
            try:
                response = await http.get(path, params={k: v for k, v in params.items() if v is not None})
            except Exception as exc:
                from x402.schemas import NoMatchingRequirementsError

                cause = exc.__cause__  # x402 wraps what the policy raised
                if isinstance(cause, PaymentRequiredError):
                    raise cause from None
                if isinstance(cause, NoMatchingRequirementsError):
                    raise PaymentRequiredError(f"refusing to pay: {cause}") from exc
                if isinstance(exc, httpx.RequestError):
                    raise WitanError(f"cannot reach {pay_url}: {exc or type(exc).__name__} — check WITAN_PAY_URL "
                                     "(or WITAN_BASE_URL) and your network") from exc
                raise
            warn_if_deprecated(response)
            if response.status_code >= 400:
                raise WitanError(f"purchase failed: {brief(response.text) or response.reason_phrase}",
                                 status=response.status_code)
            body = response.json()
            # The settlement the pay service attached: {success, transaction, network, payer}.
            # `transaction` is the proof of purchase a dispute needs.
            settlement = response.headers.get("payment-response")
            if isinstance(body, dict) and settlement:
                try:
                    body["x402"] = json.loads(base64.b64decode(settlement))
                except (ValueError, TypeError):
                    pass
            return body

    try:
        return asyncio.run(run())
    except RuntimeError as exc:
        if "running event loop" in str(exc):
            raise WitanError("buy() cannot run inside an active event loop; call it from sync code "
                             "or use asyncio.to_thread") from exc
        raise
