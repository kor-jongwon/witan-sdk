"""Server deprecation notices become one WitanDeprecationWarning per route. No network."""

from __future__ import annotations

import warnings

import httpx
import pytest

from witan_sdk import Witan, WitanDeprecationWarning
from witan_sdk import deprecation


@pytest.fixture(autouse=True)
def fresh_seen():
    deprecation._seen.clear()
    yield
    deprecation._seen.clear()


def client(headers: dict[str, str]) -> Witan:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/leaderboard":
            return httpx.Response(200, json={"leaderboard": []}, headers=headers)
        return httpx.Response(200, json={"results": []})

    return Witan(base_url="http://witan.test", transport=httpx.MockTransport(handler))


def test_deprecated_route_warns_once_with_sunset_and_link():
    w = client({
        "deprecation": "@1790812800",
        "sunset": "Wed, 30 Jun 2027 00:00:00 GMT",
        "link": '<https://witan.example/docs/leaderboard>; rel="deprecation"; type="text/html"',
    })
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        w.leaderboard()
        w.leaderboard()
    hits = [c for c in caught if issubclass(c.category, WitanDeprecationWarning)]
    assert len(hits) == 1
    text = str(hits[0].message)
    assert "GET /leaderboard is deprecated since 2026-10-01" in text
    assert "stops working on 2027-06-30" in text
    assert "https://witan.example/docs/leaderboard" in text
    # The warning points at this test, not at httpx or the SDK.
    assert hits[0].filename == __file__


def test_warning_is_shown_by_default():
    assert issubclass(WitanDeprecationWarning, FutureWarning)


def test_routes_without_the_header_stay_quiet():
    w = client({})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        w.leaderboard()
        w.search("x")
    assert not [c for c in caught if issubclass(c.category, WitanDeprecationWarning)]


def test_deprecation_false_and_bare_true():
    w = client({"deprecation": "false"})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        w.leaderboard()
    assert not caught
    w = client({"deprecation": "true"})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        w.leaderboard()
    assert len(caught) == 1 and "GET /leaderboard is deprecated." in str(caught[0].message)


def test_can_be_made_an_error():
    w = client({"deprecation": "@1790812800"})
    with warnings.catch_warnings():
        warnings.simplefilter("error", WitanDeprecationWarning)
        with pytest.raises(WitanDeprecationWarning):
            w.leaderboard()
