"""Pricing what you sell: the calls and the CLI command. No network."""

from __future__ import annotations

import json

import httpx
import pytest

from witan_sdk import Witan
from witan_sdk.cli import main

UNIT = "5e5fc8dd-af67-4f34-839b-b366ef05d43d"


def client(seen: list[httpx.Request]) -> Witan:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content) if request.content else {}
        if request.method == "PUT" and request.url.path == f"/knowledge/{UNIT}/price":
            price = body.get("price", "0.25")
            default = price is None
            return httpx.Response(200, json={"id": UNIT, "groupId": UNIT, "price": "$0.01" if default else f"${price}",
                                             "priceMicro": 10000, "default": default,
                                             "trialSale": body.get("trialSale", False), "changed": "price" in body})
        if request.method == "PATCH" and request.url.path == "/projects/probe-latency":
            return httpx.Response(200, json={"slug": "probe-latency", "access": "paid", "price": "$2.50",
                                             "priceMicro": 2500000, "default": False,
                                             "trialSale": body.get("trialSale", False), "changed": "price" in body})
        if request.method == "POST" and request.url.path == "/knowledge":
            return httpx.Response(201, json={"id": UNIT, "status": "submitted", **({"price": f"${body['price']}"} if "price" in body else {})})
        return httpx.Response(404, json={"error": "no route"})

    return Witan(api_key="km_test", base_url="http://witan.test", transport=httpx.MockTransport(handler))


def test_set_price_sends_only_what_changes():
    seen: list[httpx.Request] = []
    w = client(seen)
    w.set_price(UNIT, "0.25")
    w.set_price(UNIT, trial_sale=True)
    w.set_price(UNIT, None)                       # back to the platform default
    assert [json.loads(r.content) for r in seen] == [{"price": "0.25"}, {"trialSale": True}, {"price": None}]
    assert all(r.method == "PUT" and r.headers["authorization"] == "Bearer km_test" for r in seen)


def test_set_price_needs_something_to_change():
    with pytest.raises(ValueError):
        client([]).set_price(UNIT)


def test_submit_and_projects_carry_price():
    seen: list[httpx.Request] = []
    w = client(seen)
    w.submit("t" * 10, "b" * 60, "infra-measurement", source_declaration="own run", price="0.05", trial_sale=True)
    w.projects.update("probe-latency", price="2.50")
    w.projects.update("probe-latency", price=None, trial_sale=False)
    w.projects.update("probe-latency", title="Probe latency")   # no price key at all
    bodies = [json.loads(r.content) for r in seen]
    assert bodies[0]["price"] == "0.05" and bodies[0]["trialSale"] is True
    assert bodies[1] == {"price": "2.50"}
    assert bodies[2] == {"price": None, "trialSale": False}
    assert bodies[3] == {"title": "Probe latency"}


def test_cli_price_unit_and_dataset(capsys: pytest.CaptureFixture[str]):
    seen: list[httpx.Request] = []
    w = client(seen)
    assert main(["price", UNIT, "0.25", "--trial"], client=w) == 0
    assert seen[-1].url.path == f"/knowledge/{UNIT}/price" and json.loads(seen[-1].content) == {"price": "0.25", "trialSale": True}
    out = capsys.readouterr().out
    assert "$0.25" in out and "trial sales on" in out
    assert main(["price", "probe-latency", "default"], client=w) == 0
    assert seen[-1].method == "PATCH" and json.loads(seen[-1].content) == {"price": None}
    capsys.readouterr()
    assert main(["price", UNIT, "--no-trial"], client=w) == 0
    assert json.loads(seen[-1].content) == {"trialSale": False} and "price unchanged" in capsys.readouterr().out


def test_cli_price_with_nothing_to_change():
    seen: list[httpx.Request] = []
    with pytest.raises(SystemExit):
        main(["price", UNIT], client=client(seen))
    assert seen == []


def test_buy_with_credits_and_cli(capsys: pytest.CaptureFixture[str]):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST" and request.url.path == f"/knowledge/{UNIT}/buy":
            return httpx.Response(200, json={"id": UNIT, "groupId": UNIT, "already": False, "chargedMicro": 250000,
                                             "grantMicro": 50000, "paidMicro": 200000, "balanceMicro": 800000})
        return httpx.Response(404, json={"error": "no route"})

    w = Witan(api_key="km_test", base_url="http://witan.test", transport=httpx.MockTransport(handler))
    assert w.buy_with_credits(UNIT)["chargedMicro"] == 250000
    assert seen[-1].headers["authorization"] == "Bearer km_test" and json.loads(seen[-1].content) == {}
    assert main(["buy", UNIT, "--credits"], client=w) == 0
    assert "paid $0.25 ($0.05 given)" in capsys.readouterr().out
