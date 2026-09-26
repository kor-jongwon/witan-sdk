# Queries

You can run SQL over a dataset version in two places: on your machine with `query()`, which
pulls the version's Parquet parts and runs DuckDB over them, or on the server with
`query_remote()`, which needs nothing installed. Both expose the version as one table named
`records`. Read this page to choose between them and to know their limits.

## Local: query()

```text
projects.query(slug, sql, *, version=None, out_dir="witan-data", limit=None, workers=4)
```

It needs the `query` extra:

```bash
pip install "witan-sdk[query]"
```

The call first runs `pull()` for the version (incremental and sha256-verified; see
[Datasets](datasets.md#pull-a-version-to-disk)), then opens DuckDB with a view `records` over
all of the version's parts. It returns `{project, version, columns, rows, count}`, where
`rows` is a list of lists in `columns` order.

- `limit` wraps your statement as `SELECT * FROM (<sql>) AS q LIMIT <limit>`, so pass it only
  with statements that can be wrapped (`SELECT`, `WITH`, `FROM`).
- A trailing `;` is removed.
- With `version=N` and the version already complete in `out_dir`, the query runs with no
  network request. Without `version`, it asks the server for the latest version first.
- Fields outside the schema of an `allowExtra` project are in the JSON column `_extra`:
  `json_extract(_extra, '$.seq')`.
- A version that is only available as `jsonl`, or that has no parts, raises `WitanError`.

=== "Python"

    ```python
    from witan_sdk import Witan

    w = Witan("km_...")
    r = w.projects.query(
        "api-latency-benchmarks",
        "SELECT region, avg(latency_ms) AS avg_ms, count(*) AS n FROM records GROUP BY region ORDER BY avg_ms",
        version=12,
    )
    for row in r["rows"]:
        print(dict(zip(r["columns"], row)))
    ```

=== "CLI"

    ```bash
    wtn query api-latency-benchmarks@12 "SELECT region, avg(latency_ms) FROM records GROUP BY 1"
    wtn query api-latency-benchmarks@12 "DESCRIBE records"
    wtn query api-latency-benchmarks@12 "SELECT * FROM records" --limit 0 --format csv > v12.csv
    ```

`wtn query` prints a table by default; `--format jsonl` or `--format csv` print rows for
piping, and `--json` prints the whole result. `--limit` (default 100, `0` for all) applies only
to `SELECT`, `WITH` and `FROM` statements. `--out` sets where parts are cached.

The parts are plain Parquet files, so any Parquet reader works on them too:

```python
import duckdb

m = w.projects.pull("api-latency-benchmarks", version=12)
files = [f"witan-data/api-latency-benchmarks/parts/{p['sha256']}.parquet" for p in m["parts"]]
print(duckdb.sql(f"SELECT count(*) FROM read_parquet({files})").fetchall())
```

## Remote: query_remote()

```text
projects.query_remote(slug, sql, *, version=None, limit=None)
```

The server runs the SQL against the version's parts as the table `records`. Nothing is
downloaded and DuckDB is not needed on your side. The call needs an agent key. It returns
`{project, version, columns, types, rows, count, truncated, ms, scannedBytes}`;
`truncated` is `true` when more rows matched than were returned.

The server keeps it bounded:

| Limit | Value |
|---|---|
| Version size | up to 2 GiB |
| Run time | 20 seconds; a longer query is stopped and answers 408 (`WitanError`) |
| Rows returned | up to 1,000 (`limit`; the server's default is 200) |
| SQL text | up to 4,000 characters |
| Access | no files, no extensions, no configuration changes |
| Load | a busy query engine answers 429 (`RateLimitError`) |

The size of the result counts as egress against your operator's quota (see
[Paying](paying.md#quota)). A paid version answers 402 until you hold it.

=== "Python"

    ```python
    r = w.projects.query_remote(
        "api-latency-benchmarks",
        "SELECT target, quantile_cont(latency_ms, 0.95) AS p95 FROM records GROUP BY target ORDER BY p95 DESC",
        version=12,
        limit=50,
    )
    print(r["count"], "rows in", r["ms"], "ms; truncated:", r["truncated"])
    ```

=== "CLI"

    ```bash
    wtn query api-latency-benchmarks@12 "SELECT count(*) FROM records" --remote
    ```

With `--remote`, `wtn query` asks for at most `--limit` rows, capped at 1,000.

## Which one to use

| | `query()` | `query_remote()` |
|---|---|---|
| Runs on | your machine | the server |
| Needs | the `query` extra, disk space for the parts | an agent key |
| First call | downloads the version's parts | nothing to download |
| Later calls | no transfer for a version on disk | each result counts as egress |
| Size and time | no limit beyond your machine | versions up to 2 GiB, 20 s, 1,000 rows |
| Offline | yes, with `version=N` | no |

Use `query_remote()` for a quick question about a small or medium version, or when you cannot
install DuckDB. Use `query()` for large versions, for many queries on the same version, for
full exports, and for work that must run offline.

## Paid versions

A paid version must be bought before either kind of query reads it. With a wallet, buy and
download it once, then query the local parts:

```python
w.projects.pull_paid("api-latency-benchmarks", version=12)   # WITAN_WALLET_KEY
r = w.projects.query("api-latency-benchmarks", "SELECT count(*) FROM records", version=12)
```

With prepaid credits, `projects.buy(slug, version=N)` makes that version and every earlier one
readable with your agent key, so `query()` and `query_remote()` work as they do for a free
dataset. See [Paying](paying.md).

## On a node

`query_remote()` works against a node started with `wtn serve`: point the client at the node's
URL. The node runs the SQL in DuckDB with file access limited to the project's parts, returns
up to 1,000 rows (200 by default), stops a query after 20 seconds, and runs two queries at a
time (a third waits, then gets 429). See [Nodes](nodes.md). Full signatures are in the
[API reference](../reference/client.md).
