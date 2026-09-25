"""Signed manifests: the Ed25519 verifier, the trust store, and verification in pull, the local
cache and bundles. A test-only signer stands in for the origin. No network."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from witan_sdk import SignatureError, Witan, WitanError
from witan_sdk import ed25519, trust
from witan_sdk.bundle import published_manifest

from test_bundle import SLUG, ProjectFake, members, rewrite
from test_client import manifest_for

# RFC 8032 section 7.1, tests 1 and 2
RFC = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", b"",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", b"\x72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
]
ORIGIN = "https://origin.test"
SEED = bytes(range(32))
OTHER_SEED = bytes(range(32, 64))


# ---- a test-only signer (the SDK itself only verifies) -------------------------

def _encode(pt: tuple[int, int, int, int]) -> bytes:
    zi = pow(pt[2], ed25519._P - 2, ed25519._P)
    x, y = pt[0] * zi % ed25519._P, pt[1] * zi % ed25519._P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _expand(seed: bytes) -> tuple[int, bytes, bytes]:
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little") & ((1 << 254) - 8) | (1 << 254)
    return a, h[32:], _encode(ed25519._mul(a, ed25519._G))


def public(seed: bytes) -> bytes:
    return _expand(seed)[2]


def sign(seed: bytes, msg: bytes) -> bytes:
    a, prefix, pub = _expand(seed)
    r = int.from_bytes(hashlib.sha512(prefix + msg).digest(), "little") % ed25519._L
    big_r = _encode(ed25519._mul(r, ed25519._G))
    k = int.from_bytes(hashlib.sha512(big_r + pub + msg).digest(), "little") % ed25519._L
    return big_r + ((r + k * a) % ed25519._L).to_bytes(32, "little")


def kid(seed: bytes) -> str:
    return hashlib.sha256(public(seed)).hexdigest()[:16]


def keys_doc(seed: bytes = SEED, origin: str = ORIGIN) -> dict:
    return {"origin": origin, "keys": [{"kid": kid(seed), "alg": "Ed25519",
                                        "publicKey": base64.b64encode(public(seed)).decode()}]}


def signed(manifest: dict, seed: bytes = SEED, origin: str = ORIGIN, claim_kid: str | None = None) -> dict:
    sig = sign(seed, trust.statement(manifest, origin))
    return {**manifest, "signature": {"alg": "Ed25519", "kid": claim_kid or kid(seed), "origin": origin,
                                      "sig": base64.b64encode(sig).decode()}}


@pytest.fixture(autouse=True)
def trust_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "trust" / "trust.json"
    monkeypatch.setenv("WITAN_TRUST_FILE", str(path))
    monkeypatch.delenv("WITAN_VERIFY", raising=False)
    return path


# ---- the verifier -----------------------------------------------------------------

@pytest.mark.parametrize("seed,pub,msg,sig", RFC)
def test_rfc8032_vectors_verify_and_the_test_signer_matches(seed: str, pub: str, msg: bytes, sig: str) -> None:
    assert ed25519.verify(bytes.fromhex(pub), msg, bytes.fromhex(sig))
    assert public(bytes.fromhex(seed)).hex() == pub
    assert sign(bytes.fromhex(seed), msg).hex() == sig


def test_verify_rejects_altered_inputs() -> None:
    _, pub_hex, msg, sig_hex = RFC[1]
    pub, sig = bytes.fromhex(pub_hex), bytes.fromhex(sig_hex)
    assert not ed25519.verify(pub, b"\x73", sig)
    assert not ed25519.verify(pub, msg, sig[:10] + bytes([sig[10] ^ 1]) + sig[11:])
    assert not ed25519.verify(pub[:5] + bytes([pub[5] ^ 1]) + pub[6:], msg, sig)
    assert not ed25519.verify(pub, msg, sig[:63])
    assert not ed25519.verify(pub, msg, sig[:32] + ed25519._L.to_bytes(32, "little"))  # s must be < L
    assert not ed25519.verify(b"\xff" * 32, msg, sig)  # not a point


def test_statement_is_the_published_manifest_in_stable_json() -> None:
    m = {"project": "p", "version": 1, "format": "witan-dataset-manifest/1", "urlExpiresAt": "t", "paid": True,
         "parts": [{"sha256": "ab", "bytes": 1, "url": "http://x"}], "signature": {"sig": "..."}}
    assert trust.statement(m, "https://o") == (
        b'{"manifest":{"format":"witan-dataset-manifest/1","parts":[{"bytes":1,"sha256":"ab"}],"project":"p","version":1},'
        b'"origin":"https://o","v":1}')


# ---- the trust store -------------------------------------------------------------

def test_trust_add_list_remove(trust_file: Path) -> None:
    r = trust.add(ORIGIN + "/", keys_doc()["keys"])
    assert r["origin"] == ORIGIN and r["added"] == [kid(SEED)] and r["file"] == str(trust_file)
    assert trust.add(ORIGIN, keys_doc()["keys"])["added"] == []  # already pinned
    assert trust.add(ORIGIN, keys_doc(OTHER_SEED)["keys"])["keys"] == [kid(SEED), kid(OTHER_SEED)]  # a new key joins
    assert list(trust.trusted()) == [ORIGIN]
    assert trust.remove(ORIGIN) and not trust.remove(ORIGIN) and trust.trusted() == {}


def test_trust_refuses_keys_it_cannot_use() -> None:
    with pytest.raises(WitanError):
        trust.add(ORIGIN, [{"kid": "k", "alg": "Ed25519", "publicKey": "not base64!"}])
    with pytest.raises(WitanError):
        trust.add(ORIGIN, [{"kid": "k", "alg": "RS256", "publicKey": base64.b64encode(b"x" * 32).decode()}])
    with pytest.raises(WitanError):
        trust.add(ORIGIN, [])
    assert trust.trusted() == {}


# ---- check ----------------------------------------------------------------------

def test_check_reports_unsigned_and_untrusted_and_require_refuses_both(monkeypatch: pytest.MonkeyPatch) -> None:
    m = manifest_for(110)
    assert trust.check(m)["status"] == "unsigned"
    assert trust.check(signed(m)) == {"status": "untrusted", "origin": ORIGIN, "kid": kid(SEED)}
    for bad in (m, signed(m)):
        with pytest.raises(SignatureError):
            trust.check(bad, require=True)
    monkeypatch.setenv("WITAN_VERIFY", "1")
    with pytest.raises(SignatureError):
        trust.check(m)
    assert trust.check(m, require=False)["status"] == "unsigned"


def test_check_verifies_pinned_origins_and_refuses_any_change() -> None:
    trust.add(ORIGIN, keys_doc()["keys"])
    m = signed(manifest_for(110))
    assert trust.check(m, require=True) == {"status": "verified", "origin": ORIGIN, "kid": kid(SEED)}
    fresh = {**m, "urlExpiresAt": "2030-01-01T00:00:00Z", "parts": [{**p, "url": "http://elsewhere/p"} for p in m["parts"]]}
    assert trust.check(fresh)["status"] == "verified"  # URLs and expiry are per request, not signed
    changes = [
        {**m, "totals": {**m["totals"], "records": 4}},
        {**m, "parts": m["parts"][:1]},
        {**m, "parts": [{**m["parts"][0], "sha256": "0" * 64}, m["parts"][1]]},
        {**m, "version": 111},
        {**m, "signature": {**m["signature"], "origin": "https://other.test"}},  # a signature is bound to its origin
    ]
    trust.add("https://other.test", keys_doc()["keys"])
    for changed in changes:
        with pytest.raises(SignatureError):
            trust.check(changed)  # not only with require: a trusted origin's mismatch is always an error


def test_check_refuses_a_key_the_origin_never_published() -> None:
    trust.add(ORIGIN, keys_doc()["keys"])
    with pytest.raises(SignatureError, match="not one of"):
        trust.check(signed(manifest_for(110), seed=OTHER_SEED))
    with pytest.raises(SignatureError):  # someone else's key claiming the pinned kid
        trust.check(signed(manifest_for(110), seed=OTHER_SEED, claim_kid=kid(SEED)))


def test_local_and_republished_forms_still_verify() -> None:
    trust.add(ORIGIN, keys_doc()["keys"])
    m = signed(manifest_for(110))
    local = {**{k: v for k, v in m.items() if k != "urlExpiresAt"},
             "parts": [{k: v for k, v in p.items() if k != "url"} for p in m["parts"]],
             "format": "parquet", "count": 3, "file": "parts/<sha256>.parquet", "downloaded": 2,
             "pulledAt": "2026-09-25T00:00:00+00:00", "source": "http://node.test", "verified": "verified"}
    assert trust.check(local)["status"] == "verified"
    assert trust.check(published_manifest(local))["status"] == "verified"  # what a node serves


# ---- through the client -------------------------------------------------------------

class SignedFake(ProjectFake):
    """The shared fake as a signing origin: /.well-known/witan-keys and signed manifests."""

    def __init__(self) -> None:
        super().__init__()
        self.tamper = False
        self.unsigned = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/.well-known/witan-keys":
            self.calls.append(request)
            return httpx.Response(200, json=keys_doc())
        if path == f"/projects/{SLUG}/manifest":
            self.calls.append(request)
            m = manifest_for(int(request.url.params.get("version", 110)))
            if not self.unsigned:
                m = signed(m)
            if self.tamper:
                m["totals"] = {**m["totals"], "contributions": 999}
            return httpx.Response(200, json=m)
        return super().__call__(request)


@pytest.fixture
def fake() -> SignedFake:
    return SignedFake()


@pytest.fixture
def w(fake: SignedFake) -> Witan:
    return Witan("km_test", base_url="http://api.test", transport=httpx.MockTransport(fake))


def downloads(fake: SignedFake) -> int:
    return sum(1 for c in fake.calls if c.url.host == "parts.test")


def test_client_trust_pins_the_published_keys(w: Witan) -> None:
    r = w.trust()
    assert r["origin"] == ORIGIN and r["from"] == "http://api.test" and r["added"] == [kid(SEED)]
    assert list(w.trusted()) == [ORIGIN] and w.untrust(ORIGIN) and w.trusted() == {}


def test_pull_records_the_signature_status(w: Witan, fake: SignedFake, tmp_path: Path) -> None:
    assert w.projects.pull(SLUG, tmp_path / "a")["verified"] == "untrusted"
    w.trust()
    m = w.projects.pull(SLUG, tmp_path / "b", verify=True)
    assert m["verified"] == "verified" and m["signature"]["origin"] == ORIGIN
    on_disk = json.loads((tmp_path / "b" / SLUG / "v110" / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk["verified"] == "verified" and "signature" in on_disk


def test_pull_checks_before_any_part_is_fetched(w: Witan, fake: SignedFake, tmp_path: Path) -> None:
    w.trust()
    fake.tamper = True
    with pytest.raises(SignatureError):
        w.projects.pull(SLUG, tmp_path)
    assert downloads(fake) == 0 and not (tmp_path / SLUG / "v110").exists()


def test_verify_refuses_unsigned_versions(w: Witan, fake: SignedFake, tmp_path: Path) -> None:
    w.trust()
    fake.unsigned = True
    with pytest.raises(SignatureError, match="not signed"):
        w.projects.pull(SLUG, tmp_path, verify=True)
    assert w.projects.pull(SLUG, tmp_path)["verified"] == "unsigned"  # without verify it is only reported


def test_the_local_copy_is_rechecked_offline(w: Witan, fake: SignedFake, tmp_path: Path) -> None:
    w.trust()
    w.projects.pull(SLUG, tmp_path)
    n = len(fake.calls)
    assert w.projects.pull(SLUG, tmp_path, version=110, verify=True)["verified"] == "verified"
    assert len(fake.calls) == n  # cached: no request
    path = tmp_path / SLUG / "v110" / "manifest.json"
    m = json.loads(path.read_text(encoding="utf-8"))
    m["parent"] = 1
    path.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(SignatureError):
        w.projects.pull(SLUG, tmp_path, version=110)


def test_a_bundle_carries_the_origin_signature(w: Witan, tmp_path: Path) -> None:
    w.trust()
    path = tmp_path / "obs.witan"
    w.projects.save(SLUG, path, version=110, cache_dir=tmp_path / "cache")
    r = w.projects.load(path, tmp_path / "out", verify=True)
    assert r["signature"] == "verified" and r["signedBy"] == ORIGIN
    kept = json.loads((tmp_path / "out" / SLUG / "v110" / "manifest.json").read_text(encoding="utf-8"))
    assert kept["verified"] == "verified"
    assert w.projects.load(path, check=True)["signature"] == "verified"


def test_an_altered_bundle_manifest_is_refused_and_nothing_is_kept(w: Witan, tmp_path: Path) -> None:
    w.trust()
    path = tmp_path / "obs.witan"
    w.projects.save(SLUG, path, version=110, cache_dir=tmp_path / "cache")
    mem = members(path)
    m = json.loads(mem["manifest.json"])
    m["createdAt"] = "2020-01-01T00:00:00Z"  # consistent with its parts, header re-hashed: only the signature notices
    new_manifest = json.dumps(m).encode()
    header = {**json.loads(mem["witan-bundle.json"]), "manifestSha256": hashlib.sha256(new_manifest).hexdigest()}
    bad = tmp_path / "altered.witan"
    rewrite(path, bad, lambda name, data: (name, {"manifest.json": new_manifest,
                                                   "witan-bundle.json": json.dumps(header).encode()}.get(name, data)))
    with pytest.raises(SignatureError):
        w.projects.load(bad, tmp_path / "out")
    assert not (tmp_path / "out" / SLUG / "parts").exists() or not any((tmp_path / "out" / SLUG / "parts").iterdir())
    assert not (tmp_path / "out" / SLUG / "v110").exists()


def test_unsigned_bundles_load_unless_verify_is_asked(w: Witan, fake: SignedFake, tmp_path: Path) -> None:
    fake.unsigned = True
    path = tmp_path / "obs.witan"
    w.projects.save(SLUG, path, version=110, cache_dir=tmp_path / "cache")
    assert w.projects.load(path, tmp_path / "out")["signature"] == "unsigned"
    with pytest.raises(SignatureError):
        w.projects.load(path, tmp_path / "out2", verify=True)
