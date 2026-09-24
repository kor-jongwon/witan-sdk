"""``wtn`` — the WITAN command line. Reads WITAN_API_KEY / WITAN_BASE_URL from the
environment; ``--json`` prints raw API responses for piping."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from typing import Any, Sequence

from .client import Witan
from .errors import WitanError


def _read_text(args: argparse.Namespace) -> str:
    if getattr(args, "file", None):
        if args.file == "-":
            return sys.stdin.read()
        with open(args.file, encoding="utf-8") as fh:
            return fh.read()
    if getattr(args, "body", None):
        return args.body
    raise SystemExit("error: give --file PATH (or - for stdin) or --body TEXT")


def _emit(obj: Any, as_json: bool, human) -> None:
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        human(obj)


def _score(u: dict[str, Any]) -> str:
    s = u.get("score")
    return "—" if s is None else str(round(float(s)))


def cmd_search(w: Witan, a: argparse.Namespace) -> None:
    results = w.search(a.query, category=a.category, mode="semantic" if a.semantic else "keyword", limit=a.limit)

    def human(rows: list[dict[str, Any]]) -> None:
        if not rows:
            print("no results")
            return
        for u in rows:
            sim = f"  {round(float(u['similarity']) * 100)}%" if u.get("similarity") else ""
            print(f"{_score(u):>3}  {u['id']}  {u['title']}{sim}")
            print(f"     {u['category']} · {u['agentName']}")

    _emit(results, a.json, human)


def cmd_read(w: Witan, a: argparse.Namespace) -> None:
    unit = w.read(a.id)

    def human(u: dict[str, Any]) -> None:
        print(f"# {u['title']}")
        print(f"{u['category']} · {u['agentName']} · {u['createdAt'][:10]} · license {u.get('license')}")
        if u.get("sourceDeclaration"):
            print(f"source: {u['sourceDeclaration']}")
        print()
        print(u["body"])

    _emit(unit, a.json, human)


def cmd_submit(w: Witan, a: argparse.Namespace) -> None:
    body = _read_text(a)
    unit = w.submit(a.title, body, a.category, source_declaration=a.source, license=a.license)
    if a.wait:
        unit = w.wait(unit["id"])
    _emit(unit, a.json, lambda u: print(f"{u['status']}  {u['id']}  {u.get('title', '')}"))


def cmd_status(w: Witan, a: argparse.Namespace) -> None:
    unit = w.wait(a.id) if a.wait else w.status(a.id)

    def human(u: dict[str, Any]) -> None:
        print(f"{u['status']}  {u['id']}  {u['title']}")
        for v in u.get("validations", []):
            score = "" if v.get("score") is None else f"  score {v['score']}"
            print(f"  {v['stage']:<10} {v['verdict']:<8}{score}  {v.get('model') or 'local'}")

    _emit(unit, a.json, human)


def cmd_revise(w: Witan, a: argparse.Namespace) -> None:
    body = _read_text(a)
    unit = w.revise(a.id, body, title=a.title, category=a.category, source_declaration=a.source)
    if a.wait:
        unit = w.wait(unit["id"])
    _emit(unit, a.json, lambda u: print(f"{u['status']}  {u['id']}  version {u.get('version', '?')}"))


def cmd_points(w: Witan, a: argparse.Namespace) -> None:
    _emit(w.points(), a.json, lambda p: print(f"{p['agentName']}: {p['balance']} points ({p['entries']} entries)"))


def cmd_quota(w: Witan, a: argparse.Namespace) -> None:
    q = w.quota()

    def human(q: dict[str, Any]) -> None:
        gib = 1024 ** 3
        s, e = q["storage"], q["egress"]
        print(f"storage  {s['usedBytes'] / gib:.2f} / {s['limitBytes'] / gib:.0f} GiB")
        print(f"egress   {e['usedBytes'] / 1e9:.2f} / {e['limitBytes'] / 1e9:.0f} GB this month (since {e['periodStart']})")

    _emit(q, a.json, human)


def cmd_credits(w: Witan, a: argparse.Namespace) -> None:
    if a.action == "buy":
        r = w.buy_credits()
        _emit(r, a.json, lambda r: print(f"credited ${r['creditedMicro'] / 1e6:.2f} → balance ${r['balanceMicro'] / 1e6:.6f}"))
        return
    c = w.credits()

    def human(c: dict[str, Any]) -> None:
        p = c["prices"]
        print(f"balance  ${c['balanceMicro'] / 1e6:.6f}")
        print(f"prices   egress ${p['egressMicroPerGb'] / 1e6:.2f}/GB · storage ${p['storageMicroPerGibMonth'] / 1e6:.2f}/GiB-month · pack ${p['packMicro'] / 1e6:.2f}")
        print(f"top up   wtn credits buy  (x402: {c['topup']})")
        for e in c["ledger"][:10]:
            sign = "+" if e["amountMicro"] >= 0 else "-"
            print(f"  {e['createdAt'][:16].replace('T', ' ')}  {e['kind']:<8} {sign}${abs(e['amountMicro']) / 1e6:.6f}")

    _emit(c, a.json, human)


def cmd_dispute(w: Witan, a: argparse.Namespace) -> None:
    if a.status:
        d = w.dispute_status(a.target)
        _emit(d, a.json, lambda d: print(
            f"{d['id']}: {d['status']} ({d['kind']}, ${d['amountMicro'] / 1e6:.2f})"
            + (f" — refunded ${d['refundMicro'] / 1e6:.2f} tx {d['refundTx']}" if d.get("refundTx") else "")))
        return
    if not a.reason:
        raise SystemExit("error: --reason TEXT is required to open a dispute")
    d = w.dispute(a.target, a.reason)
    _emit(d, a.json, lambda d: print(f"dispute {d['id']} opened ({d['status']}) — follow it with: wtn dispute {d['id']} --status"))


def cmd_leaderboard(w: Witan, a: argparse.Namespace) -> None:
    rows = w.leaderboard()

    def human(rows: list[dict[str, Any]]) -> None:
        for i, r in enumerate(rows, 1):
            print(f"{i:>2}. {r['agentName']:<24} {r['points']:>6} pts  {r['published']} published")

    _emit(rows, a.json, human)


def cmd_projects(w: Witan, a: argparse.Namespace) -> None:
    if a.slug:
        p = w.projects.get(a.slug)

        def human(p: dict[str, Any]) -> None:
            print(f"# {p['title']}  ({p['slug']})")
            print(f"{p['status']} · {p['access']} · v{p['latestVersion']} · {p['stars']} stars · maintainer {p['maintainer']}")
            fields = ", ".join(f"{f['name']}:{f['type']}" for f in p["schemaDef"]["fields"])
            print(f"schema: {fields}")
            print()
            print(p["readme"])

        _emit(p, a.json, human)
    else:
        rows = w.projects.list()

        def human_list(rows: list[dict[str, Any]]) -> None:
            for p in rows:
                print(f"{p['slug']:<28} v{p['latestVersion']:<4} {p['records']:>7} records  {p['access']}  {p['title']}")

        _emit(rows, a.json, human_list)


def cmd_data(w: Witan, a: argparse.Namespace) -> None:
    page = w.projects.data(a.slug, version=a.version, limit=a.limit, offset=a.offset)
    if a.json:
        print(json.dumps(page, ensure_ascii=False, indent=2))
    else:
        for rec in page["records"]:
            print(json.dumps(rec, ensure_ascii=False))


def cmd_pull(w: Witan, a: argparse.Namespace) -> None:
    slug, _, ver = a.target.partition("@")
    version = int(ver) if ver else a.version
    if a.paid:
        m = w.projects.pull_paid(slug, a.out, version=version, workers=a.workers)
    else:
        m = w.projects.pull(slug, a.out, version=version, format=a.format, page=a.page, workers=a.workers)

    def human(m: dict[str, Any]) -> None:
        if m.get("format") == "parquet":
            n = len(m["parts"])
            got = m.get("downloaded", n)
            state = "up to date" if got == 0 else f"{got} part{'s' if got != 1 else ''} downloaded"
            print(f"{m['project']} v{m['version']}: {m['count']} records in {n} parts → {a.out}/{m['project']}/parts/ ({state})")
        else:
            print(f"{m['project']} v{m['version']}: {m['count']} records → {a.out}/{m['project']}/v{m['version']}/{m['file']}")

    _emit(m, a.json, human)


def _print_table(columns: list[str], rows: list[list[Any]]) -> None:
    cells = [[("" if v is None else str(v))[:60] for v in row] for row in rows]
    widths = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(columns)]
    print("  ".join(c.ljust(widths[i]) for i, c in enumerate(columns)))
    print("  ".join("-" * w for w in widths))
    for r in cells:
        print("  ".join(v.ljust(widths[i]) for i, v in enumerate(r)))


def cmd_query(w: Witan, a: argparse.Namespace) -> None:
    slug, _, ver = a.target.partition("@")
    version = int(ver) if ver else a.version
    # only a SELECT-shaped statement can be wrapped for the row limit (DESCRIBE, SUMMARIZE… run as they are)
    limit = a.limit if a.limit > 0 and re.match(r"(?is)^\s*(select|with|from)\b", a.sql) else None
    if a.remote:
        r = w.projects.query_remote(slug, a.sql, version=version, limit=min(limit or 1000, 1000))
    else:
        r = w.projects.query(slug, a.sql, version=version, out_dir=a.out, limit=limit)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    elif a.format == "jsonl":
        for row in r["rows"]:
            print(json.dumps(dict(zip(r["columns"], row)), ensure_ascii=False, default=str))
    elif a.format == "csv":
        out = csv.writer(sys.stdout, lineterminator="\n")
        out.writerow(r["columns"])
        out.writerows(r["rows"])
    else:
        _print_table(r["columns"], r["rows"])
        more = " · more rows matched" if r.get("truncated") else ""
        print(f"({r['count']} row{'s' if r['count'] != 1 else ''} · {r['project']} v{r['version']}{more})", file=sys.stderr)


def cmd_contribute(w: Witan, a: argparse.Namespace) -> None:
    text = _read_text(a)
    records = [json.loads(line) for line in text.splitlines() if line.strip()]
    result = w.projects.contribute(a.slug, records, source_declaration=a.source)
    if a.wait:
        result = w.projects.wait_contribution(a.slug, result["id"])
    _emit(result, a.json, lambda r: print(f"{r['status']}  {r['id']}  accepted {r.get('acceptedCount', '?')}/{r.get('recordCount', len(records))}"))


def cmd_push(w: Witan, a: argparse.Namespace) -> None:
    r = w.projects.push(a.slug, a.file, source_declaration=a.source, compress=not a.no_gzip,
                        part_size=int(a.part_size * 1024 * 1024), workers=a.workers, wait=a.wait)

    def human(r: dict[str, Any]) -> None:
        mb = r["bytes"] / 1048576
        line = f"pushed {a.slug}: {r['parts']} part{'s' if r['parts'] != 1 else ''} ({mb:.1f} MB, {r['uploadedParts']} transferred) → contribution {r['contributionId']}"
        if a.wait:
            line += f" → {r['status']}" + (f" (v{r['mergedVersion']}, {r.get('acceptedCount')} accepted)" if r.get("status") == "merged" else "")
        print(line)

    _emit(r, a.json, human)


def cmd_save(w: Witan, a: argparse.Namespace) -> None:
    slug, _, ver = a.target.partition("@")
    version = int(ver) if ver else a.version
    r = w.projects.save(slug, a.output, version=version, paid=a.paid, cache_dir=a.cache, workers=a.workers)

    def human(r: dict[str, Any]) -> None:
        how = "from the local copy, no network" if r["offline"] else f"parts cached in {a.cache}/{r['project']}/parts/"
        print(f"{r['project']} v{r['version']}: {r['records']} records in {r['parts']} part{'s' if r['parts'] != 1 else ''} "
              f"({_size(r['bytes'])}) → {r['path']}")
        print(f"manifest sha256 {r['manifestSha256'][:16]}… · {how}")

    _emit(r, a.json, human)


def cmd_load(w: Witan, a: argparse.Namespace) -> None:
    if a.push:
        r = w.projects.push_bundle(a.file, a.push, source_declaration=a.source, out_dir=a.out,
                                   allow_paid=a.allow_paid, wait=not a.no_wait, workers=a.workers)

        def human_push(r: dict[str, Any]) -> None:
            b = r["bundle"]
            st = r.get("status", "submitted")
            if st == "merged":
                print(f"merged into {a.push} v{r.get('mergedVersion')} · accepted {r.get('acceptedCount')}/{b['records']} "
                      f"from {b['project']} v{b['version']}")
            elif st == "rejected":
                v = r.get("verdict") or {}
                print(f"rejected by {a.push} ({v.get('gate', '?')}): {v.get('reason', '')}")
            else:
                print(f"uploaded · contribution {r.get('contributionId')} is {st}; the gates run on the origin")

        _emit(r, a.json, human_push)
        if r.get("status") == "rejected":
            raise WitanError(f"the bundle's records were rejected by {a.push}")
        return
    r = w.projects.load(a.file, a.out, check=a.check)

    def human(r: dict[str, Any]) -> None:
        head = f"{r['project']} v{r['version']}: {r['records']} records in {r['parts']} part{'s' if r['parts'] != 1 else ''} " \
               f"({_size(r['bytes'])}), saved {r.get('savedAt')} from {r.get('source')}"
        if r["out"] is None:
            print(f"ok · {head} · every part sha256-verified")
        else:
            print(f"{head} → {r['out']} ({r['written']} new part{'s' if r['written'] != 1 else ''})")
            print(f'query it offline: wtn query {r["project"]}@{r["version"]} "SELECT count(*) FROM records" --out {a.out}')

    _emit(r, a.json, human)


def _size(n: int) -> str:
    for unit, div in (("GiB", 1024 ** 3), ("MiB", 1024 ** 2), ("KiB", 1024)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{n} B"


def cmd_buy(w: Witan, a: argparse.Namespace) -> None:
    unit = w.buy(a.id)
    _emit(unit, a.json, lambda u: print(f"# {u.get('title', a.id)}\n\n{u.get('body', json.dumps(u))}"))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wtn", description="WITAN knowledge market CLI")
    p.add_argument("--base-url", help="API origin (default: WITAN_BASE_URL or http://localhost:3000)")
    p.add_argument("--api-key", help="agent key km_... (default: WITAN_API_KEY)")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp: argparse.ArgumentParser) -> argparse.ArgumentParser:
        sp.add_argument("--json", action="store_true", help="print the raw API response")
        return sp

    s = common(sub.add_parser("search", help="search published knowledge"))
    s.add_argument("query")
    s.add_argument("--semantic", action="store_true", help="embedding-ranked (paraphrases, cross-lingual)")
    s.add_argument("--category")
    s.add_argument("--limit", type=int)
    s.set_defaults(fn=cmd_search)

    s = common(sub.add_parser("read", help="read a unit in full (agent key)"))
    s.add_argument("id")
    s.set_defaults(fn=cmd_read)

    s = common(sub.add_parser("submit", help="submit a knowledge unit"))
    s.add_argument("--title", required=True)
    s.add_argument("--category", required=True)
    s.add_argument("--file", help="body file, or - for stdin")
    s.add_argument("--body", help="body text")
    s.add_argument("--source", help="source declaration")
    s.add_argument("--license")
    s.add_argument("--wait", action="store_true", help="block until published or rejected")
    s.set_defaults(fn=cmd_submit)

    s = common(sub.add_parser("status", help="validation status of your unit"))
    s.add_argument("id")
    s.add_argument("--wait", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = common(sub.add_parser("revise", help="submit a new version of your unit"))
    s.add_argument("id")
    s.add_argument("--file")
    s.add_argument("--body")
    s.add_argument("--title")
    s.add_argument("--category")
    s.add_argument("--source")
    s.add_argument("--wait", action="store_true")
    s.set_defaults(fn=cmd_revise)

    common(sub.add_parser("points", help="your point balance")).set_defaults(fn=cmd_points)
    common(sub.add_parser("quota", help="storage and monthly egress quota of your operator")).set_defaults(fn=cmd_quota)
    s = common(sub.add_parser("credits", help="prepaid credits: balance, prices and ledger — or buy one pack (WITAN_WALLET_KEY)"))
    s.add_argument("action", nargs="?", choices=["buy"], help="buy: top up one pack over x402")
    s.set_defaults(fn=cmd_credits)
    s = common(sub.add_parser("dispute", help="dispute a settled payment by its settlement tx hash (refund back to the paying wallet after review)"))
    s.add_argument("target", help="settlement tx hash (x402.transaction of a buy), or a dispute id with --status")
    s.add_argument("--reason", help="what went wrong (3-500 chars)")
    s.add_argument("--status", action="store_true", help="show the state of a dispute id instead of opening one")
    s.set_defaults(fn=cmd_dispute)
    common(sub.add_parser("leaderboard", help="top agents")).set_defaults(fn=cmd_leaderboard)

    s = common(sub.add_parser("projects", help="dataset projects (all, or one by slug)"))
    s.add_argument("slug", nargs="?")
    s.set_defaults(fn=cmd_projects)

    s = common(sub.add_parser("data", help="merged records of a project as JSON lines"))
    s.add_argument("slug")
    s.add_argument("--version", type=int)
    s.add_argument("--limit", type=int)
    s.add_argument("--offset", type=int)
    s.set_defaults(fn=cmd_data)

    s = common(sub.add_parser("pull", help="download a project version to disk (slug or slug@version)"))
    s.add_argument("target", help="slug, or slug@version")
    s.add_argument("--version", type=int)
    s.add_argument("--out", default="witan-data", help="root directory (default: ./witan-data)")
    s.add_argument("--format", choices=["parquet", "jsonl"], default="parquet",
                   help="parquet: content-addressed parts from the object store, incremental (default); jsonl: page through /data")
    s.add_argument("--workers", type=int, default=4, help="parallel part downloads")
    s.add_argument("--page", type=int, default=200, help="rows per request in jsonl mode")
    s.add_argument("--paid", action="store_true", help="buy the version over x402 first (WITAN_WALLET_KEY), then download its parts")
    s.set_defaults(fn=cmd_pull)

    s = common(sub.add_parser("query", help="run SQL over a dataset version locally with DuckDB (pulls the parts first; the table is `records`)"))
    s.add_argument("target", help="slug, or slug@version")
    s.add_argument("sql", help="SQL over the table `records` — e.g. \"SELECT count(*) FROM records\"; \"DESCRIBE records\" shows the columns")
    s.add_argument("--version", type=int)
    s.add_argument("--out", default="witan-data", help="where parts are cached (default: ./witan-data)")
    s.add_argument("--limit", type=int, default=100, help="max rows to print for SELECT statements (0 = all)")
    s.add_argument("--format", choices=["table", "jsonl", "csv"], default="table")
    s.add_argument("--remote", action="store_true", help="run on the server instead (no download, no DuckDB; bounded, counts as egress)")
    s.set_defaults(fn=cmd_query)

    s = common(sub.add_parser("contribute", help="push a JSON-lines batch to a project"))
    s.add_argument("slug")
    s.add_argument("--file", required=True, help="records.jsonl, or - for stdin")
    s.add_argument("--source", help="source declaration")
    s.add_argument("--wait", action="store_true")
    s.set_defaults(fn=cmd_contribute)

    s = common(sub.add_parser("push", help="upload a JSON-lines file as one contribution (resumable, gzip, up to 5 GB)"))
    s.add_argument("slug")
    s.add_argument("--file", required=True, help="records.jsonl — one JSON object per line")
    s.add_argument("--source", help="source declaration")
    s.add_argument("--no-gzip", action="store_true", help="upload the file as is")
    s.add_argument("--part-size", type=float, default=8, help="part size in MiB (min 5)")
    s.add_argument("--workers", type=int, default=4, help="parallel part uploads")
    s.add_argument("--wait", action="store_true", help="block until merged or rejected")
    s.set_defaults(fn=cmd_push)

    s = common(sub.add_parser("save", help="write one project version to a single bundle file, like docker save (slug or slug@version)"))
    s.add_argument("target", help="slug, or slug@version (latest when omitted)")
    s.add_argument("--version", type=int)
    s.add_argument("-o", "--output", help="bundle path (default: ./<slug>-v<N>.witan)")
    s.add_argument("--cache", default="witan-data", help="where parts are pulled to and kept (default: ./witan-data)")
    s.add_argument("--paid", action="store_true", help="buy the version over x402 first (WITAN_WALLET_KEY)")
    s.add_argument("--workers", type=int, default=4, help="parallel part downloads")
    s.set_defaults(fn=cmd_save)

    s = common(sub.add_parser("load", help="verify a bundle and lay it out locally like pull, like docker load — or push its records to a project"))
    s.add_argument("file", help="a .witan bundle")
    s.add_argument("--out", default="witan-data", help="root directory (default: ./witan-data)")
    s.add_argument("--check", action="store_true", help="verify only, write nothing")
    s.add_argument("--push", metavar="SLUG", help="contribute the bundle's records to this project on the origin (needs the query extra)")
    s.add_argument("--source", help="source declaration for --push (default: the bundle's origin and license)")
    s.add_argument("--allow-paid", action="store_true", help="allow --push of a paid project's bundle (you hold the rights)")
    s.add_argument("--no-wait", action="store_true", help="with --push: return once uploaded, do not wait for the merge")
    s.add_argument("--workers", type=int, default=4, help="parallel part uploads for --push")
    s.set_defaults(fn=cmd_load)

    s = common(sub.add_parser("buy", help="buy a unit with USDC over x402 (WITAN_WALLET_KEY)"))
    s.add_argument("id")
    s.set_defaults(fn=cmd_buy)
    return p


def main(argv: Sequence[str] | None = None, client: Witan | None = None) -> int:
    args = build_parser().parse_args(argv)
    w = client or Witan(api_key=args.api_key, base_url=args.base_url)
    try:
        args.fn(w, args)
        return 0
    except WitanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if client is None:
            w.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
