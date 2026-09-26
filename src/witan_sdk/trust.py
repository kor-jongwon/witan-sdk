"""Trusted origins and manifest signatures.

A WITAN origin signs every version manifest it hands out (Ed25519, key at
``/.well-known/witan-keys``). A client pins an origin's keys once — ``Witan.trust()`` /
``wtn trust add``, trust on first use — and from then on any copy of that origin's manifest can
be checked wherever it came from: the origin, a node, a node following a node, a bundle. The
parts a manifest lists are content-addressed, so a verified manifest vouches for the bytes too;
the mirrors in between need no trust at all.

When the origin rotates its key, the old key endorses the new one, and the endorsements travel in
every signature (``chain``). A pinned key's endorsement is as good as the pin: the new key is
verified against it and pinned (``endorsedBy``), offline too. A retired key keeps verifying what
it signed before the rotation. A key the origin marks revoked in its own keys document stops
counting, and so does every key pinned through it; a key nothing pinned vouches for is refused
until someone re-pins by hand (``Witan.trust(force=True)`` / ``wtn trust add --force``). Only the
origin's own document is applied: ``Witan.trust`` refuses one that names another origin.

Pinned keys live in ``$WITAN_TRUST_FILE``, else ``$XDG_CONFIG_HOME/witan/trust.json``, else
``~/.config/witan/trust.json``. ``WITAN_VERIFY=1`` makes every pull and load require a
verified signature (as ``verify=True`` / ``--verify`` does per call).
"""

from __future__ import annotations

import base64
import binascii
import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .bundle import LOCAL_KEYS, MANIFEST_FORMAT
from .ed25519 import verify as _ed25519_verify
from .errors import WitanError

# Not signed: what the origin leaves out (api/src/signing.ts signedContent: signature, urlExpiresAt,
# paid, the part URLs) and what this SDK adds to a copy (verified, and bundle.LOCAL_KEYS).
VOLATILE = ("signature", "urlExpiresAt", "paid", "verified")
STATUSES = ("current", "retired")


class SignatureError(WitanError):
    """A manifest's signature is missing where required, untrusted, or does not match."""


def origin_of(url: str) -> str:
    """``scheme://host[:port]`` of ``url``: lowercase, default port dropped, no path — what two
    spellings of one origin have in common."""
    p = urlsplit(str(url).strip())
    scheme = p.scheme.lower()
    host = (p.hostname or "").lower()
    if ":" in host:
        host = f"[{host}]"
    try:
        port = p.port
    except ValueError:
        port = None
    default = {"http": 80, "https": 443}.get(scheme)
    return f"{scheme}://{host}" + (f":{port}" if port is not None and port != default else "")


def trust_file() -> Path:
    explicit = os.environ.get("WITAN_TRUST_FILE")
    if explicit:
        return Path(explicit)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "witan" / "trust.json"


def trusted() -> dict[str, list[dict[str, Any]]]:
    """origin → its pinned keys (revoked ones stay listed, marked ``revoked``)."""
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


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _key(origin: str, k: dict[str, Any]) -> dict[str, Any]:
    """A usable Ed25519 key record, or WitanError: base64 of 32 bytes, kid = its sha256 prefix."""
    try:
        raw = base64.b64decode(k["publicKey"], validate=True)
    except (KeyError, TypeError, binascii.Error) as exc:
        raise WitanError(f"{origin} published a malformed key") from exc
    if k.get("alg") != "Ed25519" or len(raw) != 32 or not isinstance(k.get("kid"), str):
        raise WitanError(f"{origin} published a key this SDK cannot use ({k.get('alg')})")
    if hashlib.sha256(raw).hexdigest()[:16] != k["kid"]:
        raise WitanError(f"{origin} published key {k['kid']} under the wrong id")
    return {"kid": k["kid"], "alg": "Ed25519", "publicKey": k["publicKey"]}


def _status(k: dict[str, Any]) -> dict[str, Any]:
    """The published status worth keeping with a pin (current or retired)."""
    return {"status": k["status"]} if k.get("status") in STATUSES else {}


def _revoked(entries: list[dict[str, Any]]) -> set[str]:
    """The pinned keys that no longer count: revoked, or pinned through an endorsement by such a
    key — whatever a revoked key vouched for goes with it."""
    out = {e["kid"] for e in entries if e.get("revoked")}
    grew = True
    while grew:
        grew = False
        for e in entries:
            if e["kid"] not in out and e.get("endorsedBy") in out:
                out.add(e["kid"])
                grew = True
    return out


