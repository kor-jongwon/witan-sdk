"""Generate the SDK documentation diagrams as SVG (sdk/python/docs/diagrams/*.svg).

Flat, brand-coloured, one card per diagram so they read on white (PyPI, npm) and dark (GitHub)
pages alike. PNG copies for READMEs: scripts/diagrams-render.sh.

    python3 sdk/python/tools/make_diagrams.py
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent.parent / "docs" / "diagrams"

BG, PANEL, LINE = "#0B0C12", "#14151C", "#2C2F3A"
INK, SOFT, DIM = "#ECEEF2", "#9BA1AD", "#6B7180"
VIOLET, ROSE, AMBER = "#7C5CFF", "#FF5C87", "#FFB35C"
FONT = "'Wanted Sans Variable', 'Wanted Sans', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif"
MONO = "'IBM Plex Mono', 'SFMono-Regular', Consolas, monospace"


def svg(w: int, h: int, title: str, subtitle: str, body: list[str], label: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'role="img" aria-label="{escape(label)}" font-family="{FONT}" text-rendering="geometricPrecision">\n'
            f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{SOFT}"/></marker>'
            f'<marker id="arrow-v" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{VIOLET}"/></marker></defs>\n'
            f'<rect width="{w}" height="{h}" rx="16" fill="{BG}"/>\n'
            f'<text x="32" y="46" font-size="21" font-weight="700" fill="{INK}">{escape(title)}</text>\n'
            f'<text x="32" y="70" font-size="13.5" fill="{SOFT}">{escape(subtitle)}</text>\n'
            + "\n".join(body) + "\n</svg>\n")


def text(x: float, y: float, s: str, size: float = 12.5, fill: str = SOFT, weight: int = 400,
         anchor: str = "start", mono: bool = False) -> str:
    fam = f' font-family="{MONO}"' if mono else ""
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}" xml:space="preserve"{fam}>{escape(s)}</text>')


def box(x: float, y: float, w: float, h: float, lines: list[str], *, accent: str | None = None,
        dashed: bool = False, fill: str = PANEL, mono_rest: bool = False) -> str:
    stroke = accent or LINE
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{stroke}" '
           f'stroke-width="{1.6 if accent else 1.2}"{dash}/>']
    if lines:
        out.append(text(x + 16, y + 25, lines[0], 14.5, INK, 600))
        for i, line in enumerate(lines[1:]):
            out.append(text(x + 16, y + 45 + 18 * i, line, 12.5, SOFT, mono=mono_rest))
    return "\n".join(out)


def arrow(x1: float, y1: float, x2: float, y2: float, label: str = "", *, violet: bool = False,
          dashed: bool = False, lx: float | None = None, ly: float | None = None) -> str:
    color, marker = (VIOLET, "arrow-v") if violet else (SOFT, "arrow")
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    out = [f'<path d="M{x1} {y1}L{x2} {y2}" stroke="{color}" stroke-width="1.5" fill="none"{dash} '
           f'marker-end="url(#{marker})"/>']
    if label:
        out.append(text(lx if lx is not None else (x1 + x2) / 2, ly if ly is not None else min(y1, y2) - 8,
                        label, 11.5, DIM, anchor="middle"))
    return "\n".join(out)


def header(x: float, y: float, s: str) -> str:
    return text(x, y, s.upper(), 11, DIM, 600)


def overview() -> str:
    b = [header(32, 106, "Agents"), header(324, 106, "WITAN origin"), header(708, 106, "Copies")]
    b += [box(32, 118, 220, 64, ["Claude Code · Cursor", "MCP plugin, dataset tools"]),
          box(32, 196, 220, 64, ["Python SDK · wtn", "pull, query, contribute, pay"]),
          box(32, 274, 220, 64, ["JS SDK", "state for serverless and edge"])]
    b.append(f'<rect x="324" y="118" width="312" height="220" rx="12" fill="{PANEL}" stroke="{VIOLET}" stroke-width="1.6"/>')
    rows = [("Validation", "schema · PII · duplicates · model review"),
            ("Market", "knowledge units · versioned datasets"),
            ("Payments", "x402 USDC · credits · author royalties"),
            ("Signing", "Ed25519 over every version manifest")]
    for i, (t, s) in enumerate(rows):
        y = 132 + 50 * i
        b.append(f'<rect x="338" y="{y}" width="284" height="42" rx="8" fill="{BG}" stroke="{LINE}"/>')
        b.append(text(352, y + 17, t, 13, INK, 600))
        b.append(text(352, y + 33, s, 11.5, SOFT))
    b += [box(708, 118, 220, 64, ["Object store", "content-addressed Parquet parts"]),
          box(708, 196, 220, 64, ["Local node", "wtn serve · witan-node image"], accent=VIOLET),
          box(708, 274, 220, 64, ["Mirror of a node", "--upstream, signatures intact"])]
    b += [arrow(252, 150, 322, 150, "API · MCP", lx=288, ly=142),
          arrow(252, 228, 322, 228), arrow(252, 306, 322, 306),
          arrow(636, 150, 706, 150, "parts", lx=672, ly=142),
          arrow(636, 228, 706, 228, "follow", violet=True, lx=672, ly=220),
          arrow(818, 260, 818, 272)]
    b += [text(32, 378, "Agents read from the origin or from any node: the same API, SQL and MCP. A copy is trusted"),
          text(32, 398, "because its manifest carries the origin's signature, not because of where it came from.")]
    return svg(960, 424, "How WITAN works",
               "Agents exchange what they measured; every dataset version is signed where it is made.",
               b, "How WITAN works: agents, the origin, and signed copies")


def dataset_model() -> str:
    colors = {"a": "#4E5566", "b": "#5B6275", "c": "#6F5CD6", "d": "#8B6BE8", "e": ROSE}
    b = [header(32, 106, "Versions (immutable manifests)")]
    versions = [("v1", "ab"), ("v2", "abcd"), ("v3", "abcde")]
    for i, (v, parts) in enumerate(versions):
        x = 32 + 300 * i
        b.append(box(x, 118, 272, 92, [f"{v} manifest", "signed by the origin"], accent=VIOLET if v == "v3" else None))
        for j, p in enumerate(parts):
            b.append(f'<rect x="{x + 16 + 44 * j}" y="{118 + 58}" width="36" height="22" rx="5" fill="{colors[p]}"/>')
            b.append(text(x + 34 + 44 * j, 118 + 72, p, 12, INK, 600, "middle", mono=True))
    b.append(header(32, 262, "Object store (content-addressed Parquet parts, shared across versions)"))
    for j, p in enumerate("abcde"):
        x = 32 + 180 * j
        b.append(f'<rect x="{x}" y="274" width="164" height="56" rx="10" fill="{PANEL}" stroke="{colors[p]}" stroke-width="1.6"/>')
        b.append(text(x + 16, 298, f"part {p}", 14, INK, 600))
        b.append(text(x + 16, 317, f"<sha256-{p}>.parquet", 11.5, SOFT, mono=True))
    b.append(arrow(760, 210, 800, 272, "", violet=True))
    b.append(text(812, 246, "pull v3 with v2 on disk:", 11.5, SOFT))
    b.append(text(812, 262, "only part e transfers", 11.5, INK, 600))
    b += [text(32, 368, "A contribution becomes new parts plus a new manifest. Old versions never change, so a pinned"),
          text(32, 388, "version answers the same query forever, and every part is checked against its SHA-256 on the way in.")]
    return svg(960, 414, "A dataset version is a signed list of parts",
               "Like image layers: parts are content-addressed Parquet files that versions share.",
               b, "Dataset versions are signed manifests of shared Parquet parts")


def trust_chain() -> str:
    b = [box(32, 118, 196, 96, ["Origin", "signs each manifest", "key k2, endorsed by k1"], accent=VIOLET),
         box(312, 118, 196, 96, ["Node or mirror", "stores, serves copies", "signature unchanged"]),
         box(592, 118, 196, 96, ["Your client", "pinned k1 (trust add)", "follows k1 → k2"])]
    b.append(f'<rect x="848" y="118" width="80" height="42" rx="8" fill="{PANEL}" stroke="{VIOLET}" stroke-width="1.6"/>')
    b.append(text(888, 144, "verified", 13, INK, 600, "middle"))
    b.append(f'<rect x="848" y="172" width="80" height="42" rx="8" fill="{PANEL}" stroke="{ROSE}" stroke-width="1.6"/>')
    b.append(text(888, 190, "Signature", 12, INK, 600, "middle"))
    b.append(text(888, 205, "Error", 12, INK, 600, "middle"))
    b += [arrow(228, 166, 310, 166, "signed", lx=269, ly=156),
          arrow(508, 166, 590, 166, "unchanged", lx=549, ly=156),
          arrow(788, 150, 846, 139, violet=True), arrow(788, 182, 846, 193)]
    b += [text(32, 262, "Key rotation: the old key endorses the new one, and the endorsement travels inside every signature,"),
          text(32, 282, "so clients pinned to k1 keep verifying after the origin moves to k2. A revoked key stops counting at once."),
          text(32, 310, "Python: verify=True or WITAN_VERIFY=1 · JS: manifest(slug, { verify: keys }) · node: wtn serve --verify", 12, DIM, mono=True)]
    return svg(960, 336, "Signatures travel with the data",
               "Pin the origin's keys once; then check a copy from anywhere, however many hops it took.",
               b, "Origin signatures pass through nodes and mirrors and are verified by clients")


def node_topology() -> str:
    b = [box(32, 138, 200, 84, ["Your agent or app", "SDK or MCP client", "Bearer <token>"])]
    b.append(f'<rect x="306" y="106" width="324" height="206" rx="12" fill="none" stroke="{SOFT}" stroke-width="1.2" stroke-dasharray="6 5"/>')
    b.append(text(322, 128, "witan-node container · uid 10001 · read-only root", 11.5, DIM, 600))
    b.append(box(322, 142, 292, 64, ["wtn serve :8686", "API · SQL (DuckDB) · MCP /mcp"], accent=VIOLET))
    b.append(box(322, 224, 292, 72, ["/data volume", "witan-data/  trust.json"], mono_rest=True))
    b += [box(712, 118, 216, 84, ["WITAN origin", "pull the latest version", "--follow SLUG --verify"]),
          box(712, 226, 216, 84, ["Another node", "--upstream mirror", "signatures still checked"], dashed=True)]
    b += [arrow(232, 176, 320, 176, "HTTP · MCP", lx=269, ly=168),
          arrow(614, 164, 710, 158, "follow", violet=True, lx=668, ly=150),
          arrow(614, 190, 710, 256, "or", dashed=True, lx=676, ly=214),
          arrow(468, 206, 468, 222)]
    b += [text(32, 350, "docker run -d -p 127.0.0.1:8686:8686 -e WITAN_NODE_TOKEN=... -v witan-data:/data \\", 12, SOFT, mono=True),
          text(32, 370, "  ghcr.io/kor-jongwon/witan-node --follow agent-api-observatory --verify", 12, SOFT, mono=True)]
    return svg(960, 396, "witan-node in a container",
               "The origin's dataset API, SQL and MCP, served from a volume; kept current and verified.",
               b, "witan-node container topology: agent, node, volume, origin and mirrors")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in [("overview", overview), ("dataset-model", dataset_model),
                     ("trust-chain", trust_chain), ("node-topology", node_topology)]:
        (OUT / f"{name}.svg").write_text(fn(), encoding="utf-8")
        print("wrote", OUT / f"{name}.svg")


if __name__ == "__main__":
    main()
