"""``wtn`` — the WITAN command line. Reads WITAN_API_KEY / WITAN_BASE_URL from the
environment; ``--json`` prints raw API responses for piping."""

from __future__ import annotations

import argparse
import json
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
    m = w.projects.pull(slug, a.out, version=version, page=a.page)
    _emit(m, a.json, lambda m: print(f"{m['project']} v{m['version']}: {m['count']} records → {a.out}/{m['project']}/v{m['version']}/{m['file']}"))


def cmd_contribute(w: Witan, a: argparse.Namespace) -> None:
    text = _read_text(a)
    records = [json.loads(line) for line in text.splitlines() if line.strip()]
    result = w.projects.contribute(a.slug, records, source_declaration=a.source)
    if a.wait:
        result = w.projects.wait_contribution(a.slug, result["id"])
    _emit(result, a.json, lambda r: print(f"{r['status']}  {r['id']}  accepted {r.get('acceptedCount', '?')}/{r.get('recordCount', len(records))}"))


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
    s.add_argument("--page", type=int, default=200)
    s.set_defaults(fn=cmd_pull)

    s = common(sub.add_parser("contribute", help="push a JSON-lines batch to a project"))
    s.add_argument("slug")
    s.add_argument("--file", required=True, help="records.jsonl, or - for stdin")
    s.add_argument("--source", help="source declaration")
    s.add_argument("--wait", action="store_true")
    s.set_defaults(fn=cmd_contribute)

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
