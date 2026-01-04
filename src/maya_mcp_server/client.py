"""Maya client for communicating with Maya command ports."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from maya_mcp_server.bootstrap import (
    BOOTSTRAP_CODE,
    CHECK_BOOTSTRAP,
    CREATE_MODULE_TEMPLATE,
    EXECUTE_TEMPLATE,
    GET_BUFFERED_OUTPUT,
    GET_SESSION_INFO,
    INSTALL_STREAM_CAPTURE,
    UNINSTALL_STREAM_CAPTURE,
)
from maya_mcp_server.types import ExecutionResult, PortType, ResultType, SessionInfo

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class MayaConnectionError(Exception):
    """Error connecting to Maya."""

    pass


class MayaExecutionError(Exception):
    """Error executing code in Maya."""

    pass


class MayaClient:
    """Async client for communicating with a Maya command port."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7001,
        timeout: float = 30.0,
        buffer_size: int = 65536,
    ):
        """
        Initialize a Maya client.

        Args:
            host: Maya host address
            port: Maya command port number
            timeout: Default timeout for operations in seconds
            buffer_size: Socket buffer size
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self.buffer_size = buffer_size
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._bootstrapped = False
        self._session_info: SessionInfo | None = None
        self._port_type: PortType = PortType.UNKNOWN
        self._lock = asyncio.Lock()

    @property
    def key(self) -> str:
        """Unique key for the session."""
        return f"{self.host}:{self.port}"

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        """
        Establish connection to Maya command port.

        Raises:
            MayaConnectionError: If connection fails
        """
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
            logger.info(f"Connected to Maya at {self.host}:{self.port}")
        except asyncio.TimeoutError as e:
            raise MayaConnectionError(
                f"Timeout connecting to Maya at {self.host}:{self.port}"
            ) from e
        except OSError as e:
            raise MayaConnectionError(
                f"Failed to connect to Maya at {self.host}:{self.port}: {e}"
            ) from e

    async def disconnect(self) -> None:
        """Close connection to Maya."""
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None
            self._bootstrapped = False
            logger.info(f"Disconnected from Maya at {self.host}:{self.port}")

    async def _send_receive(self, data: str) -> str:
        """
        Send data to Maya and receive response.

        Maya command port expects commands and returns results terminated
        with newline + null byte.

        Args:
            data: Command string to send

        Returns:
            Response string from Maya

        Raises:
            MayaConnectionError: If not connected
            MayaExecutionError: If communication fails
        """
        if not self._writer or not self._reader:
            raise MayaConnectionError("Not connected to Maya")

        async with self._lock:
            try:
                # Send command
                self._writer.write(data.encode("utf-8"))
                await self._writer.drain()

                # Read response until null terminator
                response_bytes = b""
                while True:
                    chunk = await asyncio.wait_for(
                        self._reader.read(self.buffer_size),
                        timeout=self.timeout,
                    )
                    if not chunk:
                        break
                    response_bytes += chunk
                    # Maya terminates responses with \n\x00
                    if response_bytes.endswith(b"\x00"):
                        break

                # Decode and strip terminator
                response = response_bytes.decode("utf-8").rstrip("\x00").rstrip("\n")
                return response

            except asyncio.TimeoutError as e:
                raise MayaExecutionError("Timeout waiting for Maya response") from e
            except Exception as e:
                raise MayaExecutionError(f"Error communicating with Maya: {e}") from e

    async def detect_port_type(self) -> PortType:
        """
        Detect whether the command port speaks MEL or Python.

        Returns:
            PortType indicating the port's language
        """
        if self._port_type != PortType.UNKNOWN:
            return self._port_type

        try:
            # Try a simple Python expression
            response = await self._send_receive("1+1")

            # If we get "2" back, it's Python
            if response.strip() == "2":
                self._port_type = PortType.PYTHON
            else:
                # Likely MEL - would return an error or different format
                self._port_type = PortType.MEL

        except Exception:
            self._port_type = PortType.UNKNOWN

        logger.info(f"Detected port type: {self._port_type.value}")
        return self._port_type

    async def bootstrap(self) -> None:
        """
        Bootstrap the Maya session with helper functions.

        This creates the _mcp module in Maya's sys.modules,
        providing utilities for code execution with capture.
        """
        if self._bootstrapped:
            return

        port_type = await self.detect_port_type()
        if port_type != PortType.PYTHON:
            raise MayaConnectionError(
                f"Cannot bootstrap non-Python port (detected: {port_type.value})"
            )

        # Check if already bootstrapped (e.g., from previous connection)
        check_result = await self._send_receive(CHECK_BOOTSTRAP)
        if check_result.strip() == "True":
            self._bootstrapped = True
            logger.info("Maya session already bootstrapped")
            return

        # Execute bootstrap code using exec() with globals() to persist definitions
        # Maya command port runs each command in isolated scope, so we must use
        # exec(..., globals()) to make the code affect the global namespace
        bootstrap_cmd = f"exec({BOOTSTRAP_CODE!r}, globals())"
        await self._send_receive(bootstrap_cmd)
        self._bootstrapped = True
        logger.info("Maya session bootstrapped")

    async def session_info(self) -> SessionInfo:
        """
        Get information about the connected Maya session.

        Returns:
            SessionInfo with pid, user, maya version, current scene, etc.
        """
        if not self._bootstrapped:
            await self.bootstrap()

        response = await self._send_receive(GET_SESSION_INFO)
        info = json.loads(response)

        # Add connection info
        info["host"] = self.host
        info["port"] = self.port

        self._session_info = info
        return info

    async def write_module(
        self,
        name: str,
        code: str,
        overwrite: bool = False,
    ) -> str:
        """
        Create a virtual Python module in the Maya session.

        Args:
            name: Module name (can be dotted path like 'mypackage.mymodule')
            code: Python source code for the module
            overwrite: If True, replace existing module; else raise error

        Returns:
            Success message

        Raises:
            MayaExecutionError: If module creation fails
        """
        if not self._bootstrapped:
            await self.bootstrap()

        cmd = CREATE_MODULE_TEMPLATE.format(name=name, code=code, overwrite=overwrite)
        response = await self._send_receive(cmd)

        result = json.loads(response)
        if "error" in result and result["error"]:
            raise MayaExecutionError(result["error"])

        return result.get("message", f"Module '{name}' created")

    async def execute_code(
        self,
        code: str,
        result_type: ResultType = ResultType.NONE,
    ) -> ExecutionResult:
        """
        Execute Python code in Maya and return the result.

        Args:
            code: Python code to execute
            result_type: How to handle the result
                - NONE: Execute statements, don't capture result
                - JSON: Evaluate expression, JSON encode result
                - RAW: Evaluate expression, return string representation

        Returns:
            ExecutionResult with result and error info.
            Note: stdout/stderr are delivered via MCP Resources, not returned here.
        """
        if not self._bootstrapped:
            await self.bootstrap()

        cmd = EXECUTE_TEMPLATE.format(code=code, result_type=result_type.value)
        response = await self._send_receive(cmd)

        result: ExecutionResult = json.loads(response)

        # Decode JSON result if needed
        if result_type == ResultType.JSON and result.get("result") is not None:
            try:
                result["result"] = json.loads(result["result"])
            except json.JSONDecodeError:
                pass  # Keep as string if not valid JSON

        return result

    async def install_stream_capture(self) -> None:
        """
        Install stream capture for stdout/stderr in Maya.

        This redirects stdout/stderr through custom writers that buffer
        output for retrieval via get_buffered_output().
        """
        if not self._bootstrapped:
            await self.bootstrap()

        await self._send_receive(INSTALL_STREAM_CAPTURE)
        logger.debug(f"Stream capture installed for {self.host}:{self.port}")

    async def uninstall_stream_capture(self) -> None:
        """
        Remove stream capture and restore original stdout/stderr in Maya.
        """
        if not self._bootstrapped:
            return

        await self._send_receive(UNINSTALL_STREAM_CAPTURE)
        logger.debug(f"Stream capture uninstalled for {self.host}:{self.port}")

    async def get_buffered_output(self) -> dict[str, str]:
        """
        Get buffered stdout/stderr content and clear the buffers.

        Returns:
            Dict with "stdout" and "stderr" keys containing captured output.
        """
        if not self._bootstrapped:
            await self.bootstrap()

        response = await self._send_receive(GET_BUFFERED_OUTPUT)
        return json.loads(response)

    async def ping(self) -> bool:
        """
        Check if the Maya connection is alive.

        Returns:
            True if Maya responds, False otherwise
        """
        try:
            response = await self._send_receive("1+1")
            return response.strip() == "2"
        except Exception:
            return False

    async def __aenter__(self) -> "MayaClient":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[no-untyped-def]
        """Async context manager exit."""
        await self.disconnect()
