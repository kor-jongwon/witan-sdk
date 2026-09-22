"""Unit tests against an httpx MockTransport shaped like the live API (captured
2026-09-21). No network."""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from witan_sdk import (
    AuthError,
    NotFoundError,
    PaymentRequiredError,
    RateLimitError,
    ValidationError,
    WaitTimeout,
    Witan,
    WitanError,
)

UNIT = "5e5fc8dd-af67-4f34-839b-b366ef05d43d"
PART_A = b"PAR1" + b"a" * 120 + b"PAR1"
PART_B = b"PAR1" + b"b" * 64 + b"PAR1"
SHA_A = hashlib.sha256(PART_A).hexdigest()
SHA_B = hashlib.sha256(PART_B).hexdigest()


def manifest_for(version: int) -> dict:
    parts = [
        {"sha256": SHA_A, "bytes": len(PART_A), "records": 2, "contributionId": "c-a", "agentId": "ag", "mergedInVersion": 109, "url": "http://parts.test/a"},
        {"sha256": SHA_B, "bytes": len(PART_B), "records": 1, "contributionId": "c-b", "agentId": "ag", "mergedInVersion": 110, "url": "http://parts.test/b"},
    ]
    if version == 111:  # server says SHA_B, store serves other bytes
        parts = [{**parts[1], "url": "http://parts.test/bad", "mergedInVersion": 111}]
    return {"format": "witan-dataset-manifest/1", "project": "agent-api-observatory", "version": version,
            "parent": version - 1, "createdAt": "2026-09-21T00:00:00Z",
            "schema": {"hash": "h", "fields": [{"name": "ok", "type": "boolean"}], "allowExtra": False},
            "parts": parts, "totals": {"records": sum(p["records"] for p in parts), "bytes": sum(p["bytes"] for p in parts),
                                       "parts": len(parts), "contributions": version},
            "urlExpiresAt": "2026-09-21T00:15:00Z"}
SEARCH_HIT = {"id": UNIT, "title": "Redis 7.4 SET/GET/INCR", "category": "infra-measurement",
              "preview": "…", "score": "68", "agentName": "witan-lab", "createdAt": "2026-08-21T07:58:37.580Z"}


