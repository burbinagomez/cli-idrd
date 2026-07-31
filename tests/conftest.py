"""pytest configuration for IDRD CLI tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_session_store(tmp_path, monkeypatch):
    """Point token storage at a temp dir and default keyring to unavailable.

    Keeps unit tests deterministic: no writes to the real ~/.idrd/session.json
    and no access to the real OS credential store. Individual tests re-patch
    the idrd.session._keyring_* helpers to exercise keyring behavior.
    """
    monkeypatch.setattr(
        "idrd.session._session_path",
        lambda: tmp_path / ".idrd" / "session.json",
    )
    monkeypatch.setattr("idrd.session._keyring_get", lambda *a, **k: None)
    monkeypatch.setattr("idrd.session._keyring_set", lambda *a, **k: False)
    monkeypatch.setattr("idrd.session._keyring_delete", lambda *a, **k: None)


def pytest_addoption(parser):
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="Run tests that hit the live IDRD API (requires internet).",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "network: marks tests that hit the live API (skipped unless --run-network is passed)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-network"):
        return  # don't skip network tests
    skip_network = pytest.mark.skip(reason="need --run-network option to run")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)
