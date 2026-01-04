"""Tests for MCP server tools.

Note: MCP tools are decorated with @mcp.tool which returns a FunctionTool object.
To call them in tests, use the .fn attribute to access the underlying function:
    await server.list_sessions.fn()
    await server.use_session.fn(host, port)
"""

from __future__ import annotations

import pytest

from maya_mcp_server import server
from maya_mcp_server.session_manager import SessionManager
from tests.mocks.maya_mock import MockMayaServer


class TestServerTools:
    """Tests for MCP server tools."""

    @pytest.fixture
    async def setup_server(self, mock_port: int):
        """Set up server with mock Maya."""
        mock = MockMayaServer(port=mock_port)
        await mock.start()

        # Initialize session manager
        manager = await server.initialize_session_manager(
            scan_interval=100.0,
        )

        yield manager

        await server.shutdown_session_manager()
        await mock.stop()

    async def test_list_sessions(self, setup_server: SessionManager) -> None:
        """Test list_sessions tool."""
        sessions = await server.list_sessions.fn()
        assert len(sessions) == 1

    async def test_use_session(self, setup_server: SessionManager, mock_port: int) -> None:
        """Test use_session tool."""
        info = await server.use_session.fn("127.0.0.1", mock_port)
        assert info["port"] == mock_port

    async def test_unuse_session(self, setup_server: SessionManager, mock_port: int) -> None:
        """Test unuse_session tool."""
        await server.use_session.fn("127.0.0.1", mock_port)
        result = await server.unuse_session.fn()
        assert "deactivated" in result.lower()
        assert setup_server.active_session is None

    async def test_unuse_session_no_active(self, setup_server: SessionManager) -> None:
        """Test unuse_session when no active session."""
        result = await server.unuse_session.fn()
        assert "no active session" in result.lower()

    async def test_get_session_info(self, setup_server: SessionManager, mock_port: int) -> None:
        """Test get_session_info tool."""
        await server.use_session.fn("127.0.0.1", mock_port)
        info = await server.get_session_info.fn()
        assert info["port"] == mock_port
        assert "pid" in info
        assert "user" in info

    async def test_get_session_info_requires_session(self, setup_server: SessionManager) -> None:
        """Test that get_session_info requires an active session."""
        # Clear active session
        await server.unuse_session.fn()

        with pytest.raises(RuntimeError, match="No active session"):
            await server.get_session_info.fn()

    async def test_get_output(self, setup_server: SessionManager, mock_port: int) -> None:
        """Test get_output tool."""
        await server.use_session.fn("127.0.0.1", mock_port)
        await server.execute_code.fn("print('hello')")
        output = await server.get_output.fn()
        assert "stdout" in output
        assert "stderr" in output

    async def test_execute_code_requires_session(self, setup_server: SessionManager) -> None:
        """Test that execute_code requires an active session."""
        # Clear active session
        await server.unuse_session.fn()

        with pytest.raises(RuntimeError, match="No active session"):
            await server.execute_code.fn("1+1")

    async def test_execute_code(self, setup_server: SessionManager, mock_port: int) -> None:
        """Test execute_code tool."""
        await server.use_session.fn("127.0.0.1", mock_port)
        result = await server.execute_code.fn("1+1")
        assert "error" in result
        assert result["error"] is None

    async def test_write_module_requires_session(self, setup_server: SessionManager) -> None:
        """Test that write_module requires an active session."""
        # Clear active session
        await server.unuse_session.fn()

        with pytest.raises(RuntimeError, match="No active session"):
            await server.write_module.fn("test", "x = 1")

    async def test_write_module(self, setup_server: SessionManager, mock_port: int) -> None:
        """Test write_module tool."""
        await server.use_session.fn("127.0.0.1", mock_port)
        result = await server.write_module.fn("mymod", "x = 42")
        assert "success" in result.lower() or "created" in result.lower()


class TestServerInitialization:
    """Tests for server initialization."""

    async def test_get_session_manager_not_initialized(self) -> None:
        """Test that get_session_manager raises when not initialized."""
        # Ensure manager is None
        server._session_manager = None

        with pytest.raises(RuntimeError, match="not initialized"):
            server.get_session_manager()

    async def test_initialize_shutdown(self) -> None:
        """Test initialize and shutdown cycle."""
        manager = await server.initialize_session_manager(
            scan_interval=100.0,
        )
        assert manager is not None
        assert server._session_manager is manager

        await server.shutdown_session_manager()
        assert server._session_manager is None
