"""Dataset bundles: one version of a project as a single file, like ``docker save``.

A bundle (``.witan``) is an uncompressed tar — the parts are already compressed Parquet —
with exactly these members, in this order::

    witan-bundle.json          header: format, project, version, totals, manifest sha256, origin
    project.json               slug, title, readme, schema contract, license, tags, access, visibility
    manifest.json              the version manifest as the server published it (no download URLs)
    parts/<sha256>.parquet     every part the manifest lists, named by its content hash

Loading checks everything before anything lands on disk: only those member names (no
links, no paths elsewhere), the manifest's sha256 against the header, each part's sha256
against its name and its size against the manifest, and the totals. A bundle is as
trustworthy as the manifest in it; manifests are not signed yet.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path
from typing import Any, Callable, Iterator

from .errors import WitanError

BUNDLE_FORMAT = "witan-bundle/1"
MANIFEST_FORMAT = "witan-dataset-manifest/1"
HEADER = "witan-bundle.json"
PROJECT = "project.json"
MANIFEST = "manifest.json"
PART_RE = re.compile(r"^parts/([0-9a-f]{64})\.parquet$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,58}[a-z0-9]$")  # the header's slug becomes a directory name
PROJECT_KEYS = ("slug", "title", "readme", "schemaDef", "license", "tags", "access", "visibility", "maintainer")
# Keys a local manifest carries about this machine (pull/load bookkeeping, the x402 receipt of a
# purchase), not about the version.
LOCAL_KEYS = ("count", "file", "downloaded", "loaded", "pulledAt", "loadedAt", "loadedFrom", "source", "verified", "x402")
EXTRA_COLUMN = "_extra"
_CHUNK = 1024 * 1024


class BundleError(WitanError):
    """The file is not a valid WITAN bundle, or it fails verification."""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def published_manifest(local: dict[str, Any]) -> dict[str, Any]:
    """The server's manifest back from a local one (``pull`` stamps ``format: parquet`` and bookkeeping)."""
    m = {k: v for k, v in local.items() if k not in LOCAL_KEYS}
    m["format"] = MANIFEST_FORMAT
    m["parts"] = [{k: v for k, v in p.items() if k != "url"} for p in local["parts"]]
    return m


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes, mtime: int) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = mtime
    info.mode = 0o644
    tar.addfile(info, io.BytesIO(data))


def write_bundle(path: Path, project: dict[str, Any], local_manifest: dict[str, Any], parts_dir: Path, *,
                 source: str, sdk_version: str) -> dict[str, Any]:
    """Write one version as a bundle (atomically: a temp file renamed into place). Returns the header."""
    manifest = published_manifest(local_manifest)
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
    shas: list[str] = []
    for p in manifest["parts"]:
        if p["sha256"] not in shas:
            shas.append(p["sha256"])
    missing = [s for s in shas if not (parts_dir / f"{s}.parquet").is_file()]
    if missing:
        raise BundleError(f"{len(missing)} part(s) of v{manifest['version']} are not on disk (first: {missing[0][:12]}…)")
    saved_at = _now()
    header = {
        "format": BUNDLE_FORMAT,
        "project": project.get("slug") or manifest.get("project"),
        "version": int(manifest["version"]),
        "title": project.get("title"),
        "license": project.get("license"),
        "access": project.get("access", "public"),
        "visibility": project.get("visibility", "public"),
        "records": int(manifest["totals"]["records"]),
        "parts": len(shas),
        "bytes": sum((parts_dir / f"{s}.parquet").stat().st_size for s in shas),
        "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "savedAt": saved_at,
        "source": source,
        "sdk": f"witan-sdk/{sdk_version}",
    }
    mtime = int(_dt.datetime.fromisoformat(saved_at).timestamp())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tarfile.open(tmp, "w", format=tarfile.PAX_FORMAT) as tar:
            _add_bytes(tar, HEADER, json.dumps(header, indent=2, ensure_ascii=False).encode("utf-8"), mtime)
            _add_bytes(tar, PROJECT, json.dumps({k: project[k] for k in PROJECT_KEYS if k in project},
                                                indent=2, ensure_ascii=False).encode("utf-8"), mtime)
            _add_bytes(tar, MANIFEST, manifest_bytes, mtime)
            for sha in shas:
                f = parts_dir / f"{sha}.parquet"
                info = tarfile.TarInfo(f"parts/{sha}.parquet")
                info.size = f.stat().st_size
                info.mtime = mtime
                info.mode = 0o644
                with f.open("rb") as fh:
                    tar.addfile(info, fh)
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return header


