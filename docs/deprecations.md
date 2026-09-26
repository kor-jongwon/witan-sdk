# Versions and deprecations

## How versions are numbered

`witan-sdk` is `0.x` and follows [semantic versioning](https://semver.org/) as it applies before 1.0:

| Release | Example | What it may contain |
|---|---|---|
| patch | 0.17.0 → 0.17.1 | fixes and documentation; nothing you call behaves differently on purpose |
| minor | 0.17.x → 0.18.0 | new calls and options; changes of behaviour, each listed under **Changed** in the [release notes](changelog.md) with what to do |

Nothing is removed without a deprecation first (from 0.17.0 on):

1. A call, parameter or command is **deprecated** in a minor release. It keeps working and warns.
2. It stays for **at least two more minor releases and at least 30 days**, whichever is longer.
3. It is **removed** in a minor release, listed under **Removed**.

## What a deprecation looks like

**In the SDK.** A deprecated call raises a `WitanDeprecationWarning` (a `FutureWarning`, so Python shows
it by default) that names the replacement and the release it goes away in.

**From the server.** When an API route the SDK calls is scheduled for removal, the server answers it with
a `Deprecation` header ([RFC 9745](https://www.rfc-editor.org/rfc/rfc9745)), usually with `Sunset`
([RFC 8594](https://www.rfc-editor.org/rfc/rfc8594)) and a `Link: <…>; rel="deprecation"` to the
migration note. From 0.17.0 the SDK turns that into the same warning, once per route per process — so an
agent's logs say what to change before anything breaks. `wtn` prints it on stderr.

Fail a CI run on either kind:

```python
import warnings
from witan_sdk import WitanDeprecationWarning

warnings.simplefilter("error", WitanDeprecationWarning)
```

```bash
python -W error::FutureWarning -m pytest     # or narrower, with the filter above in conftest.py
```

## Deprecated now

| What | Deprecated in | Removed in | Use instead |
|---|---|---|---|
| — | — | — | Nothing is deprecated in this version. |

## Removed so far

Nothing has been removed.

## Behaviour changes worth knowing

The release notes list every change; these are the ones most likely to affect code written for an earlier version:

| Version | Change |
|---|---|
| 0.17.0 | Opening a dispute needs the paying wallet's signature (`dispute(..., private_key=)` or `WITAN_WALLET_KEY`). Wallet purchases refuse to sign above a price cap and outside the allowed networks. `wtn trust add` refuses keys published for another origin than `WITAN_BASE_URL` (`--origin` for a proxy). |
| 0.14.0 | `wtn trust add` on an origin that is already pinned only adds keys the pinned ones endorse; `--force` re-pins by hand. |
| 0.5.0 | Paid versions arrive as a manifest of Parquet parts, not an inline page of records. |
| 0.2.0 | `pull` writes Parquet parts; `--format jsonl` keeps the old behaviour. |

## Python versions

Python 3.10 to 3.13; CI runs the tests on 3.10 and 3.12 before every release. Support for a Python version
ends only in a minor release, after that version's upstream end of life, and is listed under **Removed**.

## The server

The public origin always runs the current platform. When an SDK feature needs something new on the server,
its release note says so. The SDK sends `User-Agent: witan-sdk/<version>`, so the server can tell which
versions still call a route before it is deprecated.
