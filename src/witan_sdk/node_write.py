"""Writes on a WITAN node: local projects, contributions, versions.

A node writes only to its **local projects** — created on the node, marked ``"local": true``
in their ``project.json``. Copies of origin projects (pulled, loaded or followed) stay
read-only there, because a version written next to the origin's would fork its history.

A contribution runs the origin's gates without the LLM screen (like a private project on
the origin): the schema contract, the personal-data pattern, and record-level duplicates
against everything the project already holds. It merges inside the request, so the answer
is final — ``merged`` with the new version, or ``rejected`` with the gate and the reason.
Accepted records become a content-addressed Parquet part (a small tail part folds into a
new one, as on the origin) and a new immutable version manifest; the part is written
before the manifest, so a crash leaves at most an unreferenced part. ``Idempotency-Key``
replays the first answer for 24 hours.

Duplicate detection hashes each record in the form it is stored in (null fields dropped,
integers and numbers normalized), so the set rebuilt from the parts after a restart agrees
with the one kept while running.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import threading
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from .bundle import EXTRA_COLUMN, SLUG_RE, iter_records

MAX_BATCH_RECORDS = 500
MAX_BATCH_BYTES = 512 * 1024
COMPACT_MAX_BYTES = 1024 * 1024
IDEMPOTENCY_TTL_S = 24 * 3600
RRN = re.compile(r"\d{6}[-\s]?[1-4]\d{6}", re.ASCII)  # the origin's personal-data gate
FIELD_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,60}$")
TAG = re.compile(r"^[a-z0-9-]{2,30}$")
DUCK_TYPE = {"string": "VARCHAR", "number": "DOUBLE", "integer": "BIGINT", "boolean": "BOOLEAN"}
CREATE_KEYS = {"slug", "title", "readme", "schemaDef", "license", "tags", "access", "visibility"}


class WriteError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _js_number(v: float) -> str:
    """A float the way JavaScript's JSON.stringify writes it (1.0 → 1, 1e-05 → 0.00001)."""
    if v != v or v in (float("inf"), float("-inf")):
        return "null"
    if v.is_integer() and abs(v) < 1e21:
        return str(int(v))
    if 1e-6 <= abs(v) < 1e21:
        return format(Decimal(repr(v)), "f")
    mantissa, _, exp = repr(v).partition("e")
    e = int(exp)
    return f"{mantissa}e{'+' if e > 0 else '-'}{abs(e)}"