def _check_header(header: dict[str, Any]) -> dict[str, Any]:
    if header.get("format") != BUNDLE_FORMAT:
        raise BundleError(f"unsupported bundle format {header.get('format')!r} (this SDK reads {BUNDLE_FORMAT})")
    if not isinstance(header.get("project"), str) or not SLUG_RE.match(header["project"]):
        raise BundleError(f"the bundle names an invalid project slug: {header.get('project')!r}")
    if not isinstance(header.get("version"), int) or header["version"] < 1:
        raise BundleError(f"the bundle names an invalid version: {header.get('version')!r}")
    return header


def peek_header(path: Path) -> dict[str, Any]:
    """The bundle header (its first member) without reading the parts — cheap, but unverified."""
    if not path.is_file():
        raise BundleError(f"no such file: {path}")
    try:
        with tarfile.open(path, "r:") as tar:
            first = tar.next()
            if first is None or first.name != HEADER or not first.isfile():
                raise BundleError(f"{path.name} is not a WITAN bundle (no {HEADER} first)")
            fh = tar.extractfile(first)
            header = json.loads(fh.read().decode("utf-8")) if fh else None
    except tarfile.TarError as exc:
        raise BundleError(f"{path.name} is not a WITAN bundle (not a tar file)") from exc
    except (UnicodeDecodeError, ValueError) as exc:
        raise BundleError(f"{HEADER} in the bundle is not valid JSON") from exc
    if not isinstance(header, dict):
        raise BundleError(f"{HEADER} in the bundle is not an object")
    return _check_header(header)


