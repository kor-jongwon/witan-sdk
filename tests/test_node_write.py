"""Writes on a node: local projects, the gates, versions, idempotency, restarts, MCP, promote."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from witan_sdk import Witan, WitanError

duckdb = pytest.importorskip("duckdb")

from witan_sdk.node import Server  # noqa: E402
from witan_sdk.node_write import record_hash, stable_stringify, stored_form  # noqa: E402

SLUG = "fn-state"
SCHEMA = {"fields": [{"name": "key", "type": "string"}, {"name": "n", "type": "integer"},
                     {"name": "v", "type": "number"}, {"name": "ok", "type": "boolean", "required": False}],
          "allowExtra": True}
README = "State a function writes at the end of a run and reads at the start of the next."


@pytest.fixture
def node(tmp_path: Path):
    srv = Server(tmp_path / "store", port=0, quiet=True).start()
    yield srv
    srv.close()


@pytest.fixture
def w(node) -> Witan:
    w = Witan("any-key", base_url=node.url)
    w.projects.create(SLUG, "Function state", README, SCHEMA)
    return w


def test_stable_stringify_matches_the_origin() -> None:
    # JavaScript's JSON.stringify for numbers, keys sorted recursively
    assert stable_stringify({"b": 1.0, "a": [0.00001, 1.5, True, None], "c": {"z": "é", "y": 1e21}}) == \
        '{"a":[0.00001,1.5,true,null],"b":1,"c":{"y":1e+21,"z":"é"}}'
    # the stored form hashes the same whether a number arrived as 2 or 2.0, and a null field is not a field
    a = stored_form({"key": "x", "n": 2.0, "v": 2, "ok": None, "note": "k"}, SCHEMA)
    b = stored_form({"key": "x", "n": 2, "v": 2.0, "note": "k"}, SCHEMA)
    assert a == b and record_hash(a) == record_hash(b)


def test_create_list_and_an_empty_project(node, w: Witan) -> None:
    [p] = w.projects.list()
    assert p["slug"] == SLUG and p["local"] is True and p["latestVersion"] == 0 and p["visibility"] == "private"
    d = w.projects.get(SLUG)
    assert d["schemaDef"] == SCHEMA and d["versions"] == [] and d["latestVersion"] == 0
    with pytest.raises(WitanError) as ei:
        w.projects.data(SLUG)
    assert ei.value.status == 404 and "no published version yet" in str(ei.value)
    assert httpx.get(f"{node.url}/healthz").json()["localProjects"] == [SLUG]


def test_create_is_validated(w: Witan) -> None:
    cases = [
        (dict(slug="Bad Slug"), 400), (dict(slug=SLUG), 409), (dict(access="paid"), 400),
        (dict(schema_def={"fields": []}), 400), (dict(schema_def={"fields": [{"name": "1x", "type": "string"}]}), 400),
        (dict(title="no"), 400),
    ]
    for override, status in cases:
        args = {"slug": "other-proj", "title": "Other project", "readme": README, "schema_def": SCHEMA, **override}
        with pytest.raises(WitanError) as ei:
            w.projects.create(args.pop("slug"), args.pop("title"), args.pop("readme"), args.pop("schema_def"), **args)
        assert ei.value.status == status, override


def test_contribute_merges_in_the_call_and_versions_stay_immutable(w: Witan) -> None:
    r1 = w.projects.contribute(SLUG, [{"key": "cursor", "n": 41, "v": 1.5, "ok": True},
                                      {"key": "retries", "n": 2, "v": 0.25, "note": "slow", "tries": 3},
                                      {"key": "empty", "n": 0, "v": 2, "ok": None}], source_declaration="run 1")
    assert r1["status"] == "merged" and r1["mergedVersion"] == 1 and r1["acceptedCount"] == 3
    assert r1["verdict"] == {"ok": True, "droppedDuplicates": 0, "parts": 1}
    # one duplicate (arrives as 2.0 / no ok field — the same stored record), two new
    r2 = w.projects.contribute(SLUG, [{"key": "empty", "n": 0.0, "v": 2.0},
                                      {"key": "later", "n": 7, "v": 3.75, "ok": False, "region": "ap-northeast-2"},
                                      {"key": "last", "n": -5, "v": -1.125}])
    assert r2["status"] == "merged" and r2["mergedVersion"] == 2 and r2["acceptedCount"] == 2
    assert r2["verdict"]["droppedDuplicates"] == 1
    page = w.projects.data(SLUG)
    assert page["version"] == 2 and page["count"] == 5
    assert page["records"][0] == {"key": "cursor", "n": 41, "v": 1.5, "ok": True}
    assert page["records"][1] == {"key": "retries", "n": 2, "v": 0.25, "note": "slow", "tries": 3}
    assert page["records"][2] == {"key": "empty", "n": 0, "v": 2}
    assert w.projects.data(SLUG, version=1)["count"] == 3  # the old version still reads as it was
    m2 = w.projects.manifest(SLUG)
    assert len(m2["parts"]) == 1 and len(m2["parts"][0]["sources"]) == 2  # the small tail folded into one part
    m1 = w.projects.manifest(SLUG, version=1)
    assert m1["parts"][0]["sha256"] != m2["parts"][0]["sha256"]
    assert w.projects.query_remote(SLUG, "SELECT sum(n) FROM records")["rows"] == [[45]]
    assert w.projects.contribution(SLUG, r2["id"])["mergedVersion"] == 2


def test_the_gates_reject_with_the_origin_s_reasons(w: Witan) -> None:
    w.projects.contribute(SLUG, [{"key": "a", "n": 1, "v": 1}])
    cases = [
        ([{"key": "b", "n": 1.5, "v": 1}], "schema", 'line 1: "n" must be integer'),
        ([{"key": "c", "n": 1, "v": 1}, {"key": "d", "v": 1}], "schema", 'line 2: missing required field "n"'),
        ([{"key": "e", "n": 1, "v": True}], "schema", '"v" must be number'),
        ([{"key": "900101-1234567", "n": 1, "v": 1}], "pii", "resident registration number pattern detected"),
        ([{"key": "a", "n": 1, "v": 1.0}], "dedup", "every record already exists in the dataset"),
    ]
    for records, gate, reason in cases:
        r = w.projects.contribute(SLUG, records)
        assert r["status"] == "rejected" and r["verdict"]["gate"] == gate and reason in r["verdict"]["reason"], r
    assert w.projects.get(SLUG)["latestVersion"] == 1  # nothing rejected made a version


def test_idempotency_key_replays_and_guards(node, w: Witan) -> None:
    body = {"records": [{"key": "k", "n": 1, "v": 1}], "sourceDeclaration": "run 9"}
    first = httpx.post(f"{node.url}/projects/{SLUG}/contribute", json=body, headers={"idempotency-key": "run-9"})
    again = httpx.post(f"{node.url}/projects/{SLUG}/contribute", json=body, headers={"idempotency-key": "run-9"})
    assert first.status_code == 201 and again.status_code == 200 and again.headers["idempotent-replayed"] == "true"
    assert again.json()["id"] == first.json()["id"] and again.json()["status"] == "merged"
    other = httpx.post(f"{node.url}/projects/{SLUG}/contribute", json={"records": [{"key": "z", "n": 2, "v": 2}]},
                       headers={"idempotency-key": "run-9"})
    assert other.status_code == 422
    assert httpx.post(f"{node.url}/projects/{SLUG}/contribute", json=body, headers={"idempotency-key": "x" * 201}).status_code == 400
    via_sdk = w.projects.contribute(SLUG, [{"key": "s", "n": 3, "v": 3}], idempotency_key="sdk-1", wait=5)
    assert w.projects.contribute(SLUG, [{"key": "s", "n": 3, "v": 3}], idempotency_key="sdk-1")["id"] == via_sdk["id"]
    assert w.projects.get(SLUG)["latestVersion"] == 2


def test_dedup_survives_a_restart(tmp_path: Path) -> None:
    store = tmp_path / "store"
    srv = Server(store, port=0, quiet=True).start()
    w = Witan("k", base_url=srv.url)
    w.projects.create(SLUG, "Function state", README, SCHEMA)
    w.projects.contribute(SLUG, [{"key": "a", "n": 1, "v": 2, "ok": None, "extra": {"deep": [1, 2.0]}}])
    srv.close()
    srv = Server(store, port=0, quiet=True).start()
    try:
        w = Witan("k", base_url=srv.url)
        again = w.projects.contribute(SLUG, [{"key": "a", "n": 1.0, "v": 2.0, "extra": {"deep": [1, 2]}}])
        assert again["status"] == "rejected" and again["verdict"]["gate"] == "dedup"  # the set rebuilt from the parts agrees
        assert w.projects.contribute(SLUG, [{"key": "b", "n": 1, "v": 2}])["mergedVersion"] == 2
    finally:
        srv.close()


def test_copies_uploads_read_only_and_unknown_projects(tmp_path: Path) -> None:
    store = tmp_path / "store"
    copy = store / "origin-copy" / "v1"
    copy.mkdir(parents=True)
    (store / "origin-copy" / "parts").mkdir()
    (copy / "manifest.json").write_text(json.dumps({"format": "parquet", "project": "origin-copy", "version": 1, "parts": [],
                                                    "totals": {"records": 0, "bytes": 0, "parts": 0, "contributions": 1}}))
    srv = Server(store, port=0, quiet=True).start()
    try:
        post = lambda path, body: httpx.post(f"{srv.url}{path}", json=body)  # noqa: E731
        r = post("/projects/origin-copy/contribute", {"records": [{"key": "x"}]})
        assert r.status_code == 405 and "copy of an origin project" in r.json()["error"]
        assert post("/projects/nope-nope/contribute", {"records": [{"key": "x"}]}).status_code == 404
        assert post("/projects/origin-copy/uploads", {"bytes": 1, "parts": 1}).status_code == 405
    finally:
        srv.close()
    ro = Server(store, port=0, quiet=True, read_only=True).start()
    try:
        r = httpx.post(f"{ro.url}/projects", json={"slug": "new-one", "title": "New one", "readme": README, "schemaDef": SCHEMA})
        assert r.status_code == 405 and "read-only" in r.json()["error"]
        tools = httpx.post(f"{ro.url}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()["result"]["tools"]
        assert "contribute_records" not in [t["name"] for t in tools]
        assert httpx.get(f"{ro.url}/healthz").json()["readOnly"] is True
    finally:
        ro.close()
    with pytest.raises(WitanError, match="local project"):
        (store / "mine").mkdir()
        (store / "mine" / "project.json").write_text(json.dumps({"slug": "mine", "local": True, "schemaDef": SCHEMA}))
        Server(store, port=0, follow=["mine"], origin=object())


def test_mcp_contribute_records(node, w: Witan) -> None:
    call = httpx.post(f"{node.url}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "contribute_records",
        "arguments": {"slug": SLUG, "records": [{"key": "m", "n": 1, "v": 1}], "idempotencyKey": "mcp-1"}}}).json()
    view = json.loads(call["result"]["content"][0]["text"])
    assert view["status"] == "merged" and view["mergedVersion"] == 1 and view["replayed"] is False
    status = httpx.post(f"{node.url}/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "contribution_status", "arguments": {"slug": SLUG, "id": view["id"]}}}).json()
    assert json.loads(status["result"]["content"][0]["text"])["acceptedCount"] == 1


def test_promote_bundles_offline_and_pushes_to_the_origin(node, w: Witan, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w.projects.contribute(SLUG, [{"key": "a", "n": 1, "v": 1}, {"key": "b", "n": 2, "v": 2, "note": "x"}])
    store = Path(node.node.store.root)
    origin = Witan("km_test", base_url="http://origin.invalid")  # no request may reach it except the push
    pushed: list[tuple[str, list[dict], str]] = []

    def fake_push(slug, path, *, source_declaration=None, workers=4, wait=False, timeout=900.0):
        lines = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
        pushed.append((slug, lines, source_declaration))
        return {"contributionId": "c-1", "status": "merged", "mergedVersion": 4, "acceptedCount": len(lines)}

    monkeypatch.setattr(origin.projects, "push", fake_push)
    r = origin.projects.promote(SLUG, to="fn-state-origin", store=store)
    assert r["status"] == "merged" and r["promoted"] == {"from": SLUG, "version": 1, "to": "fn-state-origin", "records": 2}
    slug, lines, declaration = pushed[0]
    assert slug == "fn-state-origin" and lines == [{"key": "a", "n": 1, "v": 1.0}, {"key": "b", "n": 2, "v": 2.0, "note": "x"}]
    assert "Promoted from a WITAN node" in declaration
    assert json.loads((store / SLUG / "project.json").read_text())["local"] is True  # the node project stays local
    assert w.projects.contribute(SLUG, [{"key": "c", "n": 3, "v": 3}])["mergedVersion"] == 2
    with pytest.raises(WitanError, match="not a local project"):
        origin.projects.promote("nope-nope", store=store)
