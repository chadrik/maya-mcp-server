"""Tests for SessionManager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from maya_mcp_server.client import MayaClient, MayaConnectionError
from maya_mcp_server.session_manager import SessionManager
from maya_mcp_server.types import ClientType, CommandResponse, SessionInfo


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def session_manager() -> SessionManager:
    """Create a SessionManager instance for testing."""
    return SessionManager(scan_interval=10.0, client_type=ClientType.QT)


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock MayaClient."""
    client = MagicMock()
    client.host = "127.0.0.1"
    client.port = 50000
    client.key = "127.0.0.1:50000"
    client.ping = AsyncMock(return_value=True)
    client.session_info = AsyncMock(
        return_value=SessionInfo(
            host="127.0.0.1",
            port=50000,
            pid=12345,
            user="testuser",
            maya_version="2024",
            scene_name="test.ma",
            scene_path="/path/to/test.ma",
        )
    )
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.bootstrap = AsyncMock(return_value=client)
    client.install_stream_capture = AsyncMock()
    client.uninstall_stream_capture = AsyncMock()
    return client


# ============================================================================
# Properties Tests
# ============================================================================


class TestSessionManagerProperties:
    """Test SessionManager properties."""

    def test_init_defaults(self) -> None:
        """Test default initialization."""
        manager = SessionManager()
        assert manager.scan_interval == 10.0
        assert manager.client_type == ClientType.QT
        assert manager.session_count == 0
        assert manager.active_session is None

    def test_init_custom_values(self) -> None:
        """Test initialization with custom values."""
        manager = SessionManager(scan_interval=30.0, client_type=ClientType.NATIVE)
        assert manager.scan_interval == 30.0
        assert manager.client_type == ClientType.NATIVE

    def test_session_key(self, session_manager: SessionManager) -> None:
        """Test _session_key generates correct keys."""
        assert session_manager._session_key("127.0.0.1", 7001) == "127.0.0.1:7001"
        assert session_manager._session_key("localhost", 8000) == "localhost:8000"

    def test_session_count(
        self, session_manager: SessionManager, mock_client: MagicMock
    ) -> None:
        """Test session_count property."""
        assert session_manager.session_count == 0
        session_manager._sessions["127.0.0.1:50000"] = mock_client
        assert session_manager.session_count == 1

    def test_active_session(
        self, session_manager: SessionManager, mock_client: MagicMock
    ) -> None:
        """Test active_session property."""
        assert session_manager.active_session is None
        session_manager._active_session = mock_client
        assert session_manager.active_session is mock_client


# ============================================================================
# Start/Stop Tests
# ============================================================================


class TestStartStop:
    """Test start and stop methods."""

    @pytest.mark.asyncio
    async def test_start_scans_for_sessions(
        self, session_manager: SessionManager, mocker
    ) -> None:
        """Test start calls _scan_for_sessions."""
        mock_scan = mocker.patch.object(
            session_manager, "_scan_for_sessions", new_callable=AsyncMock
        )

        await session_manager.start()

        assert session_manager._running is True
        mock_scan.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_idempotent(
        self, session_manager: SessionManager, mocker
    ) -> None:
        """Test start is idempotent."""
        mock_scan = mocker.patch.object(
            session_manager, "_scan_for_sessions", new_callable=AsyncMock
        )

        await session_manager.start()
        await session_manager.start()

        # Should only scan once
        mock_scan.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_disconnects_sessions(
        self, session_manager: SessionManager, mock_client: MagicMock
    ) -> None:
        """Test stop disconnects all sessions."""
        session_manager._sessions["127.0.0.1:50000"] = mock_client
        session_manager._active_session = mock_client
        session_manager._running = True

        await session_manager.stop()

        mock_client.disconnect.assert_called_once()
        assert session_manager._sessions == {}
        assert session_manager._active_session is None
        assert session_manager._running is False

    @pytest.mark.asyncio
    async def test_stop_handles_disconnect_error(
        self, session_manager: SessionManager, mock_client: MagicMock
    ) -> None:
        """Test stop handles disconnect errors gracefully."""
        mock_client.disconnect = AsyncMock(side_effect=Exception("Disconnect failed"))
        session_manager._sessions["127.0.0.1:50000"] = mock_client
        session_manager._running = True

        # Should not raise
        await session_manager.stop()

        assert session_manager._sessions == {}