class Fake:
    """Records requests and answers with canned, API-shaped bodies."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.status_sequence = ["screening", "validating", "published"]
        self.put_bodies: dict[int, list[bytes]] = {}
        self.upload_inits: list[dict] = []
        self.completions: list[list] = []
        self.fail_part2_once = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path, q = request.url.path, dict(request.url.params)
        auth = request.headers.get("authorization", "")

        def need_key() -> httpx.Response | None:
            if not auth.startswith("Bearer km_"):
                return httpx.Response(401, json={"error": "missing or malformed API key"})
            return None

        # presigned object store: the signature is in the URL, an Authorization header is a hard error
        if request.url.host == "parts.test":
            if "authorization" in request.headers:
                return httpx.Response(400, text="InvalidArgument: Only one auth mechanism allowed")
            if request.method == "PUT" and path.startswith("/up/"):
                n = int(path.rsplit("/", 1)[1])
                self.put_bodies.setdefault(n, []).append(request.content)
                if n == 2 and self.fail_part2_once:
                    self.fail_part2_once = False
                    return httpx.Response(500, text="flaky store")
                return httpx.Response(200, headers={"ETag": f'"etag-{n}"'})
            body = {"/a": PART_A, "/b": PART_B, "/bad": PART_A}.get(path)
            return httpx.Response(200, content=body) if body else httpx.Response(404)
        if path == "/projects/agent-api-observatory/uploads" and request.method == "POST":
            if need_key():
                return need_key()
            body = json.loads(request.content)
            self.upload_inits.append(body)
            return httpx.Response(201, json={"uploadId": "u-1", "key": "staging/u-1/records.jsonl", "partSize": 4,
                                             "parts": [{"n": i + 1, "url": f"http://parts.test/up/{i + 1}"} for i in range(body["parts"])],
                                             "expiresAt": "2099-01-01T00:00:00Z"})
        if path == "/projects/agent-api-observatory/uploads/u-1/complete":
            if need_key():
                return need_key()
            body = json.loads(request.content)
            self.completions.append(body["etags"])
            expected = self.upload_inits[-1]["parts"]
            if len(body["etags"]) != expected:
                return httpx.Response(400, json={"error": f"expected etags for parts 1..{expected}"})
            return httpx.Response(201, json={"contributionId": "c-9", "uploadId": "u-1", "status": "submitted", "bytes": 10})
        if path == "/projects/agent-api-observatory/contributions/c-9":
            return need_key() or httpx.Response(200, json={"id": "c-9", "status": "merged", "recordCount": 3,
                                                            "acceptedCount": 3, "mergedVersion": 111})

        if path == "/search":
            if q.get("q") == "nothing":
                return httpx.Response(200, json={"results": [], "mode": "keyword"})
            hit = dict(SEARCH_HIT)
            if q.get("mode") == "semantic":
                hit["similarity"] = "0.91"
            return httpx.Response(200, json={"results": [hit], "mode": q.get("mode", "keyword")})
        if path == f"/knowledge/{UNIT}/full":
            return need_key() or httpx.Response(200, json={**SEARCH_HIT, "body": "full text", "license": "platform-standard",
                                                            "sourceDeclaration": "lab", "royaltyAwarded": True})
        if path.startswith("/knowledge/") and path.endswith("/full"):
            return need_key() or httpx.Response(404, json={"error": "published knowledge unit not found"})
        if path == "/knowledge" and request.method == "POST":
            body = json.loads(request.content)
            if "body" not in body:
                return httpx.Response(400, json={"statusCode": 400, "code": "FST_ERR_VALIDATION",
                                                 "error": "Bad Request", "message": "body must have required property 'body'"})
            return httpx.Response(201, json={"id": "new-1", "title": body["title"], "category": body["category"],
                                             "status": "screening", "createdAt": "2026-09-21T00:00:00Z"})
        if path == "/knowledge/new-1":
            st = self.status_sequence.pop(0) if len(self.status_sequence) > 1 else self.status_sequence[0]
            return httpx.Response(200, json={"id": "new-1", "title": "t", "status": st, "validations": []})
        if path == "/knowledge/stuck-1":
            return httpx.Response(200, json={"id": "stuck-1", "title": "t", "status": "screening", "validations": []})
        if path == f"/knowledge/{UNIT}/review":
            return need_key() or httpx.Response(200, json={"ok": True, "updated": False})
        if path == f"/knowledge/{UNIT}/reviews":
            return httpx.Response(200, json={"count": 0, "average": 0, "reviews": []})
        if path == "/points":
            if auth == "Bearer km_limited":
                return httpx.Response(429, json={"error": "rate limit exceeded"})
            return need_key() or httpx.Response(200, json={"agentId": "a", "agentName": "probe", "balance": 12, "entries": 3})
        if path == "/quota":
            return need_key() or httpx.Response(200, json={"storage": {"usedBytes": 1234, "limitBytes": 5368709120},
                                                            "egress": {"usedBytes": 10, "limitBytes": 50000000000, "periodStart": "2026-09-01"}})
        if path == "/leaderboard":
            return httpx.Response(200, json={"leaderboard": [{"agentName": "witan-lab", "operatorName": "WITAN Lab", "points": 640, "published": 10}]})
        if path == "/projects":
            return httpx.Response(200, json={"projects": [{"slug": "agent-api-observatory", "title": "Agent API observatory",
                                                            "status": "open", "access": "public", "latestVersion": 110,
                                                            "records": 1278, "stars": 0, "contributions": 110, "license": "platform-standard",
                                                            "createdAt": "2026-08-24T07:53:57.097Z"}]})
        if path in ("/projects/agent-api-observatory/data", "/projects/legacy/data"):
            if need_key():
                return need_key()
            recs = [{"ok": True, "latency_ms": 18.2}] if int(q.get("offset", 0)) == 0 else []
            return httpx.Response(200, json={"project": path.split("/")[2], "version": int(q.get("version", 110)),
                                             "count": len(recs), "records": recs})
        if path == "/projects/agent-api-observatory/manifest":
            return need_key() or httpx.Response(200, json=manifest_for(int(q.get("version", 110))))
        if path == "/projects/legacy/manifest":
            return need_key() or httpx.Response(409, json={"error": "this version has not been materialized as parts yet"})
        if path == "/projects/paid-one/data":
            return need_key() or httpx.Response(402, json={"error": "payment required", "to": "http://pay/paid/dataset?slug=paid-one"})
        if path == "/projects/agent-api-observatory/diff":
            assert q["from"] == "100" and q["to"] == "110"
            return httpx.Response(200, json={"project": "agent-api-observatory", "from": 100, "to": 110,
                                             "addedContributions": 10, "addedRecords": 100, "fragments": [], "records": []})
        if path == "/projects/agent-api-observatory/contribute":
            body = json.loads(request.content)
            assert isinstance(body["records"], list)
            return need_key() or httpx.Response(201, json={"id": "c-1", "status": "submitted"})
        if path == "/projects/agent-api-observatory/contributions/c-1":
            return need_key() or httpx.Response(200, json={"id": "c-1", "status": "merged", "recordCount": 2,
                                                            "acceptedCount": 2, "mergedVersion": 111})
        if path == "/community/topics":
            return need_key() or httpx.Response(201, json={"id": "t-1", "createdAt": "2026-09-21T00:00:00Z"})
        if path == "/community/t/t-1/comments" and request.method == "POST":
            return need_key() or httpx.Response(201, json={"id": "40", "createdAt": "2026-09-21T00:00:00Z"})
        return httpx.Response(404, json={"error": f"unmapped {request.method} {path}"})


@pytest.fixture
def fake() -> Fake:
    return Fake()


@pytest.fixture
def w(fake: Fake) -> Witan:
    return Witan("km_test", base_url="http://api.test", transport=httpx.MockTransport(fake))


@pytest.fixture
def anon(fake: Fake, monkeypatch: pytest.MonkeyPatch) -> Witan:
    monkeypatch.delenv("WITAN_API_KEY", raising=False)
    return Witan(base_url="http://api.test", transport=httpx.MockTransport(fake))


def test_search_keyword_and_semantic(w: Witan, fake: Fake) -> None:
    hits = w.search("redis", category="infra-measurement", limit=5)
    assert hits[0]["id"] == UNIT and "similarity" not in hits[0]
    assert dict(fake.calls[-1].url.params) == {"q": "redis", "category": "infra-measurement", "limit": "5"}
    hits = w.search("redis", mode="semantic")
    assert hits[0]["similarity"] == "0.91"
    assert fake.calls[-1].url.params["mode"] == "semantic"
    assert w.search("nothing") == []


def test_user_agent_and_auth_header(w: Witan, fake: Fake) -> None:
    w.search("redis")
    req = fake.calls[-1]
    assert req.headers["authorization"] == "Bearer km_test"
    assert req.headers["user-agent"].startswith("witan-sdk/")


def test_read_full_and_errors(w: Witan, anon: Witan) -> None:
    full = w.read(UNIT)
    assert full["body"] == "full text" and full["royaltyAwarded"] is True
    with pytest.raises(NotFoundError) as ei:
        w.read("00000000-0000-0000-0000-000000000000")
    assert ei.value.status == 404 and "not found" in str(ei.value)
    with pytest.raises(AuthError):
        anon.read(UNIT)  # no key at all: fails locally before any request


def test_submit_wait_and_validation_error(w: Witan) -> None:
    unit = w.submit("t", "b", "infra-measurement", source_declaration="lab")
    assert unit["status"] == "screening"
    done = w.wait("new-1", timeout=10, interval=0)
    assert done["status"] == "published"
    with pytest.raises(WaitTimeout):
        w.wait("stuck-1", timeout=0, interval=0)
    with pytest.raises(ValidationError) as ei:
        w._request("POST", "/knowledge", json={"title": "x"}, auth=True)
    assert ei.value.code == "FST_ERR_VALIDATION" and "required property" in ei.value.message


def test_review_points_leaderboard_rate_limit(w: Witan, fake: Fake) -> None:
    assert w.review(UNIT, 5, "solid") == {"ok": True, "updated": False}
    assert w.points()["balance"] == 12
    assert w.quota()["storage"]["limitBytes"] == 5 * 1024 ** 3
    assert w.leaderboard()[0]["agentName"] == "witan-lab"
    limited = Witan("km_limited", base_url="http://api.test", transport=httpx.MockTransport(fake))
    with pytest.raises(RateLimitError):
        limited.points()


def test_projects(w: Witan) -> None:
    assert w.projects.list()[0]["slug"] == "agent-api-observatory"
    page = w.projects.data("agent-api-observatory", version=105, limit=1)
    assert page["version"] == 105 and page["records"][0]["ok"] is True
    diff = w.projects.diff("agent-api-observatory", from_version=100, to_version=110)
    assert diff["addedRecords"] == 100
    c = w.projects.contribute("agent-api-observatory", [{"a": 1}, {"a": 2}], source_declaration="probe")
    assert c["status"] == "submitted"
    assert w.projects.wait_contribution("agent-api-observatory", "c-1", timeout=5, interval=0)["mergedVersion"] == 111
    with pytest.raises(PaymentRequiredError) as ei:
        w.projects.data("paid-one")
    assert ei.value.body["to"].startswith("http://pay/")


def test_pull_jsonl_writes_snapshot_and_caches(w: Witan, fake: Fake, tmp_path) -> None:
    m = w.projects.pull("agent-api-observatory", tmp_path, format="jsonl", page=1)
    assert m["version"] == 110 and m["count"] == 1 and m["format"] == "jsonl"
    d = tmp_path / "agent-api-observatory" / "v110"
    assert (d / "records.jsonl").read_text(encoding="utf-8").strip() == json.dumps({"ok": True, "latency_ms": 18.2})
    assert json.loads((d / "manifest.json").read_text(encoding="utf-8"))["count"] == 1
    n = len(fake.calls)
    again = w.projects.pull("agent-api-observatory", tmp_path, version=110, format="jsonl", page=1)
    assert again["count"] == 1 and len(fake.calls) == n + 1  # one probe call, no re-download


def test_pull_parquet_parts_verified_and_incremental(w: Witan, fake: Fake, tmp_path) -> None:
    m = w.projects.pull("agent-api-observatory", tmp_path)
    assert m["format"] == "parquet" and m["version"] == 110 and m["downloaded"] == 2 and m["count"] == 3
    parts = tmp_path / "agent-api-observatory" / "parts"
    assert (parts / f"{SHA_A}.parquet").read_bytes() == PART_A and (parts / f"{SHA_B}.parquet").read_bytes() == PART_B
    saved = json.loads((tmp_path / "agent-api-observatory" / "v110" / "manifest.json").read_text(encoding="utf-8"))
    assert "urlExpiresAt" not in saved and all("url" not in p for p in saved["parts"])
    downloads = [c for c in fake.calls if c.url.host == "parts.test"]
    assert len(downloads) == 2 and all("authorization" not in c.headers for c in downloads)
    n = len(fake.calls)
    pinned = w.projects.pull("agent-api-observatory", tmp_path, version=110)
    assert pinned["version"] == 110 and len(fake.calls) == n  # pinned + complete on disk: no network
    latest = w.projects.pull("agent-api-observatory", tmp_path)
    assert latest["downloaded"] == 0 and len(fake.calls) == n + 1  # one manifest probe, no part transfers


def test_pull_rejects_corrupt_part(w: Witan, tmp_path) -> None:
    with pytest.raises(WitanError, match="sha256"):
        w.projects.pull("agent-api-observatory", tmp_path, version=111)
    parts = tmp_path / "agent-api-observatory" / "parts"
    assert not list(parts.glob("*.part")) and not (parts / f"{SHA_B}.parquet").exists()


def test_push_splits_uploads_in_parallel_and_completes(w: Witan, fake: Fake, tmp_path, monkeypatch) -> None:
    import witan_sdk.client as mod
    monkeypatch.setattr(mod, "MIN_PART_SIZE", 4)
    f = tmp_path / "records.jsonl"
    f.write_bytes(b"0123456789")  # 10 bytes → parts of 4: 4, 4, 2
    r = w.projects.push("agent-api-observatory", f, compress=False, part_size=4, wait=True, source_declaration="probe")
    assert fake.upload_inits[-1] == {"bytes": 10, "parts": 3, "sourceDeclaration": "probe", "compression": "none"}
    assert [fake.put_bodies[n][0] for n in (1, 2, 3)] == [b"0123", b"4567", b"89"]
    assert fake.completions[-1] == [{"n": 1, "etag": "etag-1"}, {"n": 2, "etag": "etag-2"}, {"n": 3, "etag": "etag-3"}]
    assert r["contributionId"] == "c-9" and r["parts"] == 3 and r["uploadedParts"] == 3 and r["status"] == "merged"
    puts = [c for c in fake.calls if c.method == "PUT"]
    assert len(puts) == 3 and all("authorization" not in c.headers for c in puts)
    assert not (tmp_path / "records.jsonl.witan-upload.json").exists()


def test_push_resumes_after_a_failed_part(w: Witan, fake: Fake, tmp_path, monkeypatch) -> None:
    import witan_sdk.client as mod
    monkeypatch.setattr(mod, "MIN_PART_SIZE", 4)
    f = tmp_path / "records.jsonl"
    f.write_bytes(b"0123456789")
    fake.fail_part2_once = True
    with pytest.raises(WitanError, match="HTTP 500"):
        w.projects.push("agent-api-observatory", f, compress=False, part_size=4, workers=1)
    state = json.loads((tmp_path / "records.jsonl.witan-upload.json").read_text(encoding="utf-8"))
    assert state["etags"] == {"1": "etag-1"} and state["uploadId"] == "u-1"
    inits = len(fake.upload_inits)
    r = w.projects.push("agent-api-observatory", f, compress=False, part_size=4, workers=1)
    assert len(fake.upload_inits) == inits  # resumed: no new upload started
    assert r["uploadedParts"] == 2 and fake.completions[-1][0]["etag"] == "etag-1"


def test_push_gzips_by_default(w: Witan, fake: Fake, tmp_path) -> None:
    f = tmp_path / "records.jsonl"
    f.write_text('{"ok": true}\n' * 50, encoding="utf-8")
    r = w.projects.push("agent-api-observatory", f)
    assert fake.upload_inits[-1]["compression"] == "gzip" and fake.upload_inits[-1]["parts"] == 1
    assert fake.put_bodies[1][0][:2] == b"\x1f\x8b" and r["parts"] == 1
    assert not (tmp_path / "records.jsonl.witan-upload.gz").exists()


def test_pull_falls_back_to_jsonl_when_not_materialized(w: Witan, tmp_path) -> None:
    m = w.projects.pull("legacy", tmp_path)
    assert m["format"] == "jsonl" and (tmp_path / "legacy" / "v110" / "records.jsonl").exists()


def test_community(w: Witan) -> None:
    t = w.community.topic("Payload sweep beyond 8KB?", "anyone?", category="q-and-a")
    assert t["id"] == "t-1"
    assert w.community.reply("t-1", "not yet")["id"] == "40"


def test_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WITAN_API_KEY", "km_env")
    monkeypatch.setenv("WITAN_BASE_URL", "https://witan.example/")
    c = Witan()
    assert c.api_key == "km_env" and c.base_url == "https://witan.example"


def test_buy_without_extra_or_key(w: Witan, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WITAN_WALLET_KEY", raising=False)
    with pytest.raises(PaymentRequiredError):
        w.buy(UNIT)


def test_pull_paid_materializes_the_bought_manifest(w: Witan, fake: Fake, tmp_path, monkeypatch) -> None:
    bought: list[tuple[str, int | None]] = []

    def fake_buy(slug: str, *, version: int | None = None, private_key: str | None = None) -> dict:
        bought.append((slug, version))
        return {**manifest_for(110), "project": "paid-one", "paid": True}

    monkeypatch.setattr(w, "buy_dataset", fake_buy)
    m = w.projects.pull_paid("paid-one", tmp_path, version=110, private_key="0xkey")
    assert bought == [("paid-one", 110)] and m["format"] == "parquet" and m["downloaded"] == 2 and m["count"] == 3
    assert "paid" not in m and "urlExpiresAt" not in m and all("url" not in p for p in m["parts"])
    parts = tmp_path / "paid-one" / "parts"
    assert (parts / f"{SHA_A}.parquet").read_bytes() == PART_A and (parts / f"{SHA_B}.parquet").read_bytes() == PART_B
    n = len(fake.calls)
    again = w.projects.pull_paid("paid-one", tmp_path, version=110, private_key="0xkey")
    assert again["version"] == 110 and bought == [("paid-one", 110)] and len(fake.calls) == n  # complete on disk: no second purchase
