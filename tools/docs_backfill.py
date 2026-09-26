#!/usr/bin/env python3
"""Documentation for the releases that came before the documentation site.

For every release tag that has no docs on gh-pages yet, build that version's own
README (as it appeared on PyPI), its API reference generated from its own code,
its `wtn` reference from its own parser, and the release notes up to it — then
deploy it with mike under its version number. Newer releases carry the full
guides; these older pages say plainly that they are the README of the time.

Run from the repository root after `pip install -r requirements-docs.txt`:
    python tools/docs_backfill.py            # deploy locally (gh-pages branch)
    python tools/docs_backfill.py --push     # and push it
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sh(*args: str, cwd: Path = ROOT, check: bool = True) -> str:
    return subprocess.run(args, cwd=cwd, check=check, capture_output=True, text=True).stdout


def semver(tag: str) -> tuple[int, ...]:
    return tuple(int(x) for x in tag.lstrip("v").split("."))


def deployed() -> set[str]:
    try:
        return {v["version"] for v in json.loads(sh("mike", "list", "--json"))}
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return set()


def notes_up_to(changelog: str, version: tuple[int, ...]) -> str:
    """The changelog's header and every release at or before `version`."""
    head, *sections = re.split(r"(?m)^## ", changelog)
    kept = [s for s in sections if (m := re.match(r"(\d+)\.(\d+)\.(\d+)", s)) and tuple(map(int, m.groups())) <= version]
    return head + "".join("## " + s for s in kept)


LEGACY_CONFIG = """\
site_name: witan-sdk for Python
site_url: https://kor-jongwon.github.io/witan-sdk/
repo_url: https://github.com/kor-jongwon/witan-sdk
repo_name: kor-jongwon/witan-sdk
edit_uri: ""
copyright: WITAN · MIT license · testnet preview
docs_dir: site-src
theme:
  name: material
  custom_dir: overrides
  logo: witan-mark.png
  favicon: witan-mark.png
  font: false
  palette:
    - media: "(prefers-color-scheme: light)"
      scheme: default
      primary: custom
      accent: custom
      toggle: {icon: material/weather-night, name: Dark theme}
    - media: "(prefers-color-scheme: dark)"
      scheme: slate
      primary: custom
      accent: custom
      toggle: {icon: material/weather-sunny, name: Light theme}
  features: [navigation.sections, navigation.top, search.suggest, search.highlight, content.code.copy, toc.follow]
extra:
  version: {provider: mike, default: stable, alias: true}
extra_css: [stylesheets/witan.css]
hooks: [mkdocs_hooks.py]
markdown_extensions:
  - admonition
  - attr_list
  - md_in_html
  - tables
  - toc: {permalink: true}
  - pymdownx.highlight
  - pymdownx.superfences
plugins:
  - search
  - mkdocstrings:
      handlers:
        python:
          paths: [src]
          options: {docstring_style: google, show_source: false, show_root_heading: true, show_root_full_path: false,
                    members_order: source, separate_signature: true, filters: ["!^_"], heading_level: 2,
                    merge_init_into_class: true}
nav:
  - Home: index.md
  - Reference:
      - The Witan client: reference/client.md
      - wtn command line: reference/cli.md
  - Release notes: changelog.md
"""


def build_legacy(tag: str, tree: Path) -> None:
    """Lay out a legacy docs tree inside the checked-out tag at `tree`."""
    version = tag.lstrip("v")
    src = tree / "site-src"
    (src / "reference").mkdir(parents=True)
    readme = (tree / "README.md").read_text(encoding="utf-8")
    date = sh("git", "log", "-1", "--format=%cs", tag).strip()
    banner = (f'!!! note "witan-sdk {version} · released {date}"\n'
              f"    This release predates the documentation site: below is its README as published on PyPI, "
              f"with the API and `wtn` references generated from its own code. The guides start with 0.17.0 — "
              f"see the version selector.\n\n")
    (src / "index.md").write_text(banner + readme, encoding="utf-8")
    has_client = (tree / "src" / "witan_sdk" / "client.py").exists()
    (src / "reference" / "client.md").write_text(
        "# The Witan client\n\n" + ("::: witan_sdk.client.Witan\n\n::: witan_sdk.client.Projects\n" if has_client else "Not available.\n"),
        encoding="utf-8")
    (src / "reference" / "cli.md").write_text("# wtn command line\n\n<!-- wtn-reference -->\n", encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    (src / "changelog.md").write_text(notes_up_to(changelog, semver(tag)), encoding="utf-8")
    # The look and the hook come from the current tree, the words and the code from the tag.
    shutil.copytree(ROOT / "overrides", tree / "overrides", dirs_exist_ok=True)
    shutil.copytree(ROOT / "docs" / "stylesheets", src / "stylesheets")
    shutil.copy(ROOT / "docs" / "witan-mark.png", src / "witan-mark.png")
    shutil.copy(ROOT / "mkdocs_hooks.py", tree / "mkdocs_hooks.py")
    (tree / "mkdocs-legacy.yml").write_text(LEGACY_CONFIG, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--push", action="store_true")
    args = ap.parse_args()
    current = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
    have = deployed()
    tags = sorted((t for t in sh("git", "tag", "--list", "v*").split() if re.fullmatch(r"v\d+\.\d+\.\d+", t)), key=semver)
    todo = [t for t in tags if t.lstrip("v") not in have and semver(t) < semver(current)]
    print(f"{len(tags)} release tags, {len(have)} versions deployed, {len(todo)} to backfill")
    for tag in todo:
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / tag
            sh("git", "worktree", "add", "--detach", str(tree), tag)
            try:
                build_legacy(tag, tree)
                result = subprocess.run(["mike", "deploy", "--config-file", str(tree / "mkdocs-legacy.yml"),
                                         "--title", tag.lstrip("v"), tag.lstrip("v")],
                                        cwd=ROOT, capture_output=True, text=True)
                print(f"{tag}: {'deployed' if result.returncode == 0 else 'FAILED ' + result.stderr.strip().splitlines()[-1]}")
            finally:
                sh("git", "worktree", "remove", "--force", str(tree), check=False)
    if args.push and todo:
        sh("git", "push", "origin", "gh-pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