# ============================================================================
# Scan Tests
# ============================================================================


class TestScanForSessions:
    """Test _scan_for_sessions method."""

    @pytest.mark.asyncio
    async def test_scan_discovers_sessions(
        self, session_manager: SessionManager, mock_client: MagicMock, mocker
    ) -> None:
        """Test scanning discovers new sessions."""
        mocker.patch(
            "maya_mcp_server.session_manager.get_maya_listening_ports",
            return_value=[
                {"address": "127.0.0.1", "port": 7001, "process_id": 12345},
            ],
        )
        mocker.patch.object(
            session_manager, "_probe_port", new_callable=AsyncMock, return_value=mock_client
        )

        await session_manager._scan_for_sessions()

        assert "127.0.0.1:50000" in session_manager._sessions
        assert session_manager._config_to_session["127.0.0.1:7001"] == "127.0.0.1:50000"

    @pytest.mark.asyncio
    async def test_scan_skips_communication_ports(
        self, session_manager: SessionManager, mocker
    ) -> None:
        """Test scanning skips ports in communication range."""
        mock_probe = mocker.patch.object(
            session_manager, "_probe_port", new_callable=AsyncMock
        )
        mocker.patch(
            "maya_mcp_server.session_manager.get_maya_listening_ports",
            return_value=[
                {"address": "127.0.0.1", "port": 50500, "process_id": 12345},  # In range
                {"address": "127.0.0.1", "port": 55000, "process_id": 12345},  # In range
            ],
        )

        await session_manager._scan_for_sessions()

        mock_probe.assert_not_called()

    @pytest.mark.asyncio
    async def test_scan_skips_already_probed_config_ports(
        self, session_manager: SessionManager, mock_client: MagicMock, mocker
    ) -> None:
        """Test scanning skips config ports already used."""
        session_manager._config_to_session["127.0.0.1:7001"] = "127.0.0.1:50000"
        mock_probe = mocker.patch.object(
            session_manager, "_probe_port", new_callable=AsyncMock
        )
        mocker.patch(
            "maya_mcp_server.session_manager.get_maya_listening_ports",
            return_value=[
                {"address": "127.0.0.1", "port": 7001, "process_id": 12345},
            ],
        )

        await session_manager._scan_for_sessions()

        mock_probe.assert_not_called()

    @pytest.mark.asyncio
    async def test_scan_handles_probe_failure(
        self, session_manager: SessionManager, mocker
    ) -> None:
        """Test scanning handles probe failures gracefully."""
        mocker.patch.object(
            session_manager, "_probe_port", new_callable=AsyncMock, return_value=None
        )
        mocker.patch(
            "maya_mcp_server.session_manager.get_maya_listening_ports",
            return_value=[
                {"address": "127.0.0.1", "port": 7001, "process_id": 12345},
            ],
        )

        await session_manager._scan_for_sessions()

        assert session_manager.session_count == 0


# ============================================================================
# Probe Port Tests
# ============================================================================


