"""What a first-time user meets when the origin is wrong, unreachable or not WITAN: a WitanError
that names the origin, never an httpx or JSON traceback — and a pay URL that follows the base URL."""

from __future__ import annotations

import httpx
import pytest

from witan_sdk import Witan, WitanError
from witan_sdk.cli import main
from witan_sdk.client import default_pay_url


def client(handler, base_url: str = "https://witan.example", **kw) -> Witan:
    return Witan("km_test", base_url=base_url, transport=httpx.MockTransport(handler), **kw)


def test_the_pay_url_follows_the_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WITAN_PAY_URL", raising=False)
    monkeypatch.delenv("WITAN_BASE_URL", raising=False)
    assert default_pay_url("https://witan.example") == "https://witan.example"
    for local in ("http://localhost:3000", "http://127.0.0.1:3000", "http://[::1]:3000"):
        assert default_pay_url(local) == "http://localhost:3001"
    assert Witan(base_url="https://witan.example/").pay_url == "https://witan.example"
    assert Witan().pay_url == "http://localhost:3001"
    monkeypatch.setenv("WITAN_PAY_URL", "https://pay.example/")
    assert Witan(base_url="https://witan.example").pay_url == "https://pay.example"
    assert Witan(base_url="https://witan.example", pay_url="https://other.example").pay_url == "https://other.example"


def test_an_unreachable_origin_is_named() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(WitanError, match=r"cannot reach https://witan\.example: connection refused"):
        client(refuse).search("redis")


def test_a_timeout_is_named() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(WitanError, match=r"https://witan\.example did not answer within 5s"):
        client(slow, timeout=5).search("redis")


def test_a_redirect_says_where_to_point() -> None:
    def to_https(request: httpx.Request) -> httpx.Response:
        return httpx.Response(301, headers={"location": "https://witan.example/search"})

    with pytest.raises(WitanError, match=r"redirected to https://witan\.example/search") as exc:
        client(to_https, base_url="http://witan.example").search("redis")
    assert exc.value.status == 301


def test_an_answer_that_is_not_json() -> None:
    def html(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text="<!doctype html><p>parked")

    with pytest.raises(WitanError, match=r"answered with text/html, not JSON"):
        client(html).search("redis")


def test_a_proxy_error_page_is_not_printed() -> None:
    page = "<!doctype html><html><body>" + "cloudflare " * 500 + "</body></html>"

    def bad_gateway(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, headers={"content-type": "text/html"}, text=page)

    with pytest.raises(WitanError) as exc:
        client(bad_gateway).search("redis")
    assert str(exc.value) == "Bad Gateway (HTTP 502)"
    assert len(exc.value.body["error"]) <= 500

    def long_text(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="x " * 400)

    with pytest.raises(WitanError) as exc:
        client(long_text).search("redis")
    assert len(exc.value.message) <= 300 and exc.value.message.endswith("...")


def test_the_pay_service_unreachable_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WITAN_PAY_URL", raising=False)

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    with pytest.raises(WitanError, match=r"cannot reach https://witan\.example: no route to host"):
        client(refuse).dispute_status("d-1")


def test_the_cli_prints_errors_not_tracebacks(capsys: pytest.CaptureFixture[str]) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    assert main(["search", "redis"], client=client(refuse)) == 1
    assert "error: cannot reach https://witan.example" in capsys.readouterr().err

    def interrupted(request: httpx.Request) -> httpx.Response:
        raise KeyboardInterrupt

    assert main(["search", "redis"], client=client(interrupted)) == 130
    assert capsys.readouterr().err.strip() == "interrupted"


def test_wtn_version(capsys: pytest.CaptureFixture[str]) -> None:
    from witan_sdk import __version__

    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"wtn (witan-sdk) {__version__}"
