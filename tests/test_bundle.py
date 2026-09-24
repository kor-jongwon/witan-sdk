"""Bundles (save / load / push_bundle) against the mock API. No network."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import httpx
import pytest

from witan_sdk import Witan, WitanError
from witan_sdk.bundle import BundleError, iter_records, write_bundle
from witan_sdk.cli import main

from test_client import PART_A, PART_B, SHA_A, SHA_B, Fake

SLUG = "agent-api-observatory"
PROJECT_DETAIL = {
    "id": "p-1", "slug": SLUG, "title": "Agent API observatory", "readme": "Real HTTPS round-trips to endpoints agents depend on.",
    "schemaDef": {"fields": [{"name": "ok", "type": "boolean"}], "allowExtra": False}, "license": "platform-standard",
    "status": "open", "access": "public", "visibility": "public", "createdAt": "2026-08-24T07:53:57.097Z",
    "maintainer": "WITAN Lab", "stars": 0, "latestVersion": 110, "contributors": [], "versions": [],
}


class ProjectFake(Fake):
    """The shared fake plus the project detail route bundles read their metadata from."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/projects/{SLUG}" and request.method == "GET":
            self.calls.append(request)
            return httpx.Response(200, json=PROJECT_DETAIL)
        return super().__call__(request)


@pytest.fixture
def fake() -> ProjectFake:
    return ProjectFake()


@pytest.fixture
def w(fake: ProjectFake) -> Witan:
    return Witan("km_test", base_url="http://api.test", transport=httpx.MockTransport(fake))


def offline_client() -> tuple[Witan, list[httpx.Request]]:
    calls: list[httpx.Request] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, json={"error": "offline"})

    return Witan("km_test", base_url="http://offline.test", transport=httpx.MockTransport(refuse)), calls


def members(path: Path) -> dict[str, bytes]:
    with tarfile.open(path) as t:
        return {m.name: t.extractfile(m).read() for m in t}  # type: ignore[union-attr]


def rewrite(src: Path, dst: Path, change, extra: list[tuple[str, bytes]] = ()) -> None:  # type: ignore[assignment]
    with tarfile.open(src) as t, tarfile.open(dst, "w", format=tarfile.PAX_FORMAT) as out:
        for m in t:
            data = t.extractfile(m).read()  # type: ignore[union-attr]
            res = change(m.name, data)
            if res is None:
                continue
            name, data = res
            info = tarfile.TarInfo(name)
            info.size = len(data)
            out.addfile(info, io.BytesIO(data))
        for name, data in extra:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            out.addfile(info, io.BytesIO(data))


@pytest.fixture
def bundle(w: Witan, tmp_path: Path) -> Path:
    path = tmp_path / "obs.witan"
    w.projects.save(SLUG, path, version=110, cache_dir=tmp_path / "cache")
    return path


def test_save_writes_header_project_manifest_and_parts(w: Witan, tmp_path: Path) -> None:
    r = w.projects.save(SLUG, tmp_path / "obs.witan", version=110, cache_dir=tmp_path / "cache")
    assert r["version"] == 110 and r["records"] == 3 and r["parts"] == 2 and r["bytes"] == len(PART_A) + len(PART_B)
    assert r["offline"] is False and r["format"] == "witan-bundle/1" and r["source"] == "http://api.test"
    with tarfile.open(tmp_path / "obs.witan") as t:
        names = [m.name for m in t]
    assert names == ["witan-bundle.json", "project.json", "manifest.json", f"parts/{SHA_A}.parquet", f"parts/{SHA_B}.parquet"]
    got = members(tmp_path / "obs.witan")
    manifest = json.loads(got["manifest.json"])
    assert manifest["format"] == "witan-dataset-manifest/1" and manifest["version"] == 110
    assert all("url" not in p for p in manifest["parts"]) and "pulledAt" not in manifest and "urlExpiresAt" not in manifest
    assert hashlib.sha256(got["manifest.json"]).hexdigest() == r["manifestSha256"]
    assert json.loads(got["project.json"])["schemaDef"]["fields"][0]["name"] == "ok"
    assert got[f"parts/{SHA_A}.parquet"] == PART_A
    assert (tmp_path / "cache" / SLUG / "project.json").is_file()  # kept for offline re-saves