class TestProbePort:
    """Test _probe_port method."""

    @pytest.mark.asyncio
    async def test_probe_port_success(
        self, session_manager: SessionManager, mock_client: MagicMock, mocker
    ) -> None:
        """Test successful port probing."""
        mock_maya_client = MagicMock(spec=MayaClient)
        mock_maya_client.connect = AsyncMock()
        mock_maya_client.disconnect = AsyncMock()
        mock_maya_client.bootstrap = AsyncMock(return_value=mock_client)

        mocker.patch(
            "maya_mcp_server.session_manager.MayaClient", return_value=mock_maya_client
        )

        result = await session_manager._probe_port("127.0.0.1", 7001)

        assert result is mock_client
        mock_maya_client.connect.assert_called_once()
        mock_maya_client.bootstrap.assert_called_once_with(client_type="qt")
        mock_maya_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_probe_port_connection_error(
        self, session_manager: SessionManager, mocker
    ) -> None:
        """Test probe returns None on connection error."""
        mock_maya_client = MagicMock(spec=MayaClient)
        mock_maya_client.connect = AsyncMock(
            side_effect=MayaConnectionError("Connection refused")
        )

        mocker.patch(
            "maya_mcp_server.session_manager.MayaClient", return_value=mock_maya_client
        )

        result = await session_manager._probe_port("127.0.0.1", 7001)

        assert result is None

    @pytest.mark.asyncio
    async def test_probe_port_other_error(
        self, session_manager: SessionManager, mocker
    ) -> None:
        """Test probe returns None on other errors and disconnects."""
        mock_maya_client = MagicMock(spec=MayaClient)
        mock_maya_client.connect = AsyncMock()
        mock_maya_client.bootstrap = AsyncMock(side_effect=RuntimeError("Unexpected error"))
        mock_maya_client.disconnect = AsyncMock()

        mocker.patch(
            "maya_mcp_server.session_manager.MayaClient", return_value=mock_maya_client
        )

        result = await session_manager._probe_port("127.0.0.1", 7001)

        assert result is None
        mock_maya_client.disconnect.assert_called_once()


# ============================================================================
# Prune Tests
# ============================================================================


class TestPruneDeadSessions:
    """Test _prune_dead_sessions method."""

    @pytest.mark.asyncio
    async def test_prune_removes_dead_sessions(
        self, session_manager: SessionManager
    ) -> None:
        """Test pruning removes sessions that don't respond to ping."""
        dead_client = MagicMock()
        dead_client.key = "127.0.0.1:50000"
        dead_client.ping = AsyncMock(return_value=False)
        dead_client.disconnect = AsyncMock()

        session_manager._sessions["127.0.0.1:50000"] = dead_client
        session_manager._config_to_session["127.0.0.1:7001"] = "127.0.0.1:50000"

        await session_manager._prune_dead_sessions()

        assert "127.0.0.1:50000" not in session_manager._sessions
        assert "127.0.0.1:7001" not in session_manager._config_to_session
        dead_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_prune_keeps_alive_sessions(
        self, session_manager: SessionManager, mock_client: MagicMock
    ) -> None:
        """Test pruning keeps sessions that respond to ping."""
        session_manager._sessions["127.0.0.1:50000"] = mock_client
        session_manager._config_to_session["127.0.0.1:7001"] = "127.0.0.1:50000"

        await session_manager._prune_dead_sessions()

        assert "127.0.0.1:50000" in session_manager._sessions

    @pytest.mark.asyncio
    async def test_prune_clears_active_session_if_dead(
        self, session_manager: SessionManager
    ) -> None:
        """Test pruning clears active session if it's dead."""
        dead_client = MagicMock()
        dead_client.key = "127.0.0.1:50000"
        dead_client.ping = AsyncMock(return_value=False)
        dead_client.disconnect = AsyncMock()

        session_manager._sessions["127.0.0.1:50000"] = dead_client
        session_manager._active_session = dead_client

        await session_manager._prune_dead_sessions()

        assert session_manager.active_session is None

    @pytest.mark.asyncio
    async def test_prune_handles_ping_exception(
        self, session_manager: SessionManager
    ) -> None:
        """Test pruning handles ping exceptions as dead sessions."""
        error_client = MagicMock()
        error_client.key = "127.0.0.1:50000"
        error_client.ping = AsyncMock(side_effect=Exception("Connection lost"))
        error_client.disconnect = AsyncMock()

        session_manager._sessions["127.0.0.1:50000"] = error_client

        await session_manager._prune_dead_sessions()

        assert "127.0.0.1:50000" not in session_manager._sessions


# ============================================================================
# List Sessions Tests
# ============================================================================


