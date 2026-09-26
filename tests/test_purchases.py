"""Purchase history: the wallet signs the statement the pay service issues. No network."""

from __future__ import annotations

import httpx
import pytest

from witan_sdk import Witan, WitanError
from witan_sdk.errors import PaymentRequiredError

eth_account = pytest.importorskip("eth_account")
from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402

KEY = "0x" + "11" * 32
WALLET = Account.from_key(KEY).address.lower()
ITEM = {"id": "4", "kind": "dataset", "dataset": {"slug": "paid-one", "version": 3}, "price": "$0.10",
        "amountMicro": 100000, "network": "eip155:84532", "transaction": "0x" + "ab" * 32, "status": "settled",
        "createdAt": "2026-09-25T00:00:00Z", "settledAt": "2026-09-25T00:00:05Z", "dispute": None,
        "disputeUntil": "2026-10-02T00:00:05Z"}


def statement(time: int = 1000) -> str:
    return f"WITAN purchase history\nwallet: {WALLET}\norigin: http://pay.test\ntime: {time}"


def client(handler) -> Witan:
    return Witan("km_test", base_url="http://api.test", pay_url="http://pay.test", transport=httpx.MockTransport(handler))


def test_purchases_signs_the_issued_statement_with_the_wallet() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "pay.test"
        assert "authorization" not in request.headers  # the API key never goes to the pay service
        if request.url.path == "/purchases/statement":
            assert request.url.params["wallet"] == WALLET
            return httpx.Response(200, json={"statement": statement(), "wallet": WALLET, "time": 1000, "expiresIn": 300})
        assert request.url.path == "/purchases"
        seen["headers"] = dict(request.headers)
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"wallet": WALLET, "purchases": [ITEM], "next": None})

    r = client(handler).purchases(private_key=KEY, limit=10, before="99")
    assert r["purchases"][0]["dataset"]["slug"] == "paid-one"
    h = seen["headers"]
    assert h["x-witan-wallet"] == WALLET and h["x-witan-time"] == "1000"
    assert Account.recover_message(encode_defunct(text=statement()), signature=h["x-witan-signature"]).lower() == WALLET
    assert seen["params"] == {"limit": "10", "before": "99"}


def test_the_wallet_key_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WITAN_WALLET_KEY", KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/purchases/statement":
            return httpx.Response(200, json={"statement": statement(), "wallet": WALLET, "time": 1000})
        return httpx.Response(200, json={"wallet": request.headers["x-witan-wallet"], "purchases": [], "next": None})

    assert client(handler).purchases()["wallet"] == WALLET


def test_no_wallet_key_is_an_error_before_any_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WITAN_WALLET_KEY", raising=False)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500)

    with pytest.raises(PaymentRequiredError):
        client(handler).purchases()
    assert calls == []


def test_a_refused_signature_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/purchases/statement":
            return httpx.Response(200, json={"statement": statement(), "wallet": WALLET, "time": 1000})
        return httpx.Response(401, json={"error": "the signed statement has expired — ask for a new one"})

    with pytest.raises(WitanError, match="expired"):
        client(handler).purchases(private_key=KEY)


def test_projects_buy_posts_the_version_with_the_api_key() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.content
        return httpx.Response(200, json={"project": "paid-one", "version": 3, "already": False,
                                         "chargedMicro": 100000, "balanceMicro": 900000})

    r = client(handler).projects.buy("paid-one", version=3)
    assert r["chargedMicro"] == 100000
    assert seen["path"] == "/projects/paid-one/buy" and seen["auth"] == "Bearer km_test"
    import json as _json

    assert _json.loads(seen["body"]) == {"version": 3}


def test_projects_buy_short_of_credits_raises_payment_required() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": "not enough credits: v3 of paid-one costs $0.10",
                                         "priceMicro": 100000, "balanceMicro": 0, "topup": "http://pay.test/paid/credits?operator=o"})

    with pytest.raises(PaymentRequiredError, match="not enough credits"):
        client(handler).projects.buy("paid-one")
