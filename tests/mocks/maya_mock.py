"""Mock Maya command port server for testing."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

logger = logging.getLogger(__name__)


class MockMayaServer:
    """Mock Maya command port server for testing."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7002,
        source_type: str = "python",
    ):
        """
        Initialize mock server.

        Args:
            host: Host to listen on
            port: Port to listen on
            source_type: "python" or "mel"
        """
        self.host = host
        self.port = port
        self.source_type = source_type
        self._server: asyncio.Server | None = None
        self._responses: dict[str, str] = {}
        self._handler: Callable[[str], str] | None = None
        self._bootstrapped = False
        self._globals: dict[str, object] = {}

    async def start(self) -> None:
        """Start the mock server."""
        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port,
        )
        logger.info(f"Mock Maya server listening on {self.host}:{self.port}")

    async def stop(self) -> None:
        """Stop the mock server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("Mock Maya server stopped")

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle incoming client connections."""
        try:
            while True:
                # Read command
                data = await reader.read(65536)
                if not data:
                    break

                command = data.decode("utf-8").strip()
                logger.debug(f"Mock received: {command!r}")

                # Process command
                response = self._process_command(command)
                logger.debug(f"Mock response: {response!r}")

                # Send response with Maya's terminator
                writer.write(response.encode("utf-8") + b"\n\x00")
                await writer.drain()

        except Exception as e:
            logger.debug(f"Mock client error: {e}")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    def _process_command(self, command: str) -> str:
        """Process a command and return response."""
        # Check custom responses
        if command in self._responses:
            return self._responses[command]

        # Check custom handler
        if self._handler:
            return self._handler(command)

        # Default Python behavior
        if self.source_type == "python":
            return self._execute_python(command)
        else:
            return self._execute_mel(command)

    def _execute_python(self, command: str) -> str:
        """Execute Python code and return result."""
        try:
            # Check if it's bootstrap code (contains class definition)
            if "class _MCPHelper" in command or "class _MCPStreamWriter" in command:
                # Don't actually execute bootstrap - just mark as bootstrapped
                self._bootstrapped = True
                return ""

            if "_mcp_helper.get_session_info()" in command:
                return json.dumps({
                    "pid": 12345,
                    "user": "testuser",
                    "maya_version": "2024",
                    "scene_name": "untitled",
                    "scene_path": "",
                })

            if "_mcp_helper.execute_with_capture(" in command:
                # Parse and execute the wrapped code
                # This is a simplified mock - just return success
                # Note: stdout/stderr are now delivered via MCP Resources, not here
                return json.dumps({
                    "result": None,
                    "error": None,
                })

            if "_mcp_helper.install_stream_capture()" in command:
                return ""

            if "_mcp_helper.uninstall_stream_capture()" in command:
                return ""

            if "_mcp_helper.get_buffered_output()" in command:
                return json.dumps({
                    "stdout": "",
                    "stderr": "",
                })

            if "_mcp_helper.create_module(" in command:
                return json.dumps({
                    "success": True,
                    "message": "Module created successfully",
                })

            # Simple expressions
            result = eval(command, self._globals)
            return str(result)

        except SyntaxError:
            # Try exec for statements
            try:
                exec(command, self._globals)
                return ""
            except Exception as e:
                return f"Error: {e}"
        except Exception as e:
            return f"Error: {e}"

    def _execute_mel(self, command: str) -> str:
        """Execute MEL command (mock)."""
        if command == "about -version":
            return "Maya 2024"
        return f"// Result: {command}"

    def set_response(self, command: str, response: str) -> None:
        """Set a custom response for a specific command."""
        self._responses[command] = response

    def set_handler(self, handler: Callable[[str], str]) -> None:
        """Set a custom command handler."""
        self._handler = handler

    async def __aenter__(self) -> "MockMayaServer":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[no-untyped-def]
        """Async context manager exit."""
        await self.stop()
