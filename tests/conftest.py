"""Pytest fixtures for maya-mcp-server tests."""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture
def mock_port() -> int:
    """Return a port for the mock server."""
    return 17002


@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
