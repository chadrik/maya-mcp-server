"""Session manager for multiple Maya connections."""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from maya_mcp_server.client import MayaClient, MayaConnectionError
from maya_mcp_server.types import PortType, SessionInfo
from maya_mcp_server.utils import get_maya_listening_ports

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages multiple Maya session connections."""

    def __init__(
        self,
        scan_interval: float = 10.0,
    ):
        """
        Initialize the session manager.

        Args:
            scan_interval: Seconds between background scans
        """
        self.scan_interval = scan_interval
        self._sessions: dict[str, MayaClient] = {}  # key: "host:port"
        self._active_session: MayaClient | None = None
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
        logger.info("Starting session manager")

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
        self._active_session = None
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
        """Scan for Maya sessions using actual listening ports."""
        listening_ports = get_maya_listening_ports()
        logger.debug(f"Found Maya listening on {len(listening_ports)} port(s)")

        for port_info in listening_ports:
            host = port_info['address']
            port = port_info['port']
            key = self._session_key(host, port)

            # Skip if we already have this session
            if key in self._sessions:
                continue

            # Try to connect
            client = await self._probe_port(host, port)
            if client:
                self._sessions[key] = client
                logger.info(f"Discovered Maya session at {key}")

    async def _probe_port(self, host: str, port: int) -> MayaClient | None:
        """
        Probe a port to check if it's a Maya command port.

        Args:
            host: Host to connect to
            port: Port to probe

        Returns:
            MayaClient if successful, None otherwise
        """
        client = MayaClient(host, port, timeout=5.0)

        try:
            await client.connect()

            # Detect port type
            port_type = await client.detect_port_type()

            if port_type == PortType.PYTHON:
                # Bootstrap the session
                await client.bootstrap()
                return client

            elif port_type == PortType.MEL:
                # Try to open a Python port via MEL
                python_port = port + 1000  # Convention: Python port = MEL port + 1000
                mel_cmd = (
                    f'python("import maya.cmds as cmds; '
                    f"cmds.commandPort(name=':{python_port}', sourceType='python')\")"
                )

                try:
                    await client._send_receive(mel_cmd)
                    await client.disconnect()

                    # Connect to the new Python port
                    python_client = MayaClient(host, python_port, timeout=5.0)
                    await python_client.connect()
                    await python_client.bootstrap()
                    return python_client

                except Exception as e:
                    logger.debug(f"Failed to open Python port via MEL: {e}")
                    await client.disconnect()
                    return None

            else:
                await client.disconnect()
                return None

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

        for key in dead_keys:
            client = self._sessions.pop(key)
            logger.info(f"Pruned dead session: {key}")

            # If this was the active session, clear it
            if self._active_session is client:
                self._active_session = None

            try:
                await client.disconnect()
            except Exception:
                pass

    async def list_sessions(self) -> list[SessionInfo]:
        """
        List all active sessions with their info.

        Returns:
            List of SessionInfo dictionaries
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

    async def get_session(self, host: str, port: int) -> MayaClient | None:
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

    async def use_session(self, host: str, port: int) -> MayaClient:
        """
        Activate a session for subsequent operations.

        Args:
            host: Session host
            port: Session port

        Returns:
            The activated MayaClient

        Raises:
            ValueError: If session not found

        Also installs stream capture for stdout/stderr, which can be
        retrieved via get_buffered_output() for MCP Resource streaming.
        """
        key = self._session_key(host, port)

        if key not in self._sessions:
            # Try to connect directly
            client = MayaClient(host, port)
            try:
                await client.connect()
                await client.bootstrap()
                self._sessions[key] = client
            except Exception as e:
                raise ValueError(f"Cannot connect to session {key}: {e}") from e

        # Deactivate previous session if any
        if self._active_session is not None and self._active_session.key != key:
            try:
                await self._active_session.uninstall_stream_capture()
            except Exception as e:
                logger.debug(f"Error uninstalling stream capture: {e}")

        self._active_session = self._sessions[key]

        # Install stream capture for the new active session
        try:
            await self._active_session.install_stream_capture()
        except Exception as e:
            logger.warning(f"Failed to install stream capture: {e}")

        logger.info(f"Activated session: {key}")
        return self._active_session

    async def unuse_session(self) -> None:
        """
        Deactivate the current session and release resources.

        Uninstalls stream capture and clears the active session.
        """
        if self._active_session is None:
            return

        old_key = self._active_session.key

        try:
            await self._active_session.uninstall_stream_capture()
        except Exception as e:
            logger.debug(f"Error uninstalling stream capture: {e}")

        self._active_session = None
        logger.info(f"Deactivated session: {old_key}")

    @property
    def active_session(self) -> MayaClient | None:
        """Get the currently active session."""
        return self._active_session

    @property
    def session_count(self) -> int:
        """Get the number of connected sessions."""
        return len(self._sessions)

    async def add_session(self, host: str, port: int) -> MayaClient:
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
