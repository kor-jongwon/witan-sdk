"""Generate the SDK documentation diagrams as SVG (sdk/python/docs/diagrams/*.svg).

Styled with the site's tokens (web/src/index.css), one dark card per diagram so they read on white
(PyPI, npm) and dark (GitHub) pages alike. PNG copies for READMEs: scripts/diagrams-render.sh.

    python3 sdk/python/tools/make_diagrams.py
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent.parent / "docs" / "diagrams"


# The site's tokens (web/src/index.css): near-black with a violet-to-amber tint, glass panels with
# hairline borders, violet glow on what matters, amber for money, green for "live / verified".
BG, PANEL, LINE = "#07080C", "#0E0F16", "#272830"
INK, SOFT, DIM = "#ECEEF2", "#9BA1AD", "#5D6370"
VIOLET, ROSE, AMBER, GREEN = "#7C5CFF", "#FF5C87", "#FFB35C", "#58C48A"
FONT = "'Wanted Sans Variable', 'Wanted Sans', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif"
MONO = "'DM Mono', 'SFMono-Regular', Consolas, monospace"
HEAD = 40  # the brand row pushes every body down by this much


def _marker(mid: str, color: str) -> str:
    return (f'<marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{color}"/></marker>')


def _defs() -> str:
    glow = ('<filter id="{id}" x="-50%" y="-50%" width="200%" height="200%">'
            '<feDropShadow dx="0" dy="0" stdDeviation="{sd}" flood-color="{c}" flood-opacity="{o}"/></filter>')
    return ('<defs>' + _marker("arrow", SOFT) + _marker("arrow-v", VIOLET) + _marker("arrow-a", AMBER)
            + '<linearGradient id="aurora" x1="12" y1="2" x2="21" y2="10" gradientUnits="userSpaceOnUse">'
            '<stop offset="0" stop-color="#7C5CFF"/><stop offset=".6" stop-color="#FF5C87"/>'
            '<stop offset="1" stop-color="#FFB35C"/></linearGradient>'
            '<linearGradient id="aurora-h" x1="0" y1="0" x2="1" y2="0">'
            '<stop offset="0" stop-color="#7C5CFF"/><stop offset=".6" stop-color="#FF5C87"/>'
            '<stop offset="1" stop-color="#FFB35C"/></linearGradient>'
            '<linearGradient id="aurora-v" x1="0" y1="0" x2="0" y2="1">'
            '<stop offset="0" stop-color="#9A80FF"/><stop offset="1" stop-color="#7C5CFF" stop-opacity=".55"/></linearGradient>'
            '<linearGradient id="tint" x1=".3" y1="0" x2=".7" y2="1">'
            '<stop offset="0" stop-color="#7C5CFF" stop-opacity=".2"/><stop offset=".46" stop-color="#07080C" stop-opacity="0"/>'
            '<stop offset="1" stop-color="#FF8A4C" stop-opacity=".09"/></linearGradient>'
            + glow.format(id="glow-v", sd=7, c=VIOLET, o=.55)
            + glow.format(id="glow-w", sd=2.5, c=INK, o=.45)
            + glow.format(id="glow-g", sd=4, c=GREEN, o=.8)
            + glow.format(id="glow-a", sd=4, c=AMBER, o=.45)
            + '<filter id="blur-mark" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="1.2"/></filter>'
            + '</defs>')


def svg(w: int, h: int, title: str, subtitle: str, body: list[str], label: str) -> str:
    h += HEAD
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'role="img" aria-label="{escape(label)}" font-family="{FONT}" text-rendering="geometricPrecision">\n'
            + _defs() + "\n"
            f'<rect width="{w}" height="{h}" rx="18" fill="{BG}"/>\n'
            f'<rect width="{w}" height="{h}" rx="18" fill="url(#tint)"/>\n'
            f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="17.5" fill="none" stroke="{INK}" stroke-opacity=".12"/>\n'
            # brand row, as on the site's nav
            + mark(44, 36, 0.95, glow=True)
            + f'<text x="62" y="41.5" font-size="15.5" font-weight="700" letter-spacing="-0.3" fill="{INK}">WITAN</text>\n'
            f'<text x="32" y="{46 + HEAD}" font-size="25" font-weight="800" letter-spacing="-0.8" fill="{INK}">{escape(title)}</text>\n'
            f'<text x="32" y="{71 + HEAD}" font-size="14" fill="{SOFT}">{escape(subtitle)}</text>\n'
            f'<g transform="translate(0 {HEAD})">\n' + "\n".join(body) + "\n</g>\n</svg>\n")


def mark(cx: float, cy: float, scale: float, *, glow: bool = False) -> str:
    """The WITAN crystal; with glow, a blurred copy sits behind it as on the site."""
    shape = ('<polygon points="3,7 12,2 12,10" fill="#F2F3F7"/><polygon points="12,2 21,7 12,10" fill="url(#aurora)"/>'
             '<polygon points="21,7 21,17 12,22 12,10" fill="#B9BEC9"/><polygon points="3,7 12,10 12,22 3,17" fill="#5E6470"/>')
    t = f'translate({cx - 12 * scale} {cy - 12 * scale}) scale({scale})'
    halo = (f'<g transform="{t}" filter="url(#blur-mark)" opacity=".6">{shape}</g>' if glow else "")
    return halo + f'<g transform="{t}">{shape}</g>'


def text(x: float, y: float, s: str, size: float = 12.5, fill: str = SOFT, weight: int = 400,
         anchor: str = "start", mono: bool = False) -> str:
    fam = f' font-family="{MONO}"' if mono else ""
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}" xml:space="preserve"{fam}>{escape(s)}</text>')


def panel(x: float, y: float, w: float, h: float, *, accent: bool = False, rx: float = 14,
          dashed: bool = False, fill: str = PANEL) -> str:
    """A glass panel: hairline border; the one that matters glows violet."""
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    if accent:
        return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{VIOLET}" '
                f'stroke-width="1.5" filter="url(#glow-v)"{dash}/>')
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" fill-opacity=".86" '
            f'stroke="{INK}" stroke-opacity=".16"{dash}/>')


def box(x: float, y: float, w: float, h: float, lines: list[str], *, accent: str | None = None,
        dashed: bool = False, fill: str = PANEL, mono_rest: bool = False) -> str:
    if accent and accent != VIOLET:  # red/amber outcomes keep their colour, without the violet glow
        out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{accent}" stroke-width="1.5"/>']
    else:
        out = [panel(x, y, w, h, accent=bool(accent), rx=12, dashed=dashed, fill=fill)]
    if lines:
        out.append(text(x + 16, y + 25, lines[0], 14.5, INK, 600))
        for i, line in enumerate(lines[1:]):
            out.append(text(x + 16, y + 45 + 18 * i, line, 12.5, SOFT, mono=mono_rest))
    return "\n".join(out)


def arrow(x1: float, y1: float, x2: float, y2: float, label: str = "", *, violet: bool = False,
          dashed: bool = False, lx: float | None = None, ly: float | None = None) -> str:
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    if violet:
        style = f'stroke="{VIOLET}" stroke-width="1.8" marker-end="url(#arrow-v)"'  # no glow: a filter on a flat line has an empty box
    else:
        style = f'stroke="{SOFT}" stroke-width="1.4" marker-end="url(#arrow)"'
    out = [f'<path d="M{x1} {y1}L{x2} {y2}" fill="none"{dash} {style}/>']
    if label:
        out.append(text(lx if lx is not None else (x1 + x2) / 2, ly if ly is not None else min(y1, y2) - 8,
                        label, 11.5, DIM, anchor="middle"))
    return "\n".join(out)


def header(x: float, y: float, s: str) -> str:
    """The site's eyebrow: small capitals, tracked out, dim."""
    return (f'<text x="{x}" y="{y}" font-size="11" font-weight="600" letter-spacing="0.7" fill="{DIM}" '
            f'xml:space="preserve">{escape(s.upper())}</text>')


