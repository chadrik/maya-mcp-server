"""Tests for MCP server tools."""

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
        sessions = await server._list_sessions()
        assert len(sessions) == 1

    async def test_use_session(
        self, setup_server: SessionManager, mock_port: int
    ) -> None:
        """Test use_session tool."""
        info = await server._use_session("127.0.0.1", mock_port)
        assert info["port"] == mock_port

    async def test_unuse_session(
        self, setup_server: SessionManager, mock_port: int
    ) -> None:
        """Test unuse_session tool."""
        await server._use_session("127.0.0.1", mock_port)
        result = await server._unuse_session()
        assert "deactivated" in result.lower()
        assert setup_server.active_session is None

    async def test_unuse_session_no_active(self, setup_server: SessionManager) -> None:
        """Test unuse_session when no active session."""
        result = await server._unuse_session()
        assert "no active session" in result.lower()

    async def test_get_session_info(
        self, setup_server: SessionManager, mock_port: int
    ) -> None:
        """Test get_session_info tool."""
        await server._use_session("127.0.0.1", mock_port)
        info = await server._get_session_info()
        assert info["port"] == mock_port
        assert "pid" in info
        assert "user" in info

    async def test_get_session_info_requires_session(
        self, setup_server: SessionManager
    ) -> None:
        """Test that get_session_info requires an active session."""
        # Clear active session
        await server._unuse_session()

        with pytest.raises(RuntimeError, match="No active session"):
            await server._get_session_info()

    async def test_get_output(
        self, setup_server: SessionManager, mock_port: int
    ) -> None:
        """Test get_output tool."""
        await server._use_session("127.0.0.1", mock_port)
        await server._execute_code("print('hello')")
        output = await server._get_output()
        assert "stdout" in output
        assert "stderr" in output

    async def test_execute_code_requires_session(
        self, setup_server: SessionManager
    ) -> None:
        """Test that execute_code requires an active session."""
        # Clear active session
        await server._unuse_session()

        with pytest.raises(RuntimeError, match="No active session"):
            await server._execute_code("1+1")

    async def test_execute_code(
        self, setup_server: SessionManager, mock_port: int
    ) -> None:
        """Test execute_code tool."""
        await server._use_session("127.0.0.1", mock_port)
        result = await server._execute_code("1+1")
        assert "error" in result
        assert result["error"] is None

    async def test_write_module_requires_session(
        self, setup_server: SessionManager
    ) -> None:
        """Test that write_module requires an active session."""
        # Clear active session
        await server._unuse_session()

        with pytest.raises(RuntimeError, match="No active session"):
            await server._write_module("test", "x = 1")

    async def test_write_module(
        self, setup_server: SessionManager, mock_port: int
    ) -> None:
        """Test write_module tool."""
        await server._use_session("127.0.0.1", mock_port)
        result = await server._write_module("mymod", "x = 42")
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
