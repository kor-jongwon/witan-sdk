"""The editor plugins this repository ships (Claude Code and Cursor): manifests that load, sources
that exist, one skill kept identical in both, and an MCP connection to WITAN's /mcp. No network."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(not (ROOT / ".claude-plugin").exists(), reason="the plugins are not part of the sdist")
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
EDITORS = {
    "claude": (ROOT / ".claude-plugin" / "marketplace.json", ".claude-plugin"),
    "cursor": (ROOT / ".cursor-plugin" / "marketplace.json", ".cursor-plugin"),
}


def plugins(editor: str) -> list[tuple[dict, Path]]:
    manifest, folder = EDITORS[editor]
    market = json.loads(manifest.read_text(encoding="utf-8"))
    assert KEBAB.match(market["name"]) and market["owner"]["name"]
    out = []
    for entry in market["plugins"]:
        root = (ROOT / entry["source"]).resolve()
        assert root.is_relative_to(ROOT), entry["source"]
        plugin = json.loads((root / folder / "plugin.json").read_text(encoding="utf-8"))
        assert plugin["name"] == entry["name"] and KEBAB.match(plugin["name"])
        out.append((plugin, root))
    return out


@pytest.mark.parametrize("editor", sorted(EDITORS))
def test_marketplace_and_plugin_load(editor):
    assert plugins(editor)


def skill(root: Path) -> str:
    text = (root / "skills" / "witan" / "SKILL.md").read_text(encoding="utf-8")
    front = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert front and re.search(r"^name: witan$", front.group(1), re.M) and re.search(r"^description: .{40,}", front.group(1), re.M)
    return text


def test_one_skill_in_both_plugins():
    (_, claude), = plugins("claude")
    (_, cursor), = plugins("cursor")
    assert skill(claude) == skill(cursor)


def test_both_connect_to_the_mcp_endpoint():
    (claude_plugin, _), = plugins("claude")
    server = claude_plugin["mcpServers"]["witan"]
    assert server["type"] == "http" and server["url"].endswith("/mcp") and "${WITAN_API_KEY" in server["headers"]["Authorization"]
    (_, cursor), = plugins("cursor")
    cursor_server = json.loads((cursor / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["witan"]
    assert cursor_server["url"] == "${env:WITAN_BASE_URL}/mcp"
    assert cursor_server["headers"]["Authorization"] == "Bearer ${env:WITAN_API_KEY}"
