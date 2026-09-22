"""x402 purchases. Optional: needs ``pip install "witan-sdk[x402]"``.

The wallet key signs an EIP-3009 transfer authorization for the exact price the
pay service quotes in its 402; the x402 facilitator settles it on-chain and the
body of the resource comes back in the same round trip. Nothing is broadcast by
this process and the key is never sent anywhere."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Any

from .errors import PaymentRequiredError, WitanError


def _load_x402():
    try:
        from eth_account import Account
        from x402 import x402Client
        from x402.http.clients import x402HttpxClient
        from x402.mechanisms.evm.exact import register_exact_evm_client
        from x402.mechanisms.evm.signers import EthAccountSigner
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise PaymentRequiredError(
            'x402 purchases need the extra: pip install "witan-sdk[x402]"'
        ) from exc
    return Account, x402Client, x402HttpxClient, register_exact_evm_client, EthAccountSigner


def purchase(pay_url: str, path: str, params: dict[str, Any], private_key: str | None) -> dict[str, Any]:
    key = private_key or os.environ.get("WITAN_WALLET_KEY")
    if not key:
        raise PaymentRequiredError("no wallet key: pass private_key= or set WITAN_WALLET_KEY")
    Account, x402Client, x402HttpxClient, register_exact_evm_client, EthAccountSigner = _load_x402()

    async def run() -> dict[str, Any]:
        client = x402Client()
        register_exact_evm_client(client, EthAccountSigner(Account.from_key(key)))
        async with x402HttpxClient(client, base_url=pay_url, timeout=90.0) as http:
            response = await http.get(path, params={k: v for k, v in params.items() if v is not None})
            if response.status_code >= 400:
                detail = response.text[:300]
                raise WitanError(f"purchase failed: {detail or response.reason_phrase}",
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
