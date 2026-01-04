"""Pytest fixtures for maya-mcp-server tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from tests.mocks.maya_mock import MockMayaServer


@pytest.fixture
def mock_port() -> int:
    """Return a port for the mock server."""
    return 17002


@pytest_asyncio.fixture
async def mock_maya_server(mock_port: int) -> AsyncIterator[MockMayaServer]:
    """Create and start a mock Maya server."""
    server = MockMayaServer(port=mock_port)
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