def stable_stringify(v: Any) -> str:
    """The origin's stableStringify: keys sorted recursively, JSON otherwise."""
    if isinstance(v, list):
        return "[" + ",".join(stable_stringify(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ",".join(json.dumps(str(k), ensure_ascii=False) + ":" + stable_stringify(v[k]) for k in sorted(v)) + "}"
    if v is None or isinstance(v, bool) or isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return _js_number(v)
    return json.dumps(v, ensure_ascii=False, default=str)


def record_hash(rec: Any) -> str:
    return hashlib.sha256(stable_stringify(rec).encode("utf-8")).hexdigest()


def validate_schema_def(d: Any) -> str | None:
    """The origin's validateSchemaDef."""
    if not isinstance(d, dict) or not isinstance(d.get("fields"), list) or not 1 <= len(d["fields"]) <= 40:
        return "schemaDef.fields must be a non-empty array (max 40)"
    names: set[str] = set()
    for f in d["fields"]:
        name = f.get("name") if isinstance(f, dict) else None
        if not isinstance(name, str) or not FIELD_NAME.match(name):
            return f"invalid field name: {json.dumps(name)}"
        if f.get("type") not in DUCK_TYPE:
            return f"field {name}: type must be string|number|integer|boolean"
        if name in names:
            return f"duplicate field name: {name}"
        names.add(name)
    return None


def check_record(rec: Any, schema: dict[str, Any]) -> str | None:
    """The origin's checkSchema for one record (JavaScript's typeof rules: a boolean is not a number)."""
    if not isinstance(rec, dict):
        return "not an object"
    for f in schema["fields"]:
        name, kind = f["name"], f["type"]
        v = rec.get(name)
        if v is None:
            if f.get("required") is not False:
                return f'missing required field "{name}"'
            continue
        is_num = isinstance(v, (int, float)) and not isinstance(v, bool)
        if kind == "string" and not isinstance(v, str):
            return f'"{name}" must be string'
        if kind == "boolean" and not isinstance(v, bool):
            return f'"{name}" must be boolean'
        if kind == "number" and not is_num:
            return f'"{name}" must be number'
        if kind == "integer" and not (is_num and (isinstance(v, int) or float(v).is_integer())):
            return f'"{name}" must be integer'
    if schema.get("allowExtra") is False:
        known = {f["name"] for f in schema["fields"]}
        for k in rec:
            if k not in known:
                return f'unknown field "{k}"'
    return None


def stored_form(rec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """The record as the part will hold it and a read will return it: schema fields without nulls,
    integers as int, numbers as float; extra fields kept only when the schema allows them
    (``allowExtra`` true — an unset allowExtra lets them through the gate but does not store them)."""
    out: dict[str, Any] = {}
    known = set()
    for f in schema["fields"]:
        known.add(f["name"])
        v = rec.get(f["name"])
        if v is None:
            continue
        if f["type"] == "integer":
            v = int(v)
        elif f["type"] == "number":
            v = float(v)
        out[f["name"]] = v
    if schema.get("allowExtra"):
        for k, v in rec.items():
            if k not in known:
                out[k] = v
    return out


def _write_json(path: Path, obj: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class Writer:
    """Local projects and their contributions, one lock per project."""

    def __init__(self, root: Path, follow: set[str] | None = None) -> None:
        self.root = root
        self.follow = follow or set()
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._hashes: dict[str, set[str]] = {}

    def _lock(self, slug: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(slug, threading.Lock())

    # ---- projects ----
    def project_file(self, slug: str) -> Path:
        return self.root / slug / "project.json"

    def is_local(self, slug: str) -> bool:
        try:
            return bool(json.loads(self.project_file(slug).read_text(encoding="utf-8")).get("local"))
        except (OSError, ValueError):
            return False

    def create(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise WriteError(400, "body must be an object")
        unknown = sorted(set(body) - CREATE_KEYS)
        if unknown:
            raise WriteError(400, f"body must NOT have additional properties: {unknown[0]}")
        slug = body.get("slug")
        if not isinstance(slug, str) or not SLUG_RE.match(slug):
            raise WriteError(400, "body/slug must match the slug pattern (a-z, 0-9, dashes; 3-60 characters)")
        title, readme = body.get("title"), body.get("readme")
        if not isinstance(title, str) or not 4 <= len(title) <= 140:
            raise WriteError(400, "body/title must be 4-140 characters")
        if not isinstance(readme, str) or not 20 <= len(readme) <= 20000:
            raise WriteError(400, "body/readme must be 20-20000 characters")
        err = validate_schema_def(body.get("schemaDef"))
        if err:
            raise WriteError(400, err)
        license_ = body.get("license", "platform-standard")
        if not isinstance(license_, str) or len(license_) > 60:
            raise WriteError(400, "body/license must be a string of at most 60 characters")
        tags = body.get("tags", [])
        if not isinstance(tags, list) or len(tags) > 8 or not all(isinstance(t, str) and TAG.match(t) for t in tags):
            raise WriteError(400, "body/tags must be up to 8 tags of a-z, 0-9 and dashes")
        if body.get("access", "public") != "public":
            raise WriteError(400, "a node does not sell data: access must be public (paid projects live on the origin)")
        visibility = body.get("visibility", "private")
        if visibility not in ("public", "private"):
            raise WriteError(400, "body/visibility must be public or private")
        with self._lock(slug):
            if (self.root / slug).exists() or slug in self.follow:
                raise WriteError(409, "slug already exists on this node")
            (self.root / slug / "parts").mkdir(parents=True)
            project = {
                "slug": slug, "title": title, "readme": readme, "schemaDef": body["schemaDef"], "license": license_,
                "tags": tags, "access": "public", "visibility": visibility, "maintainer": "this node",
                "local": True, "createdAt": _now(),
            }
            _write_json(self.project_file(slug), project)
        return {"id": None, "slug": slug, "visibility": visibility, "local": True}

    # ---- contributions ----
    def _contrib_path(self, slug: str, cid: str) -> Path:
        return self.root / slug / "contributions" / f"{cid}.json"

    def contribution(self, slug: str, cid: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f-]{36}", cid):
            raise WriteError(400, "invalid contribution id")
        try:
            return json.loads(self._contrib_path(slug, cid).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise WriteError(404, "contribution not found") from exc

    def _latest(self, slug: str) -> tuple[int, dict[str, Any] | None]:
        best = 0
        d = self.root / slug
        for e in d.iterdir():
            if e.is_dir() and re.fullmatch(r"v[1-9][0-9]*", e.name) and (e / "manifest.json").is_file():
                best = max(best, int(e.name[1:]))
        if best == 0:
            return 0, None
        return best, json.loads((d / f"v{best}" / "manifest.json").read_text(encoding="utf-8"))

    def _known_hashes(self, slug: str, manifest: dict[str, Any] | None) -> set[str]:
        """Every record hash the project holds — kept in memory, rebuilt from the parts after a restart."""
        if slug not in self._hashes:
            seen: set[str] = set()
            if manifest:
                files = [self.root / slug / "parts" / f"{p['sha256']}.parquet" for p in manifest["parts"]]
                for rec in iter_records(files):
                    seen.add(record_hash(rec))
            self._hashes[slug] = seen
        return self._hashes[slug]

    def _idempotency(self, slug: str) -> tuple[Path, dict[str, Any]]:
        path = self.root / slug / "index" / "idempotency.json"
        try:
            keys = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            keys = {}
        now = _dt.datetime.now(_dt.timezone.utc).timestamp()
        return path, {k: v for k, v in keys.items() if now - float(v.get("at", 0)) < IDEMPOTENCY_TTL_S}

    def contribute(self, slug: str, body: Any, idem: str | None) -> tuple[int, dict[str, Any], bool]:
        """Run the gates and merge. Returns (HTTP status, contribution view, replayed)."""
        if not self.is_local(slug):
            raise WriteError(405, f"{slug} on this node is a copy of an origin project — write to the origin")
        if not isinstance(body, dict) or set(body) - {"records", "sourceDeclaration"}:
            raise WriteError(400, "body must be {records, sourceDeclaration?}")
        records = body.get("records")
        source = body.get("sourceDeclaration")
        if not isinstance(records, list) or not 1 <= len(records) <= MAX_BATCH_RECORDS or not all(isinstance(r, dict) for r in records):
            raise WriteError(400, f"body/records must be 1-{MAX_BATCH_RECORDS} objects (bigger batches: several calls)")
        if source is not None and (not isinstance(source, str) or len(source) > 500):
            raise WriteError(400, "body/sourceDeclaration must be at most 500 characters")
        raw = json.dumps(records, ensure_ascii=False, separators=(",", ":"))
        if len(raw.encode("utf-8")) > MAX_BATCH_BYTES:
            raise WriteError(413, f"batch too large (max {MAX_BATCH_BYTES} bytes)")
        if idem is not None and (not idem or len(idem) > 200):
            raise WriteError(400, "Idempotency-Key must be 1-200 characters")
        body_sha = hashlib.sha256(f"{slug}\n{raw}\n{source or ''}".encode("utf-8")).hexdigest()

        with self._lock(slug):
            idem_path, keys = self._idempotency(slug)
            if idem and idem in keys:
                if keys[idem]["bodySha"] != body_sha:
                    raise WriteError(422, "Idempotency-Key was already used with a different project or body")
                return 200, self.contribution(slug, keys[idem]["contributionId"]), True

            project = json.loads(self.project_file(slug).read_text(encoding="utf-8"))
            schema = project["schemaDef"]
            cid = str(uuid.uuid4())
            view: dict[str, Any] = {"id": cid, "status": "rejected", "recordCount": len(records), "acceptedCount": None,
                                    "verdict": None, "mergedVersion": None, "createdAt": _now(), "sourceDeclaration": source}
            parent_v, parent = self._latest(slug)
            known = self._known_hashes(slug, parent)
            accepted: list[dict[str, Any]] = []
            batch: set[str] = set()
            dropped = 0
            verdict: dict[str, Any] | None = None
            for line, rec in enumerate(records, start=1):
                err = check_record(rec, schema)
                if err:
                    verdict = {"gate": "schema", "reason": f"line {line}: {err}"}
                    break
                if RRN.search(json.dumps(rec, ensure_ascii=False, separators=(",", ":"))):
                    verdict = {"gate": "pii", "reason": "resident registration number pattern detected"}
                    break
                stored = stored_form(rec, schema)
                h = record_hash(stored)
                if h in known or h in batch:
                    dropped += 1
                    continue
                batch.add(h)
                accepted.append(stored)
            if verdict is None and not accepted:
                verdict = {"gate": "dedup", "reason": "every record already exists in the dataset"}

            if verdict is None:
                version = parent_v + 1
                self._merge(slug, schema, parent, version, accepted, cid, dropped)
                known.update(batch)
                view.update({"status": "merged", "acceptedCount": len(accepted), "mergedVersion": version,
                             "verdict": {"ok": True, "droppedDuplicates": dropped, "parts": 1}})
            else:
                view["verdict"] = verdict
            (self.root / slug / "contributions").mkdir(exist_ok=True)
            _write_json(self._contrib_path(slug, cid), view)
            if idem:
                keys[idem] = {"bodySha": body_sha, "contributionId": cid, "at": _dt.datetime.now(_dt.timezone.utc).timestamp()}
                idem_path.parent.mkdir(exist_ok=True)
                _write_json(idem_path, keys)
            return 201, view, False

    def _merge(self, slug: str, schema: dict[str, Any], parent: dict[str, Any] | None, version: int,
               accepted: list[dict[str, Any]], cid: str, dropped: int) -> dict[str, Any]:
        import duckdb

        parts_dir = self.root / slug / "parts"
        parent_parts = list((parent or {}).get("parts", []))
        tail = parent_parts[-1] if parent_parts else None
        base = {"contributionId": cid, "agentId": "node", "mergedInVersion": version}
        fields = schema["fields"]
        allow_extra = bool(schema.get("allowExtra"))
        columns = [(f["name"], DUCK_TYPE[f["type"]]) for f in fields] + ([(EXTRA_COLUMN, "VARCHAR")] if allow_extra else [])
        names = ", ".join(f'"{n}"' for n, _ in columns)
        known = {f["name"] for f in fields}

        def row(rec: dict[str, Any]) -> tuple[Any, ...]:
            values = [rec.get(f["name"]) for f in fields]
            if allow_extra:
                extra = {k: v for k, v in rec.items() if k not in known}
                values.append(json.dumps(extra, ensure_ascii=False) if extra else None)
            return tuple(values)

        compact = tail is not None and int(tail["bytes"]) < COMPACT_MAX_BYTES
        tmp = parts_dir / f".{cid}.parquet.tmp"
        con = duckdb.connect()
        try:
            con.execute(f"CREATE TABLE t ({', '.join(f'{chr(34)}{n}{chr(34)} {ty}' for n, ty in columns)})")
            if compact:
                tail_file = str(parts_dir / f"{tail['sha256']}.parquet").replace("'", "''")
                con.execute(f"INSERT INTO t SELECT {names} FROM read_parquet('{tail_file}', union_by_name = true)")
            con.executemany(f"INSERT INTO t VALUES ({', '.join('?' for _ in columns)})", [row(r) for r in accepted])
            con.execute(f"COPY t TO '{str(tmp).replace(chr(39), chr(39) * 2)}' (FORMAT PARQUET, COMPRESSION SNAPPY)")
        finally:
            con.close()
        sha = hashlib.sha256(tmp.read_bytes()).hexdigest()
        final = parts_dir / f"{sha}.parquet"
        if final.exists():
            tmp.unlink()
        else:
            os.replace(tmp, final)
        size = final.stat().st_size
        if compact:
            previous = int(tail["records"])  # type: ignore[index]
            tail_sources = tail.get("sources") or [{  # type: ignore[union-attr]
                "contributionId": tail.get("contributionId", ""), "agentId": tail.get("agentId", ""),  # type: ignore[union-attr]
                "mergedInVersion": tail.get("mergedInVersion", 0), "records": previous, "offset": 0}]  # type: ignore[union-attr]
            ref = {"sha256": sha, "bytes": size, "records": previous + len(accepted), **base,
                   "sources": [*tail_sources, {**base, "records": len(accepted), "offset": previous}]}
            parts = parent_parts[:-1] + [ref]
        else:
            ref = {"sha256": sha, "bytes": size, "records": len(accepted), **base,
                   "sources": [{**base, "records": len(accepted), "offset": 0}]}
            parts = parent_parts + [ref]
        totals = (parent or {}).get("totals", {})
        manifest = {
            "format": "parquet", "project": slug, "version": version, "parent": version - 1 if version > 1 else None,
            "createdAt": _now(),
            "schema": {"hash": hashlib.sha256(stable_stringify(schema).encode("utf-8")).hexdigest(),
                       "fields": fields, "allowExtra": allow_extra},
            "parts": parts,
            "totals": {"records": sum(int(p["records"]) for p in parts), "bytes": sum(int(p["bytes"]) for p in parts),
                       "parts": len(parts), "contributions": int(totals.get("contributions", 0) or 0) + 1},
            "fragment": {"contributionId": cid, "agentId": "node", "accepted": len(accepted), "droppedDuplicates": dropped},
            "count": sum(int(p["records"]) for p in parts), "file": "parts/<sha256>.parquet", "source": "local",
        }
        vdir = self.root / slug / f"v{version}"
        vdir.mkdir()
        _write_json(vdir / "manifest.json", manifest)  # the part is on disk first: a crash leaves at most an orphan part
        return manifest
