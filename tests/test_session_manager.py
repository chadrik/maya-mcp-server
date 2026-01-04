"""Tests for SessionManager."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from maya_mcp_server.session_manager import SessionManager
from tests.mocks.maya_mock import MockMayaServer


class TestSessionManagerBasic:
    """Basic SessionManager tests."""

    async def test_init(self) -> None:
        """Test SessionManager initialization."""
        manager = SessionManager()
        assert manager.session_count == 0
        assert manager.active_session is None

    async def test_start_stop(self) -> None:
        """Test starting and stopping the manager."""
        manager = SessionManager(scan_interval=100.0)  # Long interval to avoid scans
        await manager.start()
        await manager.stop()

    async def test_add_session(self, mock_port: int) -> None:
        """Test manually adding a session."""
        async with MockMayaServer(port=mock_port):
            manager = SessionManager(scan_interval=100.0)
            await manager.start()

            try:
                client = await manager.add_session("127.0.0.1", mock_port)
                assert client is not None
                assert manager.session_count == 1
            finally:
                await manager.stop()

    async def test_use_session(self, mock_port: int) -> None:
        """Test activating a session."""
        async with MockMayaServer(port=mock_port):
            manager = SessionManager(scan_interval=100.0)
            await manager.start()

            try:
                await manager.add_session("127.0.0.1", mock_port)
                client = await manager.use_session("127.0.0.1", mock_port)
                assert manager.active_session is client
                assert manager.active_session.key == f"127.0.0.1:{mock_port}"
            finally:
                await manager.stop()

    async def test_unuse_session(self, mock_port: int) -> None:
        """Test deactivating a session."""
        async with MockMayaServer(port=mock_port):
            manager = SessionManager(scan_interval=100.0)
            await manager.start()

            try:
                await manager.add_session("127.0.0.1", mock_port)
                await manager.use_session("127.0.0.1", mock_port)
                assert manager.active_session is not None
                assert manager.active_session.key is not None

                await manager.unuse_session()
                assert manager.active_session is None
            finally:
                await manager.stop()

    async def test_use_nonexistent_session(self) -> None:
        """Test activating a non-existent session."""
        manager = SessionManager(scan_interval=100.0)
        await manager.start()

        try:
            with pytest.raises(ValueError):
                await manager.use_session("127.0.0.1", 59999)
        finally:
            await manager.stop()


class TestSessionManagerDiscovery:
    """Tests for session discovery."""

    async def test_scan_finds_session(self, mock_port: int) -> None:
        """Test that scanning finds a running Maya session."""
        mock_ports = [{'port': mock_port, 'address': '127.0.0.1', 'family': 'IPv4'}]
        with patch('maya_mcp_server.session_manager.get_maya_listening_ports', return_value=mock_ports):
            async with MockMayaServer(port=mock_port):
                manager = SessionManager(scan_interval=100.0)
                await manager.start()

                try:
                    # Session should be discovered
                    assert manager.session_count == 1
                finally:
                    await manager.stop()

    async def test_list_sessions(self, mock_port: int) -> None:
        """Test listing sessions."""
        mock_ports = [{'port': mock_port, 'address': '127.0.0.1', 'family': 'IPv4'}]
        with patch('maya_mcp_server.session_manager.get_maya_listening_ports', return_value=mock_ports):
            async with MockMayaServer(port=mock_port):
                manager = SessionManager(scan_interval=100.0)
                await manager.start()

                try:
                    sessions = await manager.list_sessions()
                    assert len(sessions) == 1
                    assert sessions[0]["port"] == mock_port
                finally:
                    await manager.stop()

    # FIXME: causes too many files error
    # async def test_prune_dead_session(self, mock_port: int) -> None:
    #     """Test that dead sessions are pruned."""
    #     mock_ports = [{'port': mock_port, 'address': '127.0.0.1', 'family': 'IPv4'}]
    #     with patch('maya_mcp_server.session_manager.get_maya_listening_ports', return_value=mock_ports):
    #         server = MockMayaServer(port=mock_port)
    #         await server.start()
    #
    #         manager = SessionManager(scan_interval=100.0)
    #         await manager.start()
    #
    #         try:
    #             assert manager.session_count == 1
    #
    #             # Stop the server
    #             await server.stop()
    #
    #             # Prune should remove the dead session
    #             await manager._prune_dead_sessions()
    #             assert manager.session_count == 0
    #         finally:
    #             await manager.stop()
