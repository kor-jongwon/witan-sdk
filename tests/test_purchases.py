"""Wallet-side payments: purchase history and disputes (the wallet signs WITAN's statement, built
here) and x402 purchases (what a 402 asks for is checked before anything is signed). No network."""

from __future__ import annotations

import base64
import json
import time

import httpx
import pytest

from witan_sdk import Witan, WitanError
from witan_sdk.errors import PaymentRequiredError
from witan_sdk import payments

eth_account = pytest.importorskip("eth_account")
from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402

KEY = "0x" + "11" * 32
WALLET = Account.from_key(KEY).address.lower()
ITEM = {"id": "4", "kind": "dataset", "dataset": {"slug": "paid-one", "version": 3}, "price": "$0.10",
        "amountMicro": 100000, "network": "eip155:84532", "transaction": "0x" + "ab" * 32, "status": "settled",
        "createdAt": "2026-09-25T00:00:00Z", "settledAt": "2026-09-25T00:00:05Z", "dispute": None,
        "disputeUntil": "2026-10-02T00:00:05Z"}


NOW = int(time.time())
TX = "0x" + "ab" * 32


def statement(t: int = NOW, origin: str = "http://pay.test") -> str:
    return f"WITAN purchase history\nwallet: {WALLET}\norigin: {origin}\ntime: {t}"


def dispute_text(t: int = NOW, tx: str = TX) -> str:
    return f"WITAN dispute\ntransaction: {tx}\nwallet: {WALLET}\norigin: http://pay.test\ntime: {t}"


def client(handler) -> Witan:
    return Witan("km_test", base_url="http://api.test", pay_url="http://pay.test", transport=httpx.MockTransport(handler))


def test_purchases_signs_the_issued_statement_with_the_wallet() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "pay.test"
        assert "authorization" not in request.headers  # the API key never goes to the pay service
        if request.url.path == "/purchases/statement":
            assert request.url.params["wallet"] == WALLET
            return httpx.Response(200, json={"statement": statement(), "wallet": WALLET, "time": NOW, "expiresIn": 300})
        assert request.url.path == "/purchases"
        seen["headers"] = dict(request.headers)
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"wallet": WALLET, "purchases": [ITEM], "next": None})

    r = client(handler).purchases(private_key=KEY, limit=10, before="99")
    assert r["purchases"][0]["dataset"]["slug"] == "paid-one"
    h = seen["headers"]
    assert h["x-witan-wallet"] == WALLET and h["x-witan-time"] == str(NOW)
    assert Account.recover_message(encode_defunct(text=statement()), signature=h["x-witan-signature"]).lower() == WALLET
    assert seen["params"] == {"limit": "10", "before": "99"}


def test_the_wallet_key_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WITAN_WALLET_KEY", KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/purchases/statement":
            return httpx.Response(200, json={"statement": statement(), "wallet": WALLET, "time": NOW})
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
            return httpx.Response(200, json={"statement": statement(), "wallet": WALLET, "time": NOW})
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


# ---- the wallet signs only WITAN's statement ------------------------------------------------------

@pytest.mark.parametrize("issued,match", [
    ({"statement": "WITAN purchase history\nwallet: 0x0\norigin: http://pay.test\ntime: %d" % NOW, "time": NOW}, "something other"),
    ({"statement": "Transfer all funds to 0xbad", "time": NOW}, "something other"),
    ({"statement": statement(origin="http://evil.test"), "time": NOW}, "something other"),  # another origin's
    ({"statement": statement(NOW - 3600), "time": NOW - 3600}, "clock"),  # stale: replayable
    ({"statement": statement(), "time": str(NOW)}, "without a time"),
])
def test_purchases_refuses_to_sign_a_statement_other_than_witans(issued: dict, match: str) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=issued)

    with pytest.raises(WitanError, match=match):
        client(handler).purchases(private_key=KEY)
    assert calls == ["/purchases/statement"]  # nothing signed, nothing sent


