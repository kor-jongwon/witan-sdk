"""Trusted origins and manifest signatures.

A WITAN origin signs every version manifest it hands out (Ed25519, key at
``/.well-known/witan-keys``). A client pins an origin's keys once — ``Witan.trust()`` /
``wtn trust add``, trust on first use — and from then on any copy of that origin's manifest can
be checked wherever it came from: the origin, a node, a node following a node, a bundle. The
parts a manifest lists are content-addressed, so a verified manifest vouches for the bytes too;
the mirrors in between need no trust at all.

Pinned keys live in ``$WITAN_TRUST_FILE``, else ``$XDG_CONFIG_HOME/witan/trust.json``, else
``~/.config/witan/trust.json``. ``WITAN_VERIFY=1`` makes every pull and load require a
verified signature (as ``verify=True`` / ``--verify`` does per call).
"""

from __future__ import annotations

import base64
import binascii
import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any

from .bundle import LOCAL_KEYS, MANIFEST_FORMAT
from .ed25519 import verify as _ed25519_verify
from .errors import WitanError

VOLATILE = ("signature", "urlExpiresAt", "paid", "verified")


class SignatureError(WitanError):
    """A manifest's signature is missing where required, untrusted, or does not match."""


def trust_file() -> Path:
    explicit = os.environ.get("WITAN_TRUST_FILE")
    if explicit:
        return Path(explicit)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "witan" / "trust.json"


def trusted() -> dict[str, list[dict[str, Any]]]:
    """origin → its pinned keys."""
    try:
        data = json.loads(trust_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    origins = data.get("origins") if isinstance(data, dict) else None
    return origins if isinstance(origins, dict) else {}


def _save(origins: dict[str, list[dict[str, Any]]]) -> None:
    path = trust_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"origins": origins}, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def add(origin: str, keys: list[dict[str, Any]]) -> dict[str, Any]:
    """Pin ``keys`` for ``origin`` (kept alongside any already pinned). Returns what changed."""
    origin = origin.rstrip("/")
    good = []
    for k in keys:
        try:
            raw = base64.b64decode(k["publicKey"], validate=True)
        except (KeyError, TypeError, binascii.Error) as exc:
            raise WitanError(f"{origin} published a malformed key") from exc
        if k.get("alg") != "Ed25519" or len(raw) != 32 or not isinstance(k.get("kid"), str):
            raise WitanError(f"{origin} published a key this SDK cannot use ({k.get('alg')})")
        good.append({"kid": k["kid"], "alg": "Ed25519", "publicKey": k["publicKey"]})
    if not good:
        raise WitanError(f"{origin} publishes no signing key")
    origins = trusted()
    pinned = origins.get(origin, [])
    have = {k["kid"] for k in pinned}
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    new = [{**k, "addedAt": now} for k in good if k["kid"] not in have]
    origins[origin] = pinned + new
    _save(origins)
    return {"origin": origin, "keys": [k["kid"] for k in origins[origin]], "added": [k["kid"] for k in new],
            "file": str(trust_file())}


def remove(origin: str) -> bool:
    origins = trusted()
    if origin.rstrip("/") not in origins:
        return False
    del origins[origin.rstrip("/")]
    _save(origins)
    return True


def statement(manifest: dict[str, Any], origin: str) -> bytes:
    """The bytes the origin signed: {v, origin, manifest} with the manifest as published (no URLs,
    no local bookkeeping), written the way the origin's stableStringify writes it."""
    from .node_write import stable_stringify

    content = {k: v for k, v in manifest.items() if k not in VOLATILE and k not in LOCAL_KEYS}
    if content.get("format") == "parquet":  # pull's local marker; the origin published its own format
        content["format"] = MANIFEST_FORMAT
    content["parts"] = [{k: v for k, v in p.items() if k != "url"} for p in manifest.get("parts", [])]
    return stable_stringify({"v": 1, "origin": origin, "manifest": content}).encode("utf-8")


def require_default() -> bool:
    return os.environ.get("WITAN_VERIFY", "").strip().lower() in ("1", "true", "yes")


def check(manifest: dict[str, Any], *, require: bool | None = None) -> dict[str, Any]:
    """Verify ``manifest``'s signature against the pinned keys.

    Returns ``{"status": "verified" | "unsigned" | "untrusted", "origin", "kid"}``. A signature
    from a trusted origin that does not match — or names a key that origin never published — is
    always an error. ``require`` (default: ``WITAN_VERIFY``) also refuses unsigned manifests and
    origins not trusted yet.
    """
    must = require_default() if require is None else require
    what = f"{manifest.get('project', '?')} v{manifest.get('version', '?')}"
    sig = manifest.get("signature")
    if not isinstance(sig, dict):
        if must:
            raise SignatureError(f"{what} is not signed — only versions an origin published carry a signature")
        return {"status": "unsigned", "origin": None, "kid": None}
    origin = str(sig.get("origin", "")).rstrip("/")
    kid = sig.get("kid")
    keys = {k["kid"]: k for k in trusted().get(origin, [])}
    if not keys:
        if must:
            raise SignatureError(f"{what} is signed by {origin}, which is not trusted here — pin its key first: "
                                 f"WITAN_BASE_URL={origin} wtn trust add")
        return {"status": "untrusted", "origin": origin, "kid": kid}
    key = keys.get(kid)
    if key is None:
        raise SignatureError(f"{what} is signed with key {kid}, which is not one of {origin}'s trusted keys")
    try:
        public = base64.b64decode(key["publicKey"])
        signature = base64.b64decode(str(sig.get("sig", "")), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignatureError(f"{what} carries a malformed signature") from exc
    if sig.get("alg") != "Ed25519" or not _ed25519_verify(public, statement(manifest, origin), signature):
        raise SignatureError(f"{what} does not match {origin}'s signature — the manifest was altered or corrupted")
    return {"status": "verified", "origin": origin, "kid": kid}