def add(origin: str, keys: list[dict[str, Any]]) -> dict[str, Any]:
    """Pin ``keys`` for ``origin`` as they are (trust on first use), alongside any already pinned."""
    origin = origin.rstrip("/")
    good = [(_key(origin, k), _status(k)) for k in keys]
    if not good:
        raise WitanError(f"{origin} publishes no signing key")
    origins = trusted()
    pinned = origins.get(origin, [])
    have = {k["kid"] for k in pinned}
    now = _now()
    new = [{**k, **status, "addedAt": now} for k, status in good if k["kid"] not in have]
    origins[origin] = pinned + new
    _save(origins)
    return {"origin": origin, "keys": [k["kid"] for k in origins[origin] if not k.get("revoked")],
            "added": [k["kid"] for k in new], "refused": [], "revoked": [], "file": str(trust_file())}


def remove(origin: str) -> bool:
    origins = trusted()
    if origin.rstrip("/") not in origins:
        return False
    del origins[origin.rstrip("/")]
    _save(origins)
    return True


def endorsement_statement(origin: str, key: dict[str, Any]) -> bytes:
    """What an endorsement signs: the origin's stableStringify of {v, type, origin, key}."""
    from .node_write import stable_stringify

    return stable_stringify({"v": 1, "type": "witan-key-endorsement", "origin": origin,
                             "key": {"alg": "Ed25519", "kid": key["kid"], "publicKey": key["publicKey"]}}).encode("utf-8")


def _walk(origin: str, links: list[Any], known: dict[str, dict[str, Any]], revoked: set[str],
          target: str | None, what: str) -> list[dict[str, Any]]:
    """Follow endorsements from the keys in ``known``; returns the keys learned, each verified
    against the key that vouched for it. Stops at ``target`` when given. A link whose voucher is
    known but whose endorsement does not check out is tampering and raises."""
    known = dict(known)
    learned: list[dict[str, Any]] = []
    todo = [link for link in links if isinstance(link, dict)]
    progress = True
    while progress and (target is None or target not in known):
        progress = False
        for link in todo:
            kid, by = link.get("kid"), link.get("by")
            if kid in known or kid in revoked or by in revoked or by not in known:
                continue
            try:
                key = _key(origin, link)
                sig = base64.b64decode(str(link.get("sig", "")), validate=True)
                voucher = base64.b64decode(known[by]["publicKey"])
            except (WitanError, binascii.Error, ValueError) as exc:
                raise SignatureError(f"{what}: the endorsement of key {kid} is malformed") from exc
            if not _ed25519_verify(voucher, endorsement_statement(origin, key), sig):
                raise SignatureError(f"{what}: the endorsement of key {kid} by {by} does not verify — the key chain was altered")
            entry = {**key, "endorsedBy": by}
            known[kid] = entry
            learned.append(entry)
            progress = True
    return learned


def _pin(origin: str, entries: list[dict[str, Any]]) -> None:
    origins = trusted()
    pinned = origins.get(origin, [])
    have = {k["kid"] for k in pinned}
    now = _now()
    origins[origin] = pinned + [{**e, "addedAt": now} for e in entries if e["kid"] not in have]
    _save(origins)