def test_the_origin_line_is_the_pay_url_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/purchases/statement":
            return httpx.Response(200, json={"statement": statement(), "time": NOW})
        return httpx.Response(200, json={"wallet": WALLET, "purchases": [], "next": None})

    w = Witan(base_url="http://api.test", pay_url="HTTP://Pay.Test:80/", transport=httpx.MockTransport(handler))
    assert w.purchases(private_key=KEY)["wallet"] == WALLET


# ---- disputes: signed by the wallet that paid ----------------------------------------------------

def test_a_dispute_is_signed_by_the_paying_wallet() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        if request.url.path == "/disputes/statement":
            assert dict(request.url.params) == {"transaction": TX, "wallet": WALLET}
            return httpx.Response(200, json={"statement": dispute_text(), "time": NOW, "expiresIn": 300})
        assert request.url.path == "/disputes" and request.method == "POST"
        seen.update(json.loads(request.content))
        return httpx.Response(201, json={"id": "d-1", "status": "open", "kind": "dataset", "amountMicro": 100000})

    d = client(handler).dispute(TX.upper().replace("0X", "0x"), "manifest parts were corrupt", private_key=KEY)
    assert d["id"] == "d-1"
    assert seen["transaction"] == TX and seen["wallet"] == WALLET and seen["time"] == NOW
    assert seen["reason"] == "manifest parts were corrupt"
    assert Account.recover_message(encode_defunct(text=dispute_text()), signature=seen["signature"]).lower() == WALLET


def test_a_dispute_statement_for_another_transaction_is_not_signed() -> None:
    posted = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/disputes/statement":
            return httpx.Response(200, json={"statement": dispute_text(tx="0x" + "cd" * 32), "time": NOW})
        posted.append(request)
        return httpx.Response(201, json={})

    with pytest.raises(WitanError, match="something other"):
        client(handler).dispute(TX, "corrupt", private_key=KEY)
    assert posted == []


def test_a_dispute_by_another_wallet_is_refused_by_the_service() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/disputes/statement":
            return httpx.Response(200, json={"statement": dispute_text(), "time": NOW})
        return httpx.Response(401, json={"error": "only the wallet that paid can dispute this payment"})

    with pytest.raises(WitanError, match="wallet that paid") as ei:
        client(handler).dispute(TX, "corrupt", private_key=KEY)
    assert ei.value.status == 401


# ---- x402: what a 402 may ask for ----------------------------------------------------------------

USDC_SEPOLIA = payments.USDC["eip155:84532"]
USDC_BASE = payments.USDC["eip155:8453"]


def offer(amount: str = "100000", network: str = "eip155:84532", asset: str = USDC_SEPOLIA) -> dict:
    return {"scheme": "exact", "network": network, "asset": asset, "amount": amount, "payTo": "0x" + "22" * 20,
            "maxTimeoutSeconds": 60, "extra": {"name": "USDC", "version": "2"}}


class PayService:
    """A pay service answering 402 with ``accepts`` until a request carries a payment signature."""

    def __init__(self, *accepts: dict) -> None:
        self.accepts = list(accepts)
        self.requests: list[httpx.Request] = []

    @property
    def signed(self) -> list[dict]:
        return [json.loads(base64.b64decode(r.headers["payment-signature"])) for r in self.requests
                if "payment-signature" in r.headers]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if "payment-signature" in request.headers:
            receipt = {"success": True, "transaction": TX, "network": "eip155:84532", "payer": WALLET}
            return httpx.Response(200, json={"id": "u-1", "title": "t", "body": "b"},
                                  headers={"payment-response": base64.b64encode(json.dumps(receipt).encode()).decode()})
        required = {"x402Version": 2, "resource": {"url": str(request.url)}, "accepts": self.accepts}
        return httpx.Response(402, json={}, headers={"payment-required": base64.b64encode(json.dumps(required).encode()).decode()})