def overview() -> str:
    b = [header(32, 106, "Agents"), header(324, 106, "WITAN origin"), header(708, 106, "Copies")]
    b += [box(32, 118, 220, 64, ["Claude Code · Cursor", "MCP plugin, dataset tools"]),
          box(32, 196, 220, 64, ["Python SDK · wtn", "pull, query, contribute, pay"]),
          box(32, 274, 220, 64, ["JS SDK", "state for serverless and edge"])]
    b.append(panel(324, 118, 312, 220, accent=True))
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
        b.append(f'<rect x="{x}" y="274" width="164" height="56" rx="12" fill="{PANEL}" stroke="{colors[p]}" stroke-width="1.5"/>')
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
    b.append(panel(848, 118, 80, 42, accent=True, rx=10))
    b.append(text(888, 144, "verified", 13, INK, 600, "middle"))
    b.append(f'<rect x="848" y="172" width="80" height="42" rx="10" fill="{PANEL}" stroke="{ROSE}" stroke-width="1.5"/>')
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
    b.append(f'<rect x="306" y="106" width="324" height="206" rx="16" fill="none" stroke="{INK}" stroke-opacity=".3" stroke-dasharray="6 5"/>')
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


# ---- story diagrams: few words, big shapes ----
def robot(cx: float, cy: float, color: str, size: float = 1.0) -> str:
    """An agent: a rounded head, two eyes, an antenna."""
    w, h = 40 * size, 32 * size
    x, y = cx - w / 2, cy - h / 2 + 4 * size
    return (f'<line x1="{cx}" y1="{y}" x2="{cx}" y2="{y - 9 * size}" stroke="{color}" stroke-width="{1.8 * size}"/>'
            f'<circle cx="{cx}" cy="{y - 11 * size}" r="{2.8 * size}" fill="{color}"/>'
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{9 * size}" fill="{color}" fill-opacity="0.1" '
            f'stroke="{color}" stroke-width="{1.8 * size}"/>'
            f'<circle cx="{cx - 8 * size}" cy="{y + h * 0.48}" r="{3.4 * size}" fill="{INK}"/>'
            f'<circle cx="{cx + 8 * size}" cy="{y + h * 0.48}" r="{3.4 * size}" fill="{INK}"/>')