class TestListSessions:
    """Test list_sessions method."""

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, session_manager: SessionManager) -> None:
        """Test list_sessions returns empty list when no sessions."""
        result = await session_manager.list_sessions()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_sessions_returns_info(
        self, session_manager: SessionManager, mock_client: MagicMock
    ) -> None:
        """Test list_sessions returns session info."""
        session_manager._sessions["127.0.0.1:50000"] = mock_client

        result = await session_manager.list_sessions()

        assert len(result) == 1
        assert result[0].host == "127.0.0.1"
        assert result[0].port == 50000
        assert result[0].pid == 12345

    @pytest.mark.asyncio
    async def test_list_sessions_handles_error(
        self, session_manager: SessionManager
    ) -> None:
        """Test list_sessions handles session_info errors."""
        error_client = MagicMock()
        error_client.key = "127.0.0.1:50000"
        error_client.session_info = AsyncMock(side_effect=Exception("Connection lost"))

        session_manager._sessions["127.0.0.1:50000"] = error_client

        result = await session_manager.list_sessions()

        # Should return empty list (error is logged, session will be pruned later)
        assert result == []


# ============================================================================
# Get Session Tests
# ============================================================================


class TestGetSession:
    """Test get_session method."""

    @pytest.mark.asyncio
    async def test_get_session_found(
        self, session_manager: SessionManager, mock_client: MagicMock
    ) -> None:
        """Test get_session returns client when found."""
        session_manager._sessions["127.0.0.1:50000"] = mock_client

        result = await session_manager.get_session("127.0.0.1", 50000)

        assert result is mock_client

    @pytest.mark.asyncio
    async def test_get_session_not_found(
        self, session_manager: SessionManager
    ) -> None:
        """Test get_session returns None when not found."""
        result = await session_manager.get_session("127.0.0.1", 50000)
        assert result is None


# ============================================================================
# Use Session Tests
# ============================================================================


class TestUseSession:
    """Test use_session method."""

    @pytest.mark.asyncio
    async def test_use_session_existing(
        self, session_manager: SessionManager, mock_client: MagicMock
    ) -> None:
        """Test use_session with existing session."""
        session_manager._sessions["127.0.0.1:50000"] = mock_client

        result = await session_manager.use_session("127.0.0.1", 50000)

        assert result is mock_client
        assert session_manager.active_session is mock_client
        mock_client.install_stream_capture.assert_called_once()

    @pytest.mark.asyncio
    async def test_use_session_switches_sessions(
        self, session_manager: SessionManager
    ) -> None:
        """Test use_session switches between sessions."""
        old_client = MagicMock()
        old_client.key = "127.0.0.1:50001"
        old_client.uninstall_stream_capture = AsyncMock()

        new_client = MagicMock()
        new_client.key = "127.0.0.1:50000"
        new_client.install_stream_capture = AsyncMock()

        session_manager._sessions["127.0.0.1:50001"] = old_client
        session_manager._sessions["127.0.0.1:50000"] = new_client
        session_manager._active_session = old_client

        await session_manager.use_session("127.0.0.1", 50000)

        old_client.uninstall_stream_capture.assert_called_once()
        new_client.install_stream_capture.assert_called_once()
        assert session_manager.active_session is new_client

    @pytest.mark.asyncio
    async def test_use_session_connects_new(
        self, session_manager: SessionManager, mock_client: MagicMock, mocker
    ) -> None:
        """Test use_session connects to new session if not found."""
        mock_maya_client = MagicMock(spec=MayaClient)
        mock_maya_client.connect = AsyncMock()
        mock_maya_client.bootstrap = AsyncMock()
        mock_maya_client.install_stream_capture = AsyncMock()
        mock_maya_client.key = "127.0.0.1:7001"

        mocker.patch(
            "maya_mcp_server.session_manager.MayaClient", return_value=mock_maya_client
        )

        result = await session_manager.use_session("127.0.0.1", 7001)

        assert result is mock_maya_client
        mock_maya_client.connect.assert_called_once()
        mock_maya_client.bootstrap.assert_called_once()

    @pytest.mark.asyncio
    async def test_use_session_connect_fails(
        self, session_manager: SessionManager, mocker
    ) -> None:
        """Test use_session raises ValueError on connection failure."""
        mock_maya_client = MagicMock(spec=MayaClient)
        mock_maya_client.connect = AsyncMock(
            side_effect=MayaConnectionError("Connection refused")
        )

        mocker.patch(
            "maya_mcp_server.session_manager.MayaClient", return_value=mock_maya_client
        )

        with pytest.raises(ValueError, match="Cannot connect to session"):
            await session_manager.use_session("127.0.0.1", 7001)

    @pytest.mark.asyncio
    async def test_use_session_handles_stream_capture_error(
        self, session_manager: SessionManager
    ) -> None:
        """Test use_session handles stream capture installation errors."""
        client = MagicMock()
        client.key = "127.0.0.1:50000"
        client.install_stream_capture = AsyncMock(
            side_effect=Exception("Stream capture failed")
        )

        session_manager._sessions["127.0.0.1:50000"] = client

        # Should not raise, just log warning
        result = await session_manager.use_session("127.0.0.1", 50000)

        assert result is client


