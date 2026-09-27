"""Shared test setup: retries never actually sleep (tests that care record the waits)."""

import pytest

import witan_sdk.client as client


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(client, "_sleep", waits.append)
    return waits