def unit_card(cx: float, cy: float) -> str:
    """What is traded: a small glass card with a chart on it."""
    x, y = cx - 22, cy - 16
    bars = "".join(f'<rect x="{x + 9 + 9 * i}" y="{y + 24 - h}" width="5" height="{h}" rx="1.5" fill="url(#aurora-v)"/>'
                   for i, h in enumerate((8, 13, 18)))
    return (f'<rect x="{x}" y="{y}" width="44" height="32" rx="7" fill="{PANEL}" stroke="{INK}" stroke-opacity=".4" '
            f'stroke-width="1.2"/>' + bars)


def coin(cx: float, cy: float, r: float = 17) -> str:
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{AMBER}" fill-opacity="0.16" stroke="{AMBER}" stroke-width="1.8" '
            f'filter="url(#glow-a)"/>' + text(cx, cy + r * 0.36, "$", r * 1.05, AMBER, 800, "middle"))


def badge_check(cx: float, cy: float) -> str:
    return (f'<circle cx="{cx}" cy="{cy}" r="14" fill="{BG}" stroke="{GREEN}" stroke-width="1.8" filter="url(#glow-g)"/>'
            f'<path d="M{cx - 6} {cy}l4 4.5l8 -9" stroke="{GREEN}" stroke-width="2.4" fill="none" '
            'stroke-linecap="round" stroke-linejoin="round"/>')


def node(cx: float, cy: float, r: float, *, accent: bool = False) -> str:
    if accent:
        return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{PANEL}" stroke="{VIOLET}" stroke-width="1.8" '
                f'filter="url(#glow-v)"/>')
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{PANEL}" stroke="{INK}" stroke-opacity=".2" stroke-width="1.2"/>'


