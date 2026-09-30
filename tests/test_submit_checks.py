"""What the origin refuses is refused before sending: a unit's source declaration and the license
of a unit or a project (api/src/routes/knowledge.ts, api/src/licenses.ts). No network."""

from __future__ import annotations

import json

import httpx
import pytest

from witan_sdk import LICENSES, Witan
from witan_sdk.cli import main

UNIT = "5e5fc8dd-af67-4f34-839b-b366ef05d43d"


def client(seen: list[httpx.Request], *, node: bool = False) -> Witan:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/healthz":  # the origin answers {ok}; a node with its token says so
            return httpx.Response(200, json={"ok": True, **({"node": True} if node else {})})
        seen.append(request)
        if request.method == "POST" and request.url.path == "/knowledge":
            return httpx.Response(201, json={"id": UNIT, "status": "submitted"})
        if request.method == "POST" and request.url.path == "/projects":
            body = json.loads(request.content)
            return httpx.Response(201, json={"slug": body["slug"], "license": body.get("license", "platform-standard")})
        return httpx.Response(404, json={"error": "no route"})

    return Witan(api_key="km_test", base_url="http://witan.test", transport=httpx.MockTransport(handler))


def test_licenses_match_the_origin_list():
    assert LICENSES == ("platform-standard", "CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "ODbL-1.0", "PDDL-1.0",
                        "CDLA-Permissive-2.0")


@pytest.mark.parametrize("declaration", [None, "", "abc", "   \n  ", "x" * 2001])
def test_submit_refuses_a_missing_or_bad_source_declaration(declaration):
    seen: list[httpx.Request] = []
    with pytest.raises(ValueError, match="source_declaration"):
        client(seen).submit("title", "body", "infra-measurement", source_declaration=declaration)
    assert seen == []


def test_submit_sends_the_declaration_and_the_license_as_listed():
    seen: list[httpx.Request] = []
    w = client(seen)
    w.submit("title", "body", "infra-measurement", source_declaration="own run, 2026-09-30", license="cc-by-4.0")
    w.submit("title", "body", "infra-measurement", source_declaration="x" * 2000)
    first, second = (json.loads(r.content) for r in seen)
    assert first["sourceDeclaration"] == "own run, 2026-09-30" and first["license"] == "CC-BY-4.0"
    assert "license" not in second


@pytest.mark.parametrize("license", ["MIT", "cc-by", "free text", ""])
def test_unknown_licenses_are_refused_before_sending(license):
    seen: list[httpx.Request] = []
    w = client(seen)
    with pytest.raises(ValueError, match="license must be one of"):
        w.submit("title", "body", "infra-measurement", source_declaration="own run", license=license)
    with pytest.raises(ValueError, match="license must be one of"):
        w.projects.create("probe", "Probe", "readme", {"fields": []}, license=license)
    assert seen == []


def test_project_license_any_case():
    seen: list[httpx.Request] = []
    client(seen).projects.create("probe", "Probe", "readme", {"fields": []}, license="odbl-1.0")
    assert json.loads(seen[0].content)["license"] == "ODbL-1.0"


def test_a_node_takes_any_project_license_as_given():
    seen: list[httpx.Request] = []
    w = client(seen, node=True)
    w.projects.create("probe", "Probe", "readme", {"fields": []}, license="MIT")
    w.projects.create("probe2", "Probe", "readme", {"fields": []}, license="cc-by-4.0")
    assert [json.loads(r.content)["license"] for r in seen] == ["MIT", "cc-by-4.0"]


def test_a_listed_license_needs_no_probe():
    probes: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        probes.append(request.url.path)
        return httpx.Response(201, json={"slug": "probe"})

    w = Witan(api_key="km_test", base_url="http://witan.test", transport=httpx.MockTransport(handler))
    w.projects.create("probe", "Probe", "readme", {"fields": []}, license="CC-BY-4.0")
    assert probes == ["/projects"]


def test_cli_submit_needs_source_and_a_listed_license(capsys: pytest.CaptureFixture[str]):
    seen: list[httpx.Request] = []
    w = client(seen)
    base = ["submit", "--title", "t", "--category", "infra-measurement", "--body", "b"]
    with pytest.raises(SystemExit) as ei:
        main(base, client=w)
    assert ei.value.code == 2 and "--source" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(base + ["--source", "abc"], client=w)
    assert "source_declaration is required" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(base + ["--source", "own run", "--license", "MIT"], client=w)
    assert "license must be one of" in capsys.readouterr().err
    assert seen == []
    assert main(base + ["--source", "own run", "--license", "cc0-1.0", "--json"], client=w) == 0
    assert json.loads(seen[0].content)["license"] == "CC0-1.0"


def test_cli_create_checks_the_license_on_the_origin_only(capsys: pytest.CaptureFixture[str]):
    args = ["create", "probe", "--title", "Probe", "--readme", "r", "--schema", '{"fields":[]}', "--license", "MIT"]
    seen: list[httpx.Request] = []
    assert main(args, client=client(seen)) == 1
    assert "license must be one of" in capsys.readouterr().err and seen == []
    assert main(args + ["--json"], client=client(seen, node=True)) == 0
    assert json.loads(seen[0].content)["license"] == "MIT"
