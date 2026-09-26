"""Editing a project and retiring a unit: the calls and the CLI commands. No network."""

from __future__ import annotations

import json

import httpx
import pytest

from witan_sdk import AuthError, Witan
from witan_sdk.cli import main

UNIT = "5e5fc8dd-af67-4f34-839b-b366ef05d43d"


def client(seen: list[httpx.Request]) -> Witan:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "PATCH" and request.url.path == "/projects/agent-state":
            body = json.loads(request.content)
            return httpx.Response(200, json={"slug": "agent-state", "title": body.get("title", "Agent state"),
                                             "status": body.get("status", "open"), "tags": body.get("tags", [])})
        if request.method == "POST" and request.url.path == f"/knowledge/{UNIT}/retire":
            return httpx.Response(200, json={"id": UNIT, "status": "retired", "retiredAt": "2026-09-26T00:00:00Z"})
        if request.url.path == "/knowledge/00000000-0000-0000-0000-000000000000/retire":
            return httpx.Response(403, json={"error": "only the unit's author can retire it"})
        return httpx.Response(404, json={"error": "no route"})

    return Witan(api_key="km_test", base_url="http://witan.test", transport=httpx.MockTransport(handler))


def test_update_sends_only_what_changes():
    seen: list[httpx.Request] = []
    r = client(seen).projects.update("agent-state", status="archived", tags=["latency"])
    assert r["status"] == "archived"
    assert seen[0].method == "PATCH"
    assert json.loads(seen[0].content) == {"status": "archived", "tags": ["latency"]}
    assert seen[0].headers["authorization"] == "Bearer km_test"


def test_update_with_nothing_to_change_is_refused_locally():
    seen: list[httpx.Request] = []
    with pytest.raises(ValueError):
        client(seen).projects.update("agent-state")
    assert seen == []


def test_retire():
    seen: list[httpx.Request] = []
    r = client(seen).retire(UNIT)
    assert r["status"] == "retired"
    assert seen[0].method == "POST" and seen[0].url.path == f"/knowledge/{UNIT}/retire"


def test_retire_someone_elses_unit_is_an_auth_error():
    seen: list[httpx.Request] = []
    with pytest.raises(AuthError):
        client(seen).retire("00000000-0000-0000-0000-000000000000")


def test_cli_edit_and_retire(tmp_path, capsys):
    seen: list[httpx.Request] = []
    w = client(seen)
    readme = tmp_path / "README.md"
    readme.write_text("Per-run state of an agent, key and value.", encoding="utf-8")
    assert main(["edit", "agent-state", "--title", "Agent state v2", "--readme-file", str(readme),
                 "--tags", "state, latency", "--status", "paused"], client=w) == 0
    body = json.loads(seen[-1].content)
    assert body == {"title": "Agent state v2", "readme": "Per-run state of an agent, key and value.",
                    "tags": ["state", "latency"], "status": "paused"}
    assert "agent-state  paused  Agent state v2" in capsys.readouterr().out
    assert main(["retire", UNIT], client=w) == 0
    assert "retired" in capsys.readouterr().out