def how_it_works() -> str:
    y = 206
    b = []
    # the three actors
    b.append(node(150, y, 62))
    b.append(robot(150, y, INK, 1.35))
    b.append(node(480, y, 74, accent=True))
    b.append(mark(480, y + 2, 3.9, glow=True))
    b.append(badge_check(534, y - 52))
    b.append(node(810, y, 62))
    b.append(robot(810, y, INK, 1.35))
    # the result travels right, on the site's white arcs
    for x1, x2, cx, label in ((214, 404, 309, "submits"), (556, 746, 651, "delivers")):
        b.append(f'<path d="M{x1} {y}Q{cx} {y - 30} {x2} {y}" stroke="{INK}" stroke-opacity=".8" stroke-width="1.8" '
                 f'fill="none" filter="url(#glow-w)" marker-end="url(#arrow)"/>')
        b.append(unit_card(cx, y - 15))
        b.append(text(cx, y - 44, label, 12.5, SOFT, 600, "middle"))
    # who does what — three words each
    for cx, name, what in ((150, "Agent A", "measures once"), (480, "WITAN", "verifies & signs"), (810, "Agent B", "reads it for $0.01")):
        b.append(text(cx, y + 104, name, 17, INK, 700, "middle"))
        b.append(text(cx, y + 126, what, 14, SOFT, 500, "middle"))
    # the money travels back
    b.append(f'<path d="M810 {y + 146}V{y + 172}H150V{y + 150}" stroke="{AMBER}" stroke-width="2" fill="none" '
             f'stroke-dasharray="7 5" marker-end="url(#arrow-a)"/>')
    b.append(f'<rect x="338" y="{y + 154}" width="284" height="36" rx="18" fill="{BG}"/>')
    b.append(coin(362, y + 172))
    b.append(text(388, y + 178, "70% of every read → Agent A", 15, AMBER, 700))
    return svg(960, 420, "Agents trade what they measured",
               "Measured once, verified by WITAN, bought by every agent that needs it.",
               b, "How WITAN works: agent A measures, WITAN verifies and signs, agent B buys it; 70% goes back to A")


def why_witan() -> str:
    b = []
    base = 348  # bars stand on this line; height = the work
    b.append(panel(24, 96, 440, 296, rx=16))
    b.append(panel(496, 96, 440, 296, rx=16, accent=True))
    b.append(header(48, 126, "Without WITAN"))
    b.append(f'<text x="520" y="126" font-size="11" font-weight="700" letter-spacing="0.7" fill="#B7A6FF">WITH WITAN</text>')
    b.append(text(48, 186, "4×", 52, DIM, 800))
    b.append(text(140, 164, "the same work,", 15, SOFT, 600))
    b.append(text(140, 184, "done four times", 15, SOFT, 600))
    b.append(text(520, 186, "1×", 52, "url(#aurora-h)", 800))
    b.append(text(612, 164, "measured once,", 15, INK, 600))
    b.append(text(612, 184, "bought for $0.01", 15, INK, 600))
    for i in range(4):
        cx = 92 + 96 * i
        b.append(robot(cx, 222, DIM, 0.8))
        b.append(f'<rect x="{cx - 22}" y="{base - 96}" width="44" height="96" rx="8" fill="{INK}" fill-opacity=".07" '
                 f'stroke="{INK}" stroke-opacity=".12"/>')
        cx2 = 564 + 96 * i
        if i == 0:
            b.append(robot(cx2, 222, INK, 0.8))
            b.append(f'<rect x="{cx2 - 22}" y="{base - 96}" width="44" height="96" rx="8" fill="url(#aurora-v)" '
                     f'filter="url(#glow-v)"/>')
        else:
            b.append(robot(cx2, 222, AMBER, 0.8))
            b.append(f'<rect x="{cx2 - 22}" y="{base - 12}" width="44" height="12" rx="4" fill="{AMBER}" fill-opacity=".5"/>')
            b.append(coin(cx2, base - 34, 14))
    b.append(f'<line x1="48" y1="{base}" x2="440" y2="{base}" stroke="{INK}" stroke-opacity=".14"/>')
    b.append(f'<line x1="520" y1="{base}" x2="912" y2="{base}" stroke="{INK}" stroke-opacity=".14"/>')
    b.append(text(244, base + 28, "every agent pays the full cost", 13, DIM, 600, "middle"))
    b.append(text(716, base + 28, "and Agent A earns 70% of every read", 13, AMBER, 700, "middle"))
    return svg(960, 416, "Measured once, reused by every agent",
               "The bar is the work: without a market everyone repeats it; with WITAN it is done once and paid for.",
               b, "Why WITAN: without it four agents repeat the same work; with it one measures and three buy for $0.01")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in [("how-it-works", how_it_works), ("why-witan", why_witan),
                     ("overview", overview), ("dataset-model", dataset_model),
                     ("trust-chain", trust_chain), ("node-topology", node_topology)]:
        (OUT / f"{name}.svg").write_text(fn(), encoding="utf-8")
        print("wrote", OUT / f"{name}.svg")


if __name__ == "__main__":
    main()
