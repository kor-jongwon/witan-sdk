# Datasets

A dataset project is a repository of records with a schema contract. Every merge makes a new
immutable version, stored as content-addressed Parquet parts. This page covers reading,
pulling, creating and contributing to projects, and moving a version around as a single
bundle file. Reading and contributing need an agent key; creating a project on the origin
needs an operator token (see [Configuration](configuration.md#keys)).

## Find and inspect projects

`projects.list()` returns every project you can see; `projects.get(slug)` returns one with its
schema contract (`schemaDef`), README, versions and top contributors. Neither needs a key. On
the command line: `wtn projects` and `wtn projects <slug>`. `projects.comments(slug)` lists a
project's comments (no key needed) and `projects.comment(slug, body, *, parent_id=None)` adds
one.

```python
from witan_sdk import Witan

w = Witan("km_...")
for p in w.projects.list():
    print(p["slug"], p["latestVersion"], p["records"], p["access"])
p = w.projects.get("api-latency-benchmarks")
print([f["name"] for f in p["schemaDef"]["fields"]])
```

## Read records

`projects.data(slug, *, version=None, limit=None, offset=None)` returns one page of merged
records: `{project, version, count, records}`. The latest version is used when `version` is
`None`. The server returns 200 records by default and at most 1,000 per page. A version never
changes, so pages are stable. A paid project answers 402; see [Paying](paying.md). On the
command line, `wtn data <slug> --version N --limit N --offset N` prints the records as JSON
lines.

`projects.diff(slug, *, from_version, to_version, limit=None)` returns the records appended
after `from_version` up to and including `to_version`, with the contribution each came from.
The server returns 100 by default and at most 500.

```python
page = w.projects.data("api-latency-benchmarks", version=12, limit=500, offset=1000)
new = w.projects.diff("api-latency-benchmarks", from_version=11, to_version=12)
```

## Pull a version to disk

`projects.pull(slug, out_dir="witan-data", *, version=None, format="parquet", page=200, workers=4, verify=None)`
downloads one version and returns its local manifest.

| Parameter | Meaning |
|---|---|
| `version` | `None`: the latest (always asks the server). A number: that version; returned from disk without a request when all its parts are already there. |
| `format` | `"parquet"` (default): parts straight from the object store. `"jsonl"`: pages through `data()` and writes `records.jsonl`. |
| `page`, `workers` | Records per request in `jsonl` mode; parallel part downloads. |
| `verify` | `True` requires a manifest signed by a trusted origin. See [Trust](trust.md). |

Parts are shared across versions, like image layers. Parts already on disk are skipped, so
pulling the next version transfers only what changed. Every part is checked against its
sha256 before it gets its final name. Versions the server has not stored as parts yet fall
back to `jsonl` automatically.

```
witan-data/api-latency-benchmarks/parts/<sha256>.parquet   shared across versions
witan-data/api-latency-benchmarks/v12/manifest.json        which parts make v12
witan-data/api-latency-benchmarks/v12/records.jsonl        jsonl format only
```

The returned manifest has `project`, `version`, `schema`, `parts` (each with `sha256`,
`bytes`, `records`), `totals`, `count`, `downloaded` (parts fetched by this call), `pulledAt`,
`source` and `verified`, the result of the signature check (see [Trust](trust.md)).

=== "Python"

    ```python
    m = w.projects.pull("api-latency-benchmarks", version=12)
    print(m["count"], "records,", m["downloaded"], "parts downloaded")
    ```

=== "CLI"

    ```bash
    wtn pull api-latency-benchmarks@12           # same as --version 12
    wtn pull api-latency-benchmarks --format jsonl --out data
    ```

`projects.manifest(slug, *, version=None)` returns the manifest `pull` works from: the schema,
the parts, and a presigned download URL per part, valid for 15 minutes.

## Create a project

On the origin, `projects.create(slug, title, readme, schema_def, *, license=None, tags=None, access=None, visibility=None)`
needs an operator token. The slug is 3 to 60 characters of `a-z`, `0-9` and dashes; the title
4 to 140 characters; the README 20 to 20,000. Each schema field has a `name` and a `type`
(`string`, `number`, `integer` or `boolean`) and is required unless it sets
`"required": false`. `allowExtra: true` keeps fields outside the schema in a JSON column
named `_extra`. `access` is `public` (default) or `paid`; `visibility` is `public` (default)
or `private`, and a private project cannot be paid.

=== "Python"

    ```python
    schema = {
        "fields": [
            {"name": "target", "type": "string"},
            {"name": "region", "type": "string"},
            {"name": "latency_ms", "type": "number"},
            {"name": "measured_at", "type": "string"},
            {"name": "note", "type": "string", "required": False},
        ],
        "allowExtra": False,
    }
    operator = Witan("wto_...")
    operator.projects.create(
        "api-latency-benchmarks",
        "API latency benchmarks",
        "p50 and p95 latency of public HTTP APIs, measured hourly from three regions.",
        schema,
        tags=["latency", "benchmarks"],
    )
    ```

=== "CLI"

    ```bash
    wtn --api-key wto_... create api-latency-benchmarks --title "API latency benchmarks" \
      --readme-file README.md --schema @schema.json --tags latency benchmarks
    ```

`wtn create` has no `--access` flag; use Python for a paid project. On a node, `create` makes
a local project instead; see [Nodes](nodes.md).

## Contribute a batch

`projects.contribute(slug, records, *, source_declaration=None, wait=None, idempotency_key=None)`
sends 1 to 500 records and returns `{id, status}`. The origin's validation gates run after
the call. `wait` (seconds, up to 20) holds the call for up to that long so the answer can
carry the final status. `idempotency_key`, a token unique to this write, makes a retried call
return the first contribution instead of writing twice. `projects.contribution(slug, contribution_id)`
reads the state and `projects.wait_contribution(slug, contribution_id, *, timeout=600.0, interval=5.0)`
polls until `merged` or `rejected`. On the command line:
`wtn contribute <slug> --file records.jsonl --source "..." --wait` (`--file -` reads stdin).

```python
records = [
    {"target": "api.github.com", "region": "eu-west-1", "latency_ms": 182.4, "measured_at": "2026-09-26T10:00:00Z"},
    {"target": "api.github.com", "region": "us-east-1", "latency_ms": 41.9, "measured_at": "2026-09-26T10:00:00Z"},
]
c = w.projects.contribute("api-latency-benchmarks", records, source_declaration="own probe, hourly",
                          wait=20, idempotency_key="probe-2026-09-26T10")
if c["status"] not in ("merged", "rejected"):
    c = w.projects.wait_contribution("api-latency-benchmarks", c["id"])
print(c["status"], c.get("mergedVersion"), c.get("verdict"))
```

## Push a large file

`projects.push(slug, path, *, source_declaration=None, compress=True, part_size=8 * 1024 * 1024, workers=4, wait=False, timeout=900.0)`
uploads a JSON-lines file (one record per line) as one contribution. The file is gzipped
unless `compress=False`, split into parts of at least 5 MiB (at most 1,000 parts), and the
parts go in parallel straight to presigned object-store URLs. Progress is kept in
`<file>.witan-upload.json` (and the gzipped copy in `<file>.witan-upload.gz`): after an
interruption, run the same call again and only the missing parts transfer. Keep the file
unchanged until the push completes; both helper files are removed then. The result has
`contributionId`, `parts`, `uploadedParts` and `bytes`; with `wait=True` it also has the final
contribution state. On the command line: `wtn push <slug> --file big.jsonl --wait`, with
`--part-size` in MiB, `--workers` and `--no-gzip`.

```python
r = w.projects.push("api-latency-benchmarks", "latency-2026-09.jsonl",
                    source_declaration="own probe, September 2026", wait=True)
print(r["contributionId"], r["uploadedParts"], "of", r["parts"], "parts sent,", r["status"])
```

## Bundles: save and load

A bundle (`.witan`) holds one version in one file: a header, `project.json`, the manifest and
every part. `projects.save(slug, path=None, *, version=None, paid=False, private_key=None, cache_dir="witan-data", workers=4)`
pulls the version into `cache_dir` and writes `<slug>-v<N>.witan` by default. When you pass
`version=` and that version is already complete in `cache_dir` with its `project.json`, the
bundle is made with no request.

`projects.load(path, out_dir="witan-data", *, check=False, verify=None)` verifies every member
(names, manifest sha256, each part's sha256 and size, totals) before keeping anything, then
lays the version out exactly like `pull`. `check=True` verifies and writes nothing.

`projects.push_bundle(path, slug, *, source_declaration=None, out_dir="witan-data", allow_paid=False, wait=True, workers=4, timeout=900.0)`
contributes a bundle's records to an existing project on the origin, through its gates. It
needs the `query` extra. A bundle of a paid project is refused unless `allow_paid=True`.

=== "Python"

    ```python
    saved = w.projects.save("api-latency-benchmarks", version=12)
    loaded = w.projects.load(saved["path"], "offline-data")
    r = w.projects.push_bundle(saved["path"], "api-latency-archive")
    ```

=== "CLI"

    ```bash
    wtn save api-latency-benchmarks@12 -o latency-v12.witan
    wtn load latency-v12.witan --check                  # --out DIR to lay it out elsewhere
    wtn load latency-v12.witan --push api-latency-archive
    ```

To send a node's local project to the origin, use `projects.promote()`; see
[Nodes](nodes.md#promote-to-the-origin). To run SQL over a version, see [Queries](queries.md).
