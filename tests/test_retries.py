"""Automatic retries: which requests, which failures, how long to wait. No network."""

from __future__ import annotations

import hashlib

import httpx
import pytest

from witan_sdk import RateLimitError, ServerError, Witan, WitanError

BASE = "http://witan.test"


def client(handler, **kw) -> tuple[Witan, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request, len(seen))

    return Witan("km_test", base_url=BASE, transport=httpx.MockTransport(record), **kw), seen


def flaky(*statuses: int, final: dict | None = None):
    """Answer with each status in turn, then 200."""
    def handler(request: httpx.Request, n: int) -> httpx.Response:
        if n <= len(statuses):
            return httpx.Response(statuses[n - 1], json={"error": "busy"})
        return httpx.Response(200, json=final if final is not None else {"projects": []})
    return handler


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_read_retries_transient_statuses(status, no_retry_sleep):
    w, seen = client(flaky(status, status))
    assert w.projects.list() == []
    assert len(seen) == 3
    assert no_retry_sleep == [0.3, 0.6]


def test_read_gives_up_after_retries():
    w, seen = client(flaky(503, 503, 503, 503))
    with pytest.raises(ServerError):
        w.projects.list()
    assert len(seen) == 3  # 1 + retries (2)


def test_retries_zero_is_one_attempt():
    w, seen = client(flaky(503), retries=0)
    with pytest.raises(ServerError):
        w.projects.list()
    assert len(seen) == 1


def test_other_errors_are_not_retried():
    w, seen = client(flaky(500, 404))
    with pytest.raises(WitanError):
        w.projects.list()
    assert len(seen) == 1


def test_write_without_idempotency_key_is_not_retried():
    w, seen = client(flaky(503, final={"id": "c1", "status": "submitted"}))
    with pytest.raises(ServerError):
        w.submit(title="t", body="b", category="infra-measurement")
    assert len(seen) == 1


def test_contribute_with_idempotency_key_is_retried():
    w, seen = client(flaky(502, final={"id": "c1", "status": "merged"}))
    r = w.projects.contribute("p", [{"k": 1}], idempotency_key="run-1")
    assert r["status"] == "merged"
    assert len(seen) == 2
    assert all(req.headers["idempotency-key"] == "run-1" for req in seen)


def test_contribute_without_key_is_not_retried():
    w, seen = client(flaky(502, final={"id": "c1", "status": "merged"}))
    with pytest.raises(ServerError):
        w.projects.contribute("p", [{"k": 1}])
    assert len(seen) == 1


def test_server_sql_is_retried():
    w, seen = client(flaky(503, final={"columns": ["n"], "rows": [[1]]}))
    assert w.projects.query_remote("p", "SELECT 1")["rows"] == [[1]]
    assert seen[0].method == "POST" and len(seen) == 2


def test_retry_after_seconds_is_honoured(no_retry_sleep):
    def handler(request, n):
        if n == 1:
            return httpx.Response(429, headers={"retry-after": "2"}, json={"error": "slow down"})
        return httpx.Response(200, json={"projects": []})
    w, seen = client(handler)
    w.projects.list()
    assert no_retry_sleep == [2.0] and len(seen) == 2


def test_retry_after_too_long_fails_now(no_retry_sleep):
    def handler(request, n):
        return httpx.Response(429, headers={"retry-after": "3600"}, json={"error": "slow down"})
    w, seen = client(handler)
    with pytest.raises(RateLimitError):
        w.projects.list()
    assert len(seen) == 1 and no_retry_sleep == []


def test_network_error_on_a_read_is_retried():
    def handler(request, n):
        if n == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json={"projects": []})
    w, seen = client(handler)
    assert w.projects.list() == []
    assert len(seen) == 2


def test_network_error_on_a_plain_write_is_not_retried():
    def handler(request, n):
        raise httpx.ConnectError("connection refused", request=request)
    w, seen = client(handler)
    with pytest.raises(WitanError, match="cannot reach"):
        w.submit(title="t", body="b", category="infra-measurement")
    assert len(seen) == 1


def test_timeouts_exhaust_into_a_named_error():
    def handler(request, n):
        raise httpx.ReadTimeout("slow", request=request)
    w, seen = client(handler)
    with pytest.raises(WitanError, match="did not answer"):
        w.projects.list()
    assert len(seen) == 3


def test_part_upload_retries_500():
    def handler(request, n):
        if n == 1:
            return httpx.Response(500)
        return httpx.Response(200, headers={"etag": '"abc"'})
    w, seen = client(handler)
    assert w._upload_part("http://store.test/bucket/part?X-Amz-Signature=s", b"data") == "abc"
    assert len(seen) == 2 and "authorization" not in seen[1].headers


def test_part_download_restarts_after_a_dropped_connection(tmp_path):
    body = b"PAR1" + b"x" * 40 + b"PAR1"
    sha = hashlib.sha256(body).hexdigest()

    def handler(request, n):
        if n == 1:
            raise httpx.RemoteProtocolError("peer closed connection", request=request)
        return httpx.Response(200, content=body)
    w, seen = client(handler)
    w._download_part({"sha256": sha, "bytes": len(body), "url": "http://store.test/p"}, tmp_path)
    assert (tmp_path / f"{sha}.parquet").read_bytes() == body and len(seen) == 2


def test_part_with_a_wrong_hash_is_not_retried(tmp_path):
    body = b"PAR1" + b"x" * 40 + b"PAR1"

    def handler(request, n):
        return httpx.Response(200, content=body)
    w, seen = client(handler)
    with pytest.raises(WitanError, match="sha256"):
        w._download_part({"sha256": "0" * 64, "bytes": len(body), "url": "http://store.test/p"}, tmp_path)
    assert len(seen) == 1
