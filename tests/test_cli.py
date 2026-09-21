from __future__ import annotations

import json

import httpx
import pytest

from witan_sdk import Witan
from witan_sdk.cli import main

from test_client import UNIT, Fake


@pytest.fixture
def client() -> Witan:
    return Witan("km_test", base_url="http://api.test", transport=httpx.MockTransport(Fake()))


def test_search_human_and_json(client: Witan, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["search", "redis"], client=client) == 0
    out = capsys.readouterr().out
    assert UNIT in out and "witan-lab" in out
    assert main(["search", "redis", "--semantic", "--json"], client=client) == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["similarity"] == "0.91"


def test_read_and_error_exit_code(client: Witan, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["read", UNIT], client=client) == 0
    assert "full text" in capsys.readouterr().out
    assert main(["read", "00000000-0000-0000-0000-000000000000"], client=client) == 1
    assert "error:" in capsys.readouterr().err


def test_submit_from_stdin_and_wait(client: Witan, capsys: pytest.CaptureFixture[str],
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("measured body"))
    assert main(["submit", "--title", "t", "--category", "infra-measurement", "--file", "-", "--wait"], client=client) == 0
    assert "published  new-1" in capsys.readouterr().out


def test_pull_parquet_then_up_to_date(client: Witan, capsys: pytest.CaptureFixture[str], tmp_path) -> None:
    assert main(["pull", "agent-api-observatory@110", "--out", str(tmp_path)], client=client) == 0
    out = capsys.readouterr().out
    assert "3 records in 2 parts" in out and "2 parts downloaded" in out
    assert main(["pull", "agent-api-observatory", "--out", str(tmp_path)], client=client) == 0
    assert "up to date" in capsys.readouterr().out
    assert main(["pull", "agent-api-observatory", "--out", str(tmp_path), "--format", "jsonl"], client=client) == 0
    assert "records.jsonl" in capsys.readouterr().out


def test_projects_and_data_jsonl(client: Witan, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["projects"], client=client) == 0
    assert "agent-api-observatory" in capsys.readouterr().out
    assert main(["data", "agent-api-observatory", "--limit", "1"], client=client) == 0
    line = capsys.readouterr().out.strip().splitlines()[0]
    assert json.loads(line)["ok"] is True