def test_load_lays_out_like_pull_and_query_needs_no_network(bundle: Path, tmp_path: Path) -> None:
    off, calls = offline_client()
    store = tmp_path / "store"
    r = off.projects.load(bundle, store)
    assert r["written"] == 2 and r["out"] == str(store / SLUG) and r["records"] == 3
    parts = store / SLUG / "parts"
    assert (parts / f"{SHA_A}.parquet").read_bytes() == PART_A and (parts / f"{SHA_B}.parquet").read_bytes() == PART_B
    local = json.loads((store / SLUG / "v110" / "manifest.json").read_text())
    assert local["format"] == "parquet" and local["loadedFrom"] == "obs.witan" and local["source"] == "http://api.test"
    assert off.projects.pull(SLUG, store, version=110)["version"] == 110  # complete locally → answered from disk
    assert calls == []
    assert off.projects.load(bundle, store)["written"] == 0  # idempotent: parts already there


def test_check_verifies_and_writes_nothing(bundle: Path, tmp_path: Path) -> None:
    off, calls = offline_client()
    r = off.projects.load(bundle, tmp_path / "store", check=True)
    assert r["checked"] is True and r["out"] is None and not (tmp_path / "store").exists() and calls == []


def test_resave_offline_from_a_loaded_copy_keeps_the_manifest(bundle: Path, tmp_path: Path) -> None:
    off, calls = offline_client()
    store = tmp_path / "store"
    first = off.projects.load(bundle, store)
    again = off.projects.save(SLUG, tmp_path / "again.witan", version=110, cache_dir=store)
    assert again["offline"] is True and calls == []
    assert again["manifestSha256"] == first["manifestSha256"] and again["source"] == "http://api.test"


def test_tampered_part_is_rejected_and_nothing_is_left(bundle: Path, tmp_path: Path) -> None:
    bad = tmp_path / "bad.witan"
    rewrite(bundle, bad, lambda n, d: (n, d[:10] + bytes([d[10] ^ 0xFF]) + d[11:]) if n == f"parts/{SHA_A}.parquet" else (n, d))
    off, _ = offline_client()
    with pytest.raises(BundleError, match="sha256"):
        off.projects.load(bad, tmp_path / "store")
    parts = tmp_path / "store" / SLUG / "parts"
    assert not parts.exists() or not list(parts.iterdir())
    with pytest.raises(BundleError, match="sha256"):
        off.projects.load(bad, check=True)


def test_altered_manifest_missing_part_and_foreign_members_are_rejected(bundle: Path, tmp_path: Path) -> None:
    off, _ = offline_client()

    def more_records(n: str, d: bytes):
        if n != "manifest.json":
            return n, d
        m = json.loads(d)
        m["totals"]["records"] = 999
        return n, json.dumps(m).encode()

    cases = {
        "altered": (more_records, [], "altered"),
        "missing": (lambda n, d: None if n == f"parts/{SHA_B}.parquet" else (n, d), [], "do not match its manifest"),
        "traversal": (lambda n, d: (n, d), [("../evil.txt", b"x")], "unexpected member"),
        "stray": (lambda n, d: (n, d), [("parts/readme.txt", b"x")], "unexpected member"),
    }
    for name, (change, extra, message) in cases.items():
        path = tmp_path / f"{name}.witan"
        rewrite(bundle, path, change, extra)
        with pytest.raises(BundleError, match=message):
            off.projects.load(path, tmp_path / f"store-{name}")


def test_header_slug_cannot_escape_the_store(bundle: Path, tmp_path: Path) -> None:
    def evil(n: str, d: bytes):
        if n != "witan-bundle.json":
            return n, d
        h = json.loads(d)
        h["project"] = "../../outside"
        return n, json.dumps(h).encode()

    path = tmp_path / "evil.witan"
    rewrite(bundle, path, evil)
    off, _ = offline_client()
    with pytest.raises(BundleError, match="invalid project slug"):
        off.projects.load(path, tmp_path / "store")
    assert not (tmp_path / "outside").exists()


def test_not_a_bundle(tmp_path: Path) -> None:
    junk = tmp_path / "junk.witan"
    junk.write_bytes(b"not a tar at all" * 100)
    off, _ = offline_client()
    with pytest.raises(BundleError, match="not a WITAN bundle"):
        off.projects.load(junk, tmp_path / "store")


