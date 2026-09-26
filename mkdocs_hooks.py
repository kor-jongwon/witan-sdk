"""MkDocs hook: the ``wtn`` command reference, generated from this version's own
argparse parser, so every published version documents exactly the commands and
flags it shipped with."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

MARKER = "<!-- wtn-reference -->"


def on_page_markdown(markdown: str, page, config, files) -> str:  # noqa: ANN001 - MkDocs hook signature
    if MARKER not in markdown:
        return markdown
    return markdown.replace(MARKER, reference(Path(config["config_file_path"]).parent))


def reference(root: Path) -> str:
    sys.path.insert(0, str(root / "src"))
    os.environ["COLUMNS"] = "100"   # stable wrapping, whatever the build machine's terminal
    os.environ["NO_COLOR"] = "1"
    try:
        from witan_sdk.cli import build_parser
    except Exception as exc:  # pragma: no cover - older versions without build_parser
        return f'!!! note\n    The command reference could not be generated for this version: {exc}'
    parser = build_parser()
    out = ["## wtn", "", "```text", parser.format_help().rstrip(), "```", ""]
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                out += [f"## wtn {name}", "", "```text", sub.format_help().rstrip(), "```", ""]
    return "\n".join(out)
