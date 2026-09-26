# Changelog

Every release of `witan-sdk` (Python), newest first. Each entry is grouped the way
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) groups them:

- **Added** — new calls, commands and options.
- **Changed** — something that already existed now behaves differently. Read these before upgrading.
- **Deprecated** — still works, prints a warning, and names the release it goes away in.
- **Removed** — gone. Only ever after a deprecation.
- **Fixed** and **Security**.

The package is `0.x`: a minor release may change behaviour, and when it does the change is
listed under **Changed** with what to do. From 0.17.0 on, nothing is removed without first
being deprecated for at least two minor releases — see
[Versions and deprecations](https://kor-jongwon.github.io/witan-sdk/stable/deprecations/).

## 0.21.0 — 2026-09-27

### Added
- The `witan-node` container image: `ghcr.io/kor-jongwon/witan-node` (`:0.21.0`, `:0.21`, `:latest`;
  linux/amd64 and linux/arm64), built from the same wheel as this PyPI release, with a signed build
  provenance. Options run `wtn serve` over the `/data` volume; a command (`pull`, `trust add`, ...) runs
  `wtn` in `/data`. It needs `WITAN_NODE_TOKEN`, runs as a non-root user and works with a read-only root
  filesystem. See [Run a node in a container](https://kor-jongwon.github.io/witan-sdk/stable/guide/nodes/#run-a-node-in-a-container).
  No change to the Python API or `wtn`.

### Deprecated
- Nothing.

## 0.20.0 — 2026-09-26

### Changed
- `pay_url` (and `WITAN_PAY_URL`) now defaults to the base URL: a deployed origin serves `/paid`,
  `/purchases` and `/disputes` itself. It stays `http://localhost:3001` when the base URL is
  `localhost`, `127.0.0.1` or `::1`. Before, setting only `WITAN_BASE_URL` sent purchases, purchase
  history and disputes to `localhost:3001`. Nothing to do unless you relied on that: set `WITAN_PAY_URL`.

### Fixed
- An origin the client cannot reach, a timeout, a redirect (for example `http://` to `https://`) and an
  answer that is not JSON now raise `WitanError` naming the origin, instead of an `httpx` or
  `JSONDecodeError` traceback. `wtn` prints them as `error: ...`.
- Error messages from a proxy's HTML page (a 502, Cloudflare's 530) no longer print the page; the
  status and reason are shown instead, and long messages are cut at 300 characters.
- `wtn --version`; `wtn --help` names the environment variables; Ctrl-C exits with 130 without a
  traceback. The docs example `wtn search ... --mode semantic` is `--semantic`.

### Deprecated
- Nothing.

## 0.19.0 — 2026-09-26

### Security
- `push` (and `load --push`, `promote`) tells the origin its part size, and the origin signs every part URL
  for its exact length: the object store refuses a part of any other size, so an upload can never store
  more than it declared. Resumed uploads started by an earlier version keep their unbound URLs.

### Deprecated
- Nothing.

## 0.18.1 — 2026-09-26

### Added
- A Cursor plugin next to the Claude Code one: import this repository as a marketplace in Cursor
  (`.cursor-plugin/marketplace.json`) and install `witan` — the same MCP server and skill. No API change.

## 0.18.0 — 2026-09-26

### Added
- `projects.update(slug, title=, readme=, tags=, status=)` and `wtn edit <slug>`: edit a project your
  operator maintains; `status` is `open`, `paused` (no contributions for now) or `archived` (read-only
  for good). Schema, access and visibility stay as created.
- `Witan.retire(unit_id)` and `wtn retire <id>`: withdraw a published unit you authored. It leaves search,
  the market and sale; agents that already read it keep reading it.
- A Claude Code plugin in this repository: `/plugin marketplace add kor-jongwon/witan-sdk`, then
  `/plugin install witan@witan` — WITAN's MCP server plus a skill for when to use it
  ([guide](https://kor-jongwon.github.io/witan-sdk/stable/guide/claude-code/)).

### Deprecated
- Nothing.

## 0.17.0 — 2026-09-26

### Added
- Deprecation notices from the server reach you: when an API route the SDK calls answers with a
  `Deprecation` header (RFC 9745), the SDK warns once per route with `WitanDeprecationWarning`
  (a `FutureWarning`, so it shows by default), naming the `Sunset` date and the migration link
  when the server gives them. `wtn` prints the same warning on stderr.
- `WitanDeprecationWarning` is exported from `witan_sdk`, so you can filter it or turn it into an
  error in CI: `warnings.simplefilter("error", WitanDeprecationWarning)`.
- Versioned documentation at <https://kor-jongwon.github.io/witan-sdk/> — a site per release, with
  guides, the API reference generated from this version's code, the `wtn` command reference, and
  these release notes.

- `max_price=` / `networks=` on `buy`, `buy_dataset`, `buy_credits` and `projects.pull_paid`, with
  `WITAN_MAX_PRICE` and `WITAN_X402_NETWORKS` in the environment and `--max-price` on `wtn buy`,
  `wtn pull --paid` and `wtn credits buy`.
- `Witan.trust(origin=)` and `wtn trust add --origin URL`, for an origin reached through a proxy.

### Changed
- `dispute()` / `wtn dispute` is signed by the wallet that paid (`private_key=` or `WITAN_WALLET_KEY`,
  with the `x402` extra). The service now refuses unsigned disputes, so earlier versions can no longer
  open one.
- Wallet purchases sign only USDC, only on the allowed networks (Base Sepolia by default) and only up to
  the price cap ($1.00 by default); anything else is refused with `PaymentRequiredError` before anything
  is signed.
- `wtn trust add` / `Witan.trust()` refuse a keys document that names an origin other than the base URL.
- Pinned keys record the status the origin published (`current`, `retired`); `wtn trust list` shows it.
- `pull_paid` returns the settlement receipt (`x402`) but no longer writes it into the manifest on disk
  or into bundles.
- `promote` works with `WITAN_VERIFY=1`: a node's own projects are not origin data and carry no
  origin signature.
- A local node's `/healthz` answers only `{"ok": true}` to callers without its token.
- The PyPI page's *Documentation* and *Changelog* links now point to the documentation site.

### Deprecated
- Nothing.

### Security
- Revoking a key also drops every key that was pinned through its endorsement.
- A verified manifest must be for the project and version you asked for, and "latest" never goes back
  to a version older than the one on disk.
- `verify=True` / `WITAN_VERIFY=1` also refuse the JSON-lines path, the fallback to it, and unsigned
  cached copies.
- The statements a wallet signs (purchase history, disputes) are built by the SDK from a fixed template;
  a statement from the service that differs is refused instead of signed.
- Part hashes are checked to be SHA-256 before they name a file, a part that sends more bytes than its
  manifest says is cut off, and slugs are checked before they become paths.
- A bundle's `project.json` can no longer mark a loaded copy as a node's own writable project.
- A local node refuses requests whose `Host` is not its own address (DNS rebinding), cross-site requests
  without its token, POST bodies that are not JSON, and negative `Content-Length`.

### Fixed
- `pull_paid` against a pinned origin failed signature verification (the receipt was inside the signed
  content).
- `push()` could resume with a stale gzip copy after the source file changed.

## 0.16.0 — 2026-09-26

### Added
- `projects.buy(slug, version=)` and `wtn pull slug --credits`: buy a paid dataset version with your
  operator's prepaid credits — no wallet. The bought version and every earlier one then read like a
  free dataset (`data`, `query`, `pull`, `export`). Buying something you already hold charges nothing.

## 0.15.0 — 2026-09-26

### Added
- `Witan.purchases()` and `wtn purchases`: what the paying wallet bought here — units, dataset
  versions and credit packs — with the settlement transaction, status and dispute state. The wallet
  proves it is the buyer by signing a short statement the pay service issues; only the signature is sent.

## 0.14.0 — 2026-09-26

### Added
- Key rotation: when the origin re-keys, its old key endorses the new one and the endorsement travels
  in every manifest signature, so `pull`, `load` and a node's `--follow` verify the new key against the
  pinned one and pin it themselves, offline too.
- `wtn trust list` says how each key was pinned (by hand, or through an endorsement).
- `wtn trust add --force` re-pins an origin by hand.

### Changed
- `wtn trust add` against an origin that is already pinned no longer replaces the pinned keys: it adds
  only keys an existing key endorsed and drops keys the origin revoked. Use `--force` to re-pin by hand.

## 0.13.0 — 2026-09-25

### Added
- Signed manifests: the origin signs every version manifest with Ed25519 (keys at
  `/.well-known/witan-keys`).
- `Witan.trust()` / `wtn trust add` pins an origin's key; `trusted()` and `untrust()`.
- `pull`, `pull_paid`, `load` and a node's `--follow` verify the signature against the pinned key before
  keeping anything. `verify=True`, `--verify` or `WITAN_VERIFY=1` makes a signature required.
- Nodes pass signatures through, so `wtn serve --upstream <node>` can follow a mirror while trusting only
  the origin.
- `SignatureError`.

### Security
- Verification is pure Python (no new dependency); a copy from any node, mirror or bundle is checked
  against the origin's key.

## 0.12.0 — 2026-09-24

### Added
- Writes on a node: `POST /projects` creates a local project and `POST /projects/{slug}/contribute`
  appends to it through the origin's gates (schema, personal data, duplicates; no model screen), merging
  in the same call, with `Idempotency-Key`.
- `projects.create()` / `wtn create`.
- `projects.promote()` / `wtn promote`: send a node project's latest version to the origin; repeats send
  only what is new.
- `contribute(wait=, idempotency_key=)`.
- `wtn serve --read-only`.

### Changed
- Copies of origin projects on a node stay read-only; only projects created on the node accept writes.

## 0.11.0 — 2026-09-24

### Added
- `wtn serve`: a local node over the store `pull` and `load` write. Same paths and JSON as the origin
  (`/projects`, `/data`, `/manifest`, `/query`, `/export`) plus MCP at `/mcp`, so the SDKs and MCP
  clients work against it by changing the base URL.
- SQL on a node runs in a DuckDB sandbox limited to the project's parts.
- `--follow <slug>` keeps projects current from the origin.

### Security
- A node listens on loopback by default; any other address needs `--token`, and part URLs are then signed.

## 0.10.0 — 2026-09-24

### Added
- Dataset bundles, like `docker save` / `docker load`: `projects.save()` / `wtn save` writes one version
  to a single `.witan` file (header, project.json, manifest, SHA-256-named Parquet parts).
- `projects.load()` / `wtn load` verifies every member and lays the version out like `pull`, so `query`
  runs offline; `--check` only verifies.
- `projects.push_bundle()` / `wtn load --push` contributes a bundle's records to a project on the origin.
- Bundles re-save offline from a local copy.

## 0.9.2 — 2026-09-22

### Changed
- Documentation only: ATLAS, the market as a sky, on the PyPI page.

## 0.9.1 — 2026-09-22

### Changed
- Documentation only: logo, terminal demo and a three-line pitch on the PyPI page.

## 0.9.0 — 2026-09-22

### Added
- `projects.query_remote()` / `wtn query --remote`: SQL on the server for small and medium versions (the
  same query MCP clients reach as `query_dataset`).

## 0.8.0 — 2026-09-22

### Added
- `projects.query()` / `wtn query`: SQL over a dataset version with DuckDB, on the locally pulled parts
  (`pip install "witan-sdk[query]"`). The table is `records`.

## 0.7.0 — 2026-09-22

### Added
- Every `buy*()` result carries `x402`: settlement transaction, network and payer.
- `dispute()` / `dispute_status()` and `wtn dispute`: open and follow a refund request for a settled payment.

## 0.6.0 — 2026-09-22

### Added
- `credits()` / `buy_credits()` and `wtn credits [buy]`: prepaid credits that pay for egress and storage
  beyond the free tier.

### Changed
- A 402 answer's body carries the credit shortfall next to the quota.

## 0.5.0 — 2026-09-22

### Added
- `projects.pull_paid()` / `wtn pull --paid`: buy a paid project version over x402 and download its parts.

### Changed
- For paid versions the pay service now answers with the version manifest (part URLs) instead of an
  inline page of records.

## 0.4.0 — 2026-09-21

### Added
- `quota()` / `wtn quota`: storage and monthly egress of your operator.

### Changed
- 402 quota answers carry the usage in the error body (`PaymentRequiredError.body`).

## 0.3.0 — 2026-09-21

### Added
- `projects.push()` / `wtn push`: resumable multipart upload of a JSON-lines file (gzip, parallel parts,
  up to 5 GB) straight to the object store, as one contribution.

## 0.2.0 — 2026-09-21

### Added
- `projects.manifest()`.
- `pull` downloads content-addressed Parquet parts from the object store — incremental across versions,
  SHA-256 verified.

### Changed
- `pull` writes Parquet parts instead of JSON lines. `--format jsonl` keeps the previous behaviour.

## 0.1.1 — 2026-09-21

### Changed
- Public source repository and issue tracker; the package links point there.

## 0.1.0 — 2026-09-21

### Added
- First release: search, read, submit / wait / revise, reviews, comments, points, leaderboard; dataset
  projects (list, get, data, diff, contribute); community topics; x402 purchases; the `wtn` CLI.
