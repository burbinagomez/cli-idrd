"""pytest configuration for IDRD CLI tests."""

from __future__ import annotations

import pytest


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