def _real_bundle(tmp_path: Path, access: str = "public") -> Path:
    """A bundle whose part is real Parquet shaped like the server writes it (allowExtra → _extra)."""
    duckdb = pytest.importorskip("duckdb")
    parts = tmp_path / "src" / "parts"
    parts.mkdir(parents=True)
    raw = parts / "raw.parquet"
    con = duckdb.connect()
    con.execute(
        "COPY (SELECT * FROM (VALUES ('cursor', 41::BIGINT, 1.5::DOUBLE, true, NULL::VARCHAR),"
        " ('retries', 2::BIGINT, NULL::DOUBLE, false, '{\"note\":\"slow\",\"tries\":3}'),"
        " ('empty', NULL::BIGINT, 2.0::DOUBLE, NULL::BOOLEAN, NULL::VARCHAR)) AS t(key, n, v, ok, _extra))"
        f" TO '{raw}' (FORMAT PARQUET)")
    con.close()
    sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    raw.rename(parts / f"{sha}.parquet")
    size = (parts / f"{sha}.parquet").stat().st_size
    manifest = {"format": "parquet", "project": "state-src", "version": 4, "parent": 3, "createdAt": "2026-09-24T00:00:00Z",
                "parts": [{"sha256": sha, "bytes": size, "records": 3, "contributionId": "c", "agentId": "a", "mergedInVersion": 4}],
                "totals": {"records": 3, "bytes": size, "parts": 1, "contributions": 4}, "pulledAt": "x", "source": "http://origin.test"}
    project = {"slug": "state-src", "title": "State", "readme": "r", "license": "cc-by-4.0", "access": access, "visibility": "public",
               "schemaDef": {"fields": [{"name": "key", "type": "string"}], "allowExtra": True}}
    path = tmp_path / "state.witan"
    write_bundle(path, project, manifest, parts, source="http://origin.test", sdk_version="test")
    return path


def test_records_come_back_as_the_api_returns_them(tmp_path: Path) -> None:
    path = _real_bundle(tmp_path)
    off, _ = offline_client()
    off.projects.load(path, tmp_path / "store")
    part = next((tmp_path / "store" / "state-src" / "parts").glob("*.parquet"))
    assert list(iter_records([part])) == [
        {"key": "cursor", "n": 41, "v": 1.5, "ok": True},
        {"key": "retries", "n": 2, "ok": False, "note": "slow", "tries": 3},
        {"key": "empty", "v": 2.0},
    ]


def test_push_bundle_uploads_the_records_and_refuses_paid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    off, calls = offline_client()
    pushed: list[tuple[str, list[dict], str]] = []

    def fake_push(slug, path, *, source_declaration=None, workers=4, wait=False, timeout=900.0):
        lines = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
        pushed.append((slug, lines, source_declaration))
        return {"contributionId": "c-9", "status": "merged", "mergedVersion": 1, "acceptedCount": len(lines)}

    monkeypatch.setattr(off.projects, "push", fake_push)
    path = _real_bundle(tmp_path)
    r = off.projects.push_bundle(path, "state-copy", out_dir=tmp_path / "store")
    assert r["status"] == "merged" and r["bundle"]["records"] == 3 and r["bundle"]["version"] == 4
    slug, lines, declaration = pushed[0]
    assert slug == "state-copy" and len(lines) == 3 and lines[1]["note"] == "slow"
    assert "Imported from bundle state.witan" in declaration and "cc-by-4.0" in declaration
    assert not (tmp_path / "state.witan.records.jsonl").exists()  # cleaned up after a finished push

    paid_dir = tmp_path / "paid"
    paid_dir.mkdir()
    paid = _real_bundle(paid_dir, access="paid")
    with pytest.raises(WitanError, match="paid project"):
        off.projects.push_bundle(paid, "state-copy", out_dir=tmp_path / "store2")
    assert not (tmp_path / "store2").exists()  # refused before anything was loaded
    off.projects.push_bundle(paid, "state-copy", out_dir=tmp_path / "store2", allow_paid=True)
    assert len(pushed) == 2 and calls == []


def test_cli_save_load_check_and_error_exit(fake: ProjectFake, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    client = Witan("km_test", base_url="http://api.test", transport=httpx.MockTransport(fake))
    out = tmp_path / "obs.witan"
    assert main(["save", f"{SLUG}@110", "-o", str(out), "--cache", str(tmp_path / "cache")], client=client) == 0
    text = capsys.readouterr().out
    assert "3 records in 2 parts" in text and str(out) in text and "manifest sha256" in text
    assert main(["load", str(out), "--check"], client=client) == 0
    assert capsys.readouterr().out.startswith("ok · agent-api-observatory v110")
    assert main(["load", str(out), "--out", str(tmp_path / "store")], client=client) == 0
    text = capsys.readouterr().out
    assert "2 new parts" in text and "wtn query agent-api-observatory@110" in text
    bad = tmp_path / "bad.witan"
    rewrite(out, bad, lambda n, d: None if n.startswith("parts/") else (n, d))
    assert main(["load", str(bad)], client=client) == 1
    assert "error:" in capsys.readouterr().err
