"""Testnet e2e is opt-in so the normal suite stays offline."""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="run the live Besu testnet end-to-end test",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-e2e"):
        return
    skip = pytest.mark.skip(reason="live testnet e2e; pass --run-e2e to enable")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip)
