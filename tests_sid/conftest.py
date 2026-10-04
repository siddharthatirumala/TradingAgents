"""Fixtures shared by the SID Trading Firm tests.

The suite runs the same on any machine: no network, nothing read from or written
to the user's home, and no SID_* settings leaking in from the developer's shell
or .env file. A test that needs a real service (PostgreSQL) is marked
``integration`` and skips unless that service is configured.
"""

import os
import socket
import tempfile

import pytest


def _own_file_locations():
    """Point upstream's results, cache and memory log at a directory of the suite's own.

    Set before ``tradingagents`` is imported, whose defaults live in the user's home.
    """
    home = tempfile.mkdtemp(prefix="sid-tests-")
    os.environ["TRADINGAGENTS_RESULTS_DIR"] = os.path.join(home, "logs")
    os.environ["TRADINGAGENTS_CACHE_DIR"] = os.path.join(home, "cache")
    os.environ["TRADINGAGENTS_MEMORY_LOG_PATH"] = os.path.join(home, "memory", "trading_memory.md")


_own_file_locations()


@pytest.fixture(autouse=True)
def _no_sid_environment(monkeypatch):
    """Clear SID_* variables so a developer's own settings never become test defaults."""
    for name in list(os.environ):
        if name.startswith("SID_"):
            monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    """Unit tests do not reach the network; a test that must is marked integration."""
    if request.node.get_closest_marker("integration"):
        return

    def refuse(*args, **kwargs):
        raise OSError(f"test tried to reach the network: {args[1:] or kwargs}")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: refuse(None, *a))
