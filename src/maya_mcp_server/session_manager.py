"""Session manager for multiple Maya connections."""

from __future__ import annotations

import asyncio
import logging

from maya_mcp_server.client import BaseMayaClient, MayaClient, MayaConnectionError
from maya_mcp_server.types import (
    COMMUNICATION_PORT_MAX,
    COMMUNICATION_PORT_MIN,
    ClientType,
    SessionInfo,
)
from maya_mcp_server.utils import get_maya_listening_ports


logger = logging.getLogger(__name__)


class SessionManager:
    """Manages multiple Maya session connections."""

    def __init__(
        self,
        scan_interval: float = 10.0,
        client_type: ClientType = ClientType.QT,
    ):
        """
        Initialize the session manager.

        Args:
            scan_interval: Seconds between background scans
            client_type: Type of client to use for Maya communication
        """
        self.scan_interval = scan_interval
        self.client_type = client_type
        # key: "host:port" (communication port)
        self._sessions: dict[str, BaseMayaClient] = {}
        # map config key -> session key
        #   we use a "config" command port to bootstrap a dedicated communication port, and only
        #   the latter are considered "sessions"
        self._config_to_session: dict[str, str] = {}
        # session keys with stream capture
        self._stream_capture_installed: set[str] = set()
        self._scan_task: asyncio.Task[None] | None = None
        self._running = False

    def _session_key(self, host: str, port: int) -> str:
        """Generate unique key for a session."""
        return f"{host}:{port}"

    async def start(self) -> None:
        """Start the session manager and begin background scanning."""
        if self._running:
            return

        self._running = True
        logger.info(f"Starting session manager (client_type={self.client_type.value})")

        # Do initial scan
        await self._scan_for_sessions()

        # Start background scanning task
        self._scan_task = asyncio.create_task(self._background_scan())

    async def stop(self) -> None:
        """Stop scanning and disconnect all sessions."""
        self._running = False

        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
            self._scan_task = None

        # Disconnect all sessions
        for client in self._sessions.values():
            try:
                await client.disconnect()
            except Exception as e:
                logger.debug(f"Error disconnecting client: {e}")

        self._sessions.clear()
        self._config_to_session.clear()
        self._stream_capture_installed.clear()
        logger.info("Session manager stopped")

    async def _background_scan(self) -> None:
        """Periodically scan for new sessions and prune dead ones."""
        while self._running:
            try:
                await asyncio.sleep(self.scan_interval)
                await self._scan_for_sessions()
                await self._prune_dead_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in background scan: {e}")

    async def _scan_for_sessions(self) -> None:
        """Scan for Maya sessions using actual listening ports.

        Only scans configuration ports (outside the communication port range).
        Communication ports are per-client dedicated ports created during bootstrap.
        """
        for port_info in get_maya_listening_ports():
            host = port_info["address"]
            port = port_info["port"]
            config_key = self._session_key(host, port)

            # Skip communication ports (dedicated per-client ports)
            if COMMUNICATION_PORT_MIN <= port <= COMMUNICATION_PORT_MAX:
                continue

            # Skip if we've already used this configuration port to create a session
            if config_key in self._config_to_session:
                continue

            # Try to connect to this configuration port
            client = await self._probe_port(host, port)
            if client:
                # Store session by its communication port key
                self._sessions[client.key] = client
                # Track which config port created this session
                self._config_to_session[config_key] = client.key
                logger.info(
                    f"Discovered Maya session at {client.key} (PID {port_info['process_id']})"
                )

    async def _probe_port(self, host: str, port: int) -> BaseMayaClient | None:
        """
        Probe a port to check if it's a Maya command port.

        Args:
            host: Host to connect to
            port: Port to probe

        Returns:
            MayaClient if successful, None otherwise
        """
        # Use longer timeout to support long-running operations
        client = MayaClient(host, port, timeout=60.0)

        try:
            await client.connect()
            new_client = await client.bootstrap(client_type=self.client_type.value)
            await client.disconnect()
            return new_client
        except MayaConnectionError:
            return None
        except Exception as e:
            logger.debug(f"Error probing {host}:{port}: {e}")
            try:
                await client.disconnect()
            except Exception:
                pass
            return None

    async def _prune_dead_sessions(self) -> None:
        """Remove sessions that are no longer responding."""
        dead_keys = []

        for key, client in self._sessions.items():
            try:
                if not await client.ping():
                    dead_keys.append(key)
            except Exception:
                dead_keys.append(key)

        for session_key in dead_keys:
            client = self._sessions.pop(session_key)
            logger.info(f"Pruned dead session: {session_key}")

            # Remove from config mapping
            config_key = None
            for cfg_key, sess_key in self._config_to_session.items():
                if sess_key == session_key:
                    config_key = cfg_key
                    break
            if config_key:
                del self._config_to_session[config_key]

            # Remove from stream capture tracking
            self._stream_capture_installed.discard(session_key)

            try:
                await client.disconnect()
            except Exception:
                pass

    async def list_sessions(self) -> list[SessionInfo]:
        """
        List all running Maya sessions.

        Returns:
            List of key properties about each session
        """
        results: list[SessionInfo] = []

        for key, client in list(self._sessions.items()):
            try:
                info = await client.session_info()
                results.append(info)
            except Exception as e:
                logger.debug(f"Error getting session info for {key}: {e}")
                # Session might have closed, will be pruned on next scan

        return results

    async def get_session(self, host: str, port: int) -> BaseMayaClient | None:
        """
        Get a session by host and port.

        Args:
            host: Session host
            port: Session port

        Returns:
            MayaClient if found, None otherwise
        """
        key = self._session_key(host, port)
        return self._sessions.get(key)

    async def get_client(self, session_key: str | None = None) -> BaseMayaClient:
        """
        Get a client for the specified session, with auto-selection.

        Args:
            session_key: Session key. If None and only one session exists, auto-selects it.

        Returns:
            The MayaClient for the session

        Raises:
            ValueError: If no sessions exist, multiple sessions exist without
                        explicit selection, or the specified session is not found.

        Stream capture is automatically installed on first access to each session.
        """
        # Auto-select if only one session and no explicit host:port
        client: BaseMayaClient
        if session_key is None:
            if len(self._sessions) == 0:
                raise ValueError("No Maya sessions available. Use add_session first.")
            elif len(self._sessions) == 1:
                client = next(iter(self._sessions.values()))
            else:
                session_keys = list(self._sessions.keys())
                raise ValueError(
                    f"Multiple sessions available: {session_keys}. "
                    "Specify host and port explicitly."
                )
        else:
            maybe_client = self._sessions.get(session_key)
            if maybe_client is None:
                raise ValueError(f"Session {session_key} not found")
            client = maybe_client

        # Auto-install stream capture on first access
        if client.key not in self._stream_capture_installed:
            try:
                await client.install_stream_capture()
                self._stream_capture_installed.add(client.key)
            except Exception as e:
                logger.warning(f"Failed to install stream capture for {client.key}: {e}")

        return client

    @property
    def session_count(self) -> int:
        """Get the number of connected sessions."""
        return len(self._sessions)

    async def add_session(self, host: str, port: int) -> BaseMayaClient:
        """
        Manually add a session at a specific host:port.

        Args:
            host: Session host
            port: Session port

        Returns:
            The connected MayaClient

        Raises:
            MayaConnectionError: If connection fails
        """
        key = self._session_key(host, port)

        if key in self._sessions:
            return self._sessions[key]

        client = MayaClient(host, port)
        await client.connect()
        await client.bootstrap()

        self._sessions[key] = client
        logger.info(f"Added session: {key}")

        return client


if __name__ == "__main__":
    cmd = """
import maya.cmds
print('one')
print('two')
maya.cmds.ls(cameras=True)
"""

    async def run() -> None:
        session_manager = SessionManager()
        print("starting")
        await session_manager.start()
        print("started")
        result = await session_manager.list_sessions()
        print(result)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
