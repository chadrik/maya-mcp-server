"""Tests for the MCP tool layer in server.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp.exceptions import ToolError

from maya_mcp_server import server
from maya_mcp_server.types import CommandResponse, ErrorInfo, OutputBuffer


# ============================================================================
# Fixtures
# ============================================================================


REMOTE_ERROR: ErrorInfo = {
    "type": "builtins.NameError",
    "message": "name 'boom' is not defined",
    "traceback": 'Traceback (most recent call last):\n  File "<mcp>", line 1\nNameError: ...',
}


@pytest.fixture
def mock_client() -> MagicMock:
    """A Maya client whose buffered output fetch succeeds."""
    client = MagicMock()
    client.get_buffered_output = AsyncMock(return_value=OutputBuffer(stdout="", stderr=""))
    client.append_output = MagicMock()
    return client


@pytest.fixture
def patched_manager(monkeypatch: pytest.MonkeyPatch, mock_client: MagicMock) -> MagicMock:
    """Install a session manager that hands back mock_client."""
    manager = MagicMock()
    manager.get_client = AsyncMock(return_value=mock_client)
    monkeypatch.setattr(server, "_session_manager", manager)
    return manager


# ============================================================================
# execute_code error propagation
# ============================================================================


async def test_execute_code_raises_on_remote_error(
    patched_manager: MagicMock, mock_client: MagicMock
) -> None:
    """A remote exception must surface as ToolError, not be silently dropped."""
    mock_client.execute_code = AsyncMock(
        return_value=CommandResponse(result=None, error=REMOTE_ERROR)
    )

    with pytest.raises(ToolError) as excinfo:
        await server.execute_code.fn(code="boom", result_type="NONE")

    message = str(excinfo.value)
    assert "builtins.NameError" in message
    assert "name 'boom' is not defined" in message
    assert "Traceback (most recent call last)" in message


async def test_execute_code_returns_result_when_no_error(
    patched_manager: MagicMock, mock_client: MagicMock
) -> None:
    """Successful execution still returns the captured result."""
    mock_client.execute_code = AsyncMock(
        return_value=CommandResponse(result=["pCube1"], error=None)
    )

    result = await server.execute_code.fn(code="cmds.ls()", result_type="JSON")

    assert result == ["pCube1"]


async def test_execute_code_buffers_output_before_raising(
    patched_manager: MagicMock, mock_client: MagicMock
) -> None:
    """Output printed before the exception is preserved, not lost to the raise."""
    mock_client.execute_code = AsyncMock(
        return_value=CommandResponse(result=None, error=REMOTE_ERROR)
    )
    mock_client.get_buffered_output = AsyncMock(
        return_value=OutputBuffer(stdout="partial work\n", stderr="")
    )

    with pytest.raises(ToolError):
        await server.execute_code.fn(code="boom", result_type="NONE")

    mock_client.append_output.assert_called_once_with("partial work\n", "")