def read_bundle(path: Path, parts_dir: Path | None = None, *,
                accept: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Verify a bundle and, when ``parts_dir`` is given, place its parts there.

    Parts stream to ``<sha>.parquet.part`` while their hash is computed and are renamed
    only after the whole bundle verified; on any failure the temporaries are removed and
    nothing new is left behind. A part already on disk with the right size is kept (its
    bytes in the bundle are still hashed). ``accept`` sees the verified manifest last, before
    anything is kept, and refuses the bundle by raising. Returns ``{header, project, manifest, written}``.
    """
    if not path.is_file():
        raise BundleError(f"no such file: {path}")
    header: dict[str, Any] | None = None
    project: dict[str, Any] | None = None
    manifest_bytes: bytes | None = None
    seen_parts: dict[str, int] = {}
    staged: list[tuple[Path, Path]] = []
    names: set[str] = set()
    try:
        try:
            tar = tarfile.open(path, "r:")
        except tarfile.TarError as exc:
            raise BundleError(f"{path.name} is not a WITAN bundle (not a tar file)") from exc
        with tar:
            for member in tar:
                name = member.name
                if name in names:
                    raise BundleError(f"duplicate member in bundle: {name}")
                names.add(name)
                if not member.isfile():
                    raise BundleError(f"unexpected member in bundle (not a regular file): {name}")
                fh = tar.extractfile(member)
                if fh is None:
                    raise BundleError(f"unreadable member in bundle: {name}")
                if name in (HEADER, PROJECT, MANIFEST):
                    data = fh.read()
                    if name == MANIFEST:
                        manifest_bytes = data
                    else:
                        try:
                            parsed = json.loads(data.decode("utf-8"))
                        except (UnicodeDecodeError, ValueError) as exc:
                            raise BundleError(f"{name} in the bundle is not valid JSON") from exc
                        if name == HEADER:
                            header = parsed
                        else:
                            project = parsed
                    continue
                m = PART_RE.match(name)
                if not m:
                    raise BundleError(f"unexpected member in bundle: {name}")
                sha = m.group(1)
                digest = hashlib.sha256()
                size = 0
                target = parts_dir / f"{sha}.parquet" if parts_dir is not None else None
                tmp: Path | None = None
                out = None
                if target is not None and not (target.is_file() and target.stat().st_size == member.size):
                    parts_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
                    tmp = target.with_suffix(".parquet.part")
                    out = tmp.open("wb")
                    staged.append((tmp, target))
                try:
                    while True:
                        chunk = fh.read(_CHUNK)
                        if not chunk:
                            break
                        digest.update(chunk)
                        size += len(chunk)
                        if out is not None:
                            out.write(chunk)
                finally:
                    if out is not None:
                        out.close()
                if digest.hexdigest() != sha:
                    raise BundleError(f"part {sha[:12]}… failed sha256 verification — the bundle is damaged or was altered")
                seen_parts[sha] = size

        if header is None or project is None or manifest_bytes is None:
            missing = [n for n, v in ((HEADER, header), (PROJECT, project), (MANIFEST, manifest_bytes)) if v is None]
            raise BundleError(f"not a complete WITAN bundle: missing {', '.join(missing)}")
        _check_header(header)
        if hashlib.sha256(manifest_bytes).hexdigest() != header.get("manifestSha256"):
            raise BundleError("manifest.json does not match the sha256 in the bundle header — the bundle was altered")
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise BundleError("manifest.json in the bundle is not valid JSON") from exc
        slug = header.get("project")
        if project.get("slug") != slug or manifest.get("project", slug) != slug:
            raise BundleError("the bundle's header, project.json and manifest name different projects")
        if int(manifest.get("version", -1)) != int(header.get("version", -2)):
            raise BundleError("the bundle's header and manifest name different versions")
        expected: dict[str, int] = {}
        for p in manifest.get("parts", []):
            expected[p["sha256"]] = int(p["bytes"])
        if set(expected) != set(seen_parts):
            lacking = sorted(set(expected) - set(seen_parts))
            extra = sorted(set(seen_parts) - set(expected))
            detail = f"missing {lacking[0][:12]}…" if lacking else f"unlisted {extra[0][:12]}…"
            raise BundleError(f"the bundle's parts do not match its manifest ({detail})")
        for sha, size in seen_parts.items():
            if size != expected[sha]:
                raise BundleError(f"part {sha[:12]}… is {size} bytes, the manifest says {expected[sha]}")
        totals = manifest.get("totals", {})
        records = sum(int(p["records"]) for p in manifest["parts"])
        if int(totals.get("records", records)) != records:
            raise BundleError(f"manifest totals say {totals.get('records')} records, its parts hold {records}")
        if accept is not None:
            accept(manifest)

        for tmp, target in staged:
            tmp.replace(target)
        written = len(staged)
        staged = []
        return {"header": header, "project": project, "manifest": manifest, "written": written}
    finally:
        for tmp, _ in staged:
            if tmp.exists():
                tmp.unlink()


def local_manifest(manifest: dict[str, Any], header: dict[str, Any], bundle_name: str, written: int) -> dict[str, Any]:
    """The manifest a loaded version keeps on disk — the same shape ``pull`` writes, so ``query`` and
    ``pull`` treat it as a complete local copy."""
    m = {k: v for k, v in manifest.items()}
    m.update({
        "format": "parquet",
        "count": int(manifest["totals"]["records"]),
        "file": "parts/<sha256>.parquet",
        "downloaded": 0,
        "loaded": written,
        "loadedAt": _now(),
        "loadedFrom": bundle_name,
        "source": header.get("source"),
    })
    return m


def record_from_row(columns: list[str], row: Any) -> dict[str, Any]:
    """One Parquet row as the API returns the record: null fields omitted, the ``_extra`` JSON
    column of an ``allowExtra`` schema folded back in."""
    rec: dict[str, Any] = {}
    for col, val in zip(columns, row):
        if col == EXTRA_COLUMN:
            if val:
                rec.update(json.loads(val))
            continue
        if val is None:
            continue
        rec[col] = val
    return rec


def iter_records(part_files: list[Path]) -> Iterator[dict[str, Any]]:
    """Records of a version from its parts, shaped the way the API returns them: null fields
    omitted, the ``_extra`` JSON column of an ``allowExtra`` schema folded back into the record."""
    try:
        import duckdb
    except ImportError as exc:
        raise WitanError('reading bundle records needs the extra: pip install "witan-sdk[query]"') from exc
    con = duckdb.connect()
    try:
        for f in part_files:
            quoted = "'" + str(f).replace("'", "''") + "'"
            cur = con.execute(f"SELECT * FROM read_parquet({quoted})")
            columns = [d[0] for d in cur.description]
            while True:
                rows = cur.fetchmany(10_000)
                if not rows:
                    break
                for row in rows:
                    yield record_from_row(columns, row)
    finally:
        con.close()