# ============================================================================
# Unuse Session Tests
# ============================================================================


class TestUnuseSession:
    """Test unuse_session method."""

    @pytest.mark.asyncio
    async def test_unuse_session(
        self, session_manager: SessionManager, mock_client: MagicMock
    ) -> None:
        """Test unuse_session deactivates session."""
        session_manager._active_session = mock_client

        await session_manager.unuse_session()

        assert session_manager.active_session is None
        mock_client.uninstall_stream_capture.assert_called_once()

    @pytest.mark.asyncio
    async def test_unuse_session_no_active(
        self, session_manager: SessionManager
    ) -> None:
        """Test unuse_session does nothing when no active session."""
        await session_manager.unuse_session()
        assert session_manager.active_session is None

    @pytest.mark.asyncio
    async def test_unuse_session_handles_error(
        self, session_manager: SessionManager
    ) -> None:
        """Test unuse_session handles uninstall errors."""
        client = MagicMock()
        client.key = "127.0.0.1:50000"
        client.uninstall_stream_capture = AsyncMock(
            side_effect=Exception("Uninstall failed")
        )

        session_manager._active_session = client

        # Should not raise
        await session_manager.unuse_session()

        assert session_manager.active_session is None


# ============================================================================
# Add Session Tests
# ============================================================================


class TestAddSession:
    """Test add_session method."""

    @pytest.mark.asyncio
    async def test_add_session_new(
        self, session_manager: SessionManager, mocker
    ) -> None:
        """Test adding a new session."""
        mock_maya_client = MagicMock(spec=MayaClient)
        mock_maya_client.connect = AsyncMock()
        mock_maya_client.bootstrap = AsyncMock()
        mock_maya_client.key = "127.0.0.1:7001"

        mocker.patch(
            "maya_mcp_server.session_manager.MayaClient", return_value=mock_maya_client
        )

        result = await session_manager.add_session("127.0.0.1", 7001)

        assert result is mock_maya_client
        assert "127.0.0.1:7001" in session_manager._sessions
        mock_maya_client.connect.assert_called_once()
        mock_maya_client.bootstrap.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_session_existing(
        self, session_manager: SessionManager, mock_client: MagicMock
    ) -> None:
        """Test adding existing session returns it without reconnecting."""
        session_manager._sessions["127.0.0.1:50000"] = mock_client

        result = await session_manager.add_session("127.0.0.1", 50000)

        assert result is mock_client
        mock_client.connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_session_connection_fails(
        self, session_manager: SessionManager, mocker
    ) -> None:
        """Test add_session raises on connection failure."""
        mock_maya_client = MagicMock(spec=MayaClient)
        mock_maya_client.connect = AsyncMock(
            side_effect=MayaConnectionError("Connection refused")
        )

        mocker.patch(
            "maya_mcp_server.session_manager.MayaClient", return_value=mock_maya_client
        )

        with pytest.raises(MayaConnectionError):
            await session_manager.add_session("127.0.0.1", 7001)