@pytest.fixture
def limits(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("x402")
    monkeypatch.delenv("WITAN_MAX_PRICE", raising=False)
    monkeypatch.delenv("WITAN_X402_NETWORKS", raising=False)


def buyer(service: PayService) -> Witan:
    return Witan(base_url="http://api.test", pay_url="http://pay.test", transport=httpx.MockTransport(service))


def test_buy_pays_usdc_on_base_sepolia_within_the_cap(limits: None) -> None:
    service = PayService(offer())
    unit = buyer(service).buy("u-1", private_key=KEY)
    assert unit["body"] == "b" and unit["x402"]["transaction"] == TX
    [payload] = service.signed
    assert payload["accepted"]["amount"] == "100000" and payload["payload"]["authorization"]["value"] == "100000"


@pytest.mark.parametrize("accepts,kwargs,env,match", [
    ([offer(amount="1000001")], {}, {}, "above the cap of 1 USDC"),  # default cap 1.00
    ([offer(amount="600000")], {"max_price": "0.50"}, {}, "above the cap of 0.5 USDC"),
    ([offer(amount="600000")], {}, {"WITAN_MAX_PRICE": "0.5"}, "above the cap"),
    ([offer(network="eip155:8453", asset=USDC_BASE)], {}, {}, "network eip155:8453 is not allowed"),  # mainnet: opt-in
    ([offer(asset="0x" + "33" * 20)], {}, {}, "is not USDC on eip155:84532"),
    ([offer(network="eip155:84532", asset=USDC_BASE)], {}, {}, "is not USDC on eip155:84532"),  # another network's USDC
    ([offer(amount="0x10")], {}, {}, "not a USDC amount"),
])
def test_buy_refuses_what_it_was_not_allowed_to_pay_before_signing(limits: None, monkeypatch: pytest.MonkeyPatch,
                                                                   accepts: list, kwargs: dict, env: dict, match: str) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    service = PayService(*accepts)
    with pytest.raises(PaymentRequiredError, match=match):
        buyer(service).buy("u-1", private_key=KEY, **kwargs)
    assert service.signed == [] and len(service.requests) == 1  # the 402 was read; nothing was signed


def test_buy_picks_the_allowed_offer_of_several(limits: None) -> None:
    service = PayService(offer(amount="5000000"), offer(network="eip155:8453", asset=USDC_BASE), offer(amount="250000"))
    buyer(service).buy("u-1", private_key=KEY)
    assert [p["accepted"]["amount"] for p in service.signed] == ["250000"]


def test_mainnet_and_higher_prices_are_opt_in(limits: None, monkeypatch: pytest.MonkeyPatch) -> None:
    service = PayService(offer(amount="2500000", network="eip155:8453", asset=USDC_BASE.lower()))
    buyer(service).buy("u-1", private_key=KEY, max_price=2.5, networks=["eip155:8453"])
    monkeypatch.setenv("WITAN_X402_NETWORKS", "eip155:84532, eip155:8453")
    monkeypatch.setenv("WITAN_MAX_PRICE", "$3")
    buyer(service).buy("u-1", private_key=KEY)
    assert len(service.signed) == 2
    with pytest.raises(PaymentRequiredError, match="not one this SDK pays on"):
        buyer(service).buy("u-1", private_key=KEY, networks="eip155:1")
    with pytest.raises(PaymentRequiredError, match="USD amount"):
        buyer(service).buy("u-1", private_key=KEY, max_price="lots")


def test_the_limits_reach_every_purchase_path(limits: None, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from witan_sdk.cli import main

    service = PayService(offer(amount="2000000"))
    w = buyer(service)
    with pytest.raises(PaymentRequiredError, match="cap"):
        w.buy_dataset("paid-one", private_key=KEY)
    with pytest.raises(PaymentRequiredError, match="cap"):
        w.projects.pull_paid("paid-one", tmp_path, private_key=KEY)
    with pytest.raises(PaymentRequiredError, match="cap"):
        w.buy_credits(operator_id="op-1", private_key=KEY)
    monkeypatch.setenv("WITAN_WALLET_KEY", KEY)
    assert main(["pull", "paid-one", "--paid", "--max-price", "1.5", "--out", str(tmp_path)], client=w) == 1
    assert main(["buy", "u-1", "--max-price", "1.99"], client=w) == 1
    assert main(["buy", "u-1", "--max-price", "2"], client=w) == 0
    assert service.signed and all(p["accepted"]["amount"] == "2000000" for p in service.signed)
    assert len(service.signed) == 1