def refresh(data: dict[str, Any], *, force: bool = False, expect: str | None = None) -> dict[str, Any]:
    """Apply an origin's published keys (``/.well-known/witan-keys``) to the trust file.

    First contact pins them (trust on first use). After that the document's revocations and
    retirements apply to the pinned keys — it is the origin's own document — and a revoked key
    takes every key pinned through it along. A new key is added only when a pinned key that still
    counts endorsed it (directly or through a chain); one nothing pinned vouches for is ``refused``
    unless ``force`` (re-pinning by hand, after checking its id out of band). ``expect`` is the
    origin the document must be for (the URL it was fetched from); another origin raises
    ``SignatureError`` and nothing changes.
    """
    if not isinstance(data, dict):
        raise WitanError("the server did not answer with a keys document")
    origin = str(data.get("origin", "")).rstrip("/")
    if expect is not None and origin_of(origin) != origin_of(expect):
        raise SignatureError(f"these keys are for {origin or '(no origin)'}, not {expect.rstrip('/')} — pin them only if that "
                             f"server speaks for {origin or 'it'} (a proxy): origin={origin!r} / wtn trust add --origin {origin}")
    published = [k for k in data.get("keys", []) if isinstance(k, dict)]
    status = {k.get("kid"): k.get("status") for k in published}
    live = [k for k in published if k.get("status") != "revoked"]
    revoked_now = {k["kid"] for k in published if k.get("status") == "revoked" and isinstance(k.get("kid"), str)}
    origins = trusted()
    if not origins.get(origin):
        return {**add(origin, live), "revoked": sorted(revoked_now)}
    entries = origins[origin]
    now = _now()
    marked: list[str] = []
    for e in entries:
        if e["kid"] in revoked_now and not e.get("revoked"):
            e["revoked"] = True
            e["revokedAt"] = now
            marked.append(e["kid"])
        elif status.get(e["kid"]) == "retired" and not e.get("revoked"):
            e["status"] = "retired"
    cut = _revoked(entries)
    by_kid = {k.get("kid"): k for k in live}
    links = [{**by_kid[e["kid"]], "by": e.get("by"), "sig": e.get("sig")}
             for e in data.get("endorsements", []) if isinstance(e, dict) and e.get("kid") in by_kid]
    known = {e["kid"]: e for e in entries if e["kid"] not in cut}
    have = {e["kid"] for e in entries}
    reached = _walk(origin, links, known, cut, None, f"{origin}'s published keys")
    learned = [{**k, **_status(by_kid[k["kid"]]), "addedAt": now} for k in reached if k["kid"] not in have]
    entries.extend(learned)
    counted = {e["kid"] for e in entries} - _revoked(entries)
    refused = [k for k in live if k.get("kid") not in counted]
    forced: list[dict[str, Any]] = []
    if force and refused:
        forced = [{**_key(origin, k), **_status(k), "forced": True, "addedAt": now} for k in refused]
        again = {k["kid"] for k in forced}  # a key pinned through a revoked one is re-rooted by hand
        entries[:] = [e for e in entries if e["kid"] not in again] + forced
        refused = []
    _save(origins)
    return {"origin": origin, "keys": [e["kid"] for e in entries if e["kid"] not in _revoked(entries)],
            "added": [k["kid"] for k in learned + forced], "refused": [k.get("kid") for k in refused],
            "revoked": marked, "file": str(trust_file())}


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

    Returns ``{"status": "verified" | "unsigned" | "untrusted", "origin", "kid", "learned"}``. A
    signature from a trusted origin that does not match — or whose key neither is pinned nor is
    reached by endorsements from a pinned key — is always an error; keys learned through the
    signature's chain are pinned (``learned``). ``require`` (default: ``WITAN_VERIFY``) also
    refuses unsigned manifests and origins not trusted yet.
    """
    must = require_default() if require is None else require
    what = f"{manifest.get('project', '?')} v{manifest.get('version', '?')}"
    sig = manifest.get("signature")
    if not isinstance(sig, dict):
        if must:
            raise SignatureError(f"{what} is not signed — only versions an origin published carry a signature")
        return {"status": "unsigned", "origin": None, "kid": None, "learned": []}
    origin = str(sig.get("origin", "")).rstrip("/")
    kid = sig.get("kid")
    entries = trusted().get(origin, [])
    if not entries:
        if must:
            raise SignatureError(f"{what} is signed by {origin}, which is not trusted here — pin its key first: "
                                 f"WITAN_BASE_URL={origin} wtn trust add")
        return {"status": "untrusted", "origin": origin, "kid": kid, "learned": []}
    revoked = _revoked(entries)
    if kid in revoked:
        if any(e["kid"] == kid and e.get("revoked") for e in entries):
            raise SignatureError(f"{what} is signed with key {kid}, which {origin} revoked")
        raise SignatureError(f"{what} is signed with key {kid}, which was pinned through a key {origin} revoked — check "
                             f"the key id with its operator, then: WITAN_BASE_URL={origin} wtn trust add --force")
    known = {e["kid"]: e for e in entries if e["kid"] not in revoked}
    learned: list[dict[str, Any]] = []
    key = known.get(kid)
    if key is None:
        chain = sig.get("chain") if isinstance(sig.get("chain"), list) else []
        learned = _walk(origin, chain, known, revoked, kid, what)
        key = next((k for k in learned if k["kid"] == kid), None)
        if key is None:
            raise SignatureError(f"{what} is signed with key {kid}, which is not one of {origin}'s pinned keys and no "
                                 "endorsement leads to it from one — if the origin re-keyed, check the new key id with "
                                 f"its operator, then: WITAN_BASE_URL={origin} wtn trust add --force")
        # a key the chain passes through was succeeded; the one that signed is in use
        learned = [{**k, "status": "current" if k["kid"] == kid else "retired"} for k in learned]
    try:
        public = base64.b64decode(key["publicKey"])
        signature = base64.b64decode(str(sig.get("sig", "")), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignatureError(f"{what} carries a malformed signature") from exc
    if sig.get("alg") != "Ed25519" or not _ed25519_verify(public, statement(manifest, origin), signature):
        raise SignatureError(f"{what} does not match {origin}'s signature — the manifest was altered or corrupted")
    if learned:
        _pin(origin, learned)
    return {"status": "verified", "origin": origin, "kid": kid, "learned": [k["kid"] for k in learned]}
