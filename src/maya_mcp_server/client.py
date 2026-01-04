"""Maya client for communicating with Maya command ports."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import TYPE_CHECKING, Self
from dataclasses import dataclass

from maya_mcp_server.bootstrap import (
    CHECK_BOOTSTRAP,
    CREATE_MODULE_TEMPLATE,
    EXECUTE_TEMPLATE,
    GET_BUFFERED_OUTPUT,
    GET_SESSION_INFO,
    INSTALL_STREAM_CAPTURE,
    START_QT_SERVER,
    UNINSTALL_STREAM_CAPTURE,
    START_COMMAND_PORT,
    get_bootstrap_code,
    get_helper_module_code,
)
from maya_mcp_server.types import (
    ExecutionResult,
    PortType,
    ResultType,
    SessionInfo,
    COMMUNICATION_PORT_MIN,
    COMMUNICATION_PORT_MAX,
)


if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class MayaConnectionError(Exception):
    """Error connecting to Maya."""

    pass


class MayaExecutionError(Exception):
    """Error executing code in Maya."""

    pass



@dataclass
class BaseMayaClient:
    host: str = "127.0.0.1"
    port: int = 7001
    timeout: float = 30.0
    buffer_size: int = 65536

    def __post_init__(self):
        """
        Initialize a Maya client.

        Args:
            host: Maya host address
            port: Maya command port number
            timeout: Default timeout for operations in seconds
            buffer_size: Socket buffer size
        """
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        # Output buffers for stdout/stderr capture
        self._stdout_buffer: str = ""
        self._stderr_buffer: str = ""

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
        # FIXME: shut down the maya command port running in Maya
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

    async def __aenter__(self) -> Self:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[no-untyped-def]
        """Async context manager exit."""
        await self.disconnect()


class MayaClient(BaseMayaClient):
    """Async client for communicating with a Maya command port."""

    def __post_init__(self):
        super().__post_init__()
        self._port_type: PortType = PortType.UNKNOWN

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

    async def _detect_port_type(self) -> PortType:
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

    async def bootstrap(self) -> MayaClient | None:
        """
        Bootstrap the Maya session with helper functions.

        This creates the _mcp module in Maya's sys.modules,
        providing utilities for code execution with capture.
        """
        port_type = await self._detect_port_type()

        if port_type != PortType.PYTHON:
            # TODO: support bootstrapping from a MEL command port
            raise MayaConnectionError(
                f"Cannot bootstrap non-Python port (detected: {port_type.value})"
            )

        # Check if already bootstrapped (e.g., from previous connection)
        check_result = await self._send_receive(CHECK_BOOTSTRAP)
        if check_result.strip() == "True":
            logger.info("Maya session already bootstrapped, updating module...")
            # Module exists, but update it to ensure it has latest functions
            helper_code = get_helper_module_code()
            cmd = CREATE_MODULE_TEMPLATE.format(name="maya_mcp", code=helper_code, overwrite=True)
            await self._send_receive(cmd)
            logger.info("Maya mcp module updated")
        else:
            # Execute bootstrap code using exec() with globals() to persist definitions
            # Maya command port runs each command in isolated scope, so we must use
            # exec(..., globals()) to make the code affect the global namespace
            bootstrap_code = get_bootstrap_code()
            bootstrap_cmd = f"exec({bootstrap_code!r}, globals())"
            await self._send_receive(bootstrap_cmd)
            # We've now bootstrapped the create_module function, which we use to create
            # the helper module:
            helper_code = get_helper_module_code()
            cmd = CREATE_MODULE_TEMPLATE.format(name="maya_mcp", code=helper_code, overwrite=False)
            # Remove the module name from create_module since it doesn't exist there yet.
            cmd = cmd.split(".", 1)[-1]
            await self._send_receive(cmd)
            logger.info("Maya session bootstrapped")

        # Create a dedicated communication port for this client
        new_port = random.randint(COMMUNICATION_PORT_MIN, COMMUNICATION_PORT_MAX)
        logger.info(f"Creating dedicated commandPort on port {new_port}")
        cmd = START_COMMAND_PORT.format(port=new_port)
        result = await self._send_receive(cmd)
        logger.info(f"Dedicated commandPort created: {result}")

        # Wait a moment for the port to start listening
        await asyncio.sleep(0.5)

        logger.info(f"Connecting to dedicated port {new_port}...")
        new_client = MayaClient(host=self.host, port=new_port, timeout=self.timeout, buffer_size=self.buffer_size)
        # Connect to the new dedicated port
        await new_client.connect()
        logger.info(f"Connected to dedicated port {new_port}")
        return new_client

    async def bootstrap_new(self) -> MayaQtClient:
        """
        Bootstrap the Maya session with helper functions.

        This creates the _mcp module in Maya's sys.modules,
        providing utilities for code execution with capture.
        Also starts the Qt command server and switches to it.
        """
        # Skip port detection - assume Python port and send commands directly
        # Maya command ports can be finicky with responses, so we'll just send
        # all bootstrap code and then connect to the Qt server it creates

        logger.info("Bootstrapping Maya session (sending code without waiting for responses)...")

        # Phase 1: Execute bootstrap code to create create_module function
        bootstrap_code = get_bootstrap_code()
        bootstrap_cmd = f"exec({bootstrap_code!r}, globals())"
        self._writer.write(bootstrap_cmd.encode("utf-8") + b"\n")
        await self._writer.drain()
        await asyncio.sleep(0.1)  # Give Maya time to execute

        # Phase 2: Create the helper module
        helper_code = get_helper_module_code()
        cmd = CREATE_MODULE_TEMPLATE.format(name="maya_mcp", code=helper_code, overwrite=False)
        cmd = cmd.split(".", 1)[-1]  # Remove module prefix
        self._writer.write(cmd.encode("utf-8") + b"\n")
        await self._writer.drain()
        await asyncio.sleep(0.1)

        # Phase 3: Start Qt server and detect the new port
        # Get current ports before starting server
        from maya_mcp_server.utils import get_maya_listening_ports
        ports_before = {p["port"] for p in get_maya_listening_ports()}
        logger.debug(f"Ports before Qt server: {ports_before}")

        # Start the Qt server
        start_cmd = f"{START_QT_SERVER}"
        self._writer.write(start_cmd.encode("utf-8") + b"\n")
        await self._writer.drain()

        # Wait for new port to appear
        logger.info("Waiting for Qt server to start...")
        try:
            qt_port = None
            for attempt in range(30):  # Try for 3 seconds (30 * 0.1s)
                await asyncio.sleep(0.1)

                # Check for new ports
                ports_after = {p["port"] for p in get_maya_listening_ports()}
                new_ports = ports_after - ports_before

                if new_ports:
                    # Found a new port - this should be our Qt server
                    qt_port = new_ports.pop()
                    logger.info(f"Detected Qt server on port {qt_port}")
                    break

            if not qt_port:
                raise MayaConnectionError("Failed to detect Qt server port - no new ports opened by Maya")

            # Connect to Qt server with retry logic
            qt_client = MayaQtClient(host=self.host, port=qt_port, timeout=self.timeout)
            await qt_client.connect()

            # Disconnect from commandPort (free it for others)
            if self._writer:
                old_port = self.port
                self._writer.close()
                try:
                    await self._writer.wait_closed()
                except Exception:
                    pass
                logger.info(f"Disconnected from commandPort {old_port}, now using Qt server on port {qt_port}")

        except Exception as e:
            raise MayaConnectionError(f"Qt server bootstrap failed: {e}") from e

        logger.info("Maya session bootstrapped with Qt server")
        return qt_client

    async def session_info(self) -> SessionInfo:
        """
        Get information about the connected Maya session.

        Returns:
            SessionInfo with pid, user, maya version, current scene, etc.
        """
        response = await self._send_receive(GET_SESSION_INFO)
        info = json.loads(response)

        # Add connection info
        info["host"] = self.host
        info["port"] = self.port
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
        await self._send_receive(INSTALL_STREAM_CAPTURE)
        logger.debug(f"Stream capture installed for {self.host}:{self.port}")

    async def uninstall_stream_capture(self) -> None:
        """
        Remove stream capture and restore original stdout/stderr in Maya.
        """
        await self._send_receive(UNINSTALL_STREAM_CAPTURE)
        logger.debug(f"Stream capture uninstalled for {self.host}:{self.port}")

    async def get_buffered_output(self) -> dict[str, str]:
        """
        Get buffered stdout/stderr content and clear the buffers.

        Returns:
            Dict with "stdout" and "stderr" keys containing captured output.
        """
        response = await self._send_receive(GET_BUFFERED_OUTPUT)
        return json.loads(response)

    def append_output(self, stdout: str = "", stderr: str = "") -> None:
        """
        Append output to the client's buffers.

        This is called after execute_code to accumulate output.

        Args:
            stdout: Stdout content to append
            stderr: Stderr content to append
        """
        if stdout:
            self._stdout_buffer += stdout
        if stderr:
            self._stderr_buffer += stderr

    def get_accumulated_output(self, clear: bool = True) -> dict[str, str]:
        """
        Get accumulated stdout/stderr output.

        Args:
            clear: If True, clear the buffers after reading

        Returns:
            Dict with "stdout" and "stderr" keys
        """
        output = {"stdout": self._stdout_buffer, "stderr": self._stderr_buffer}

        if clear:
            self._stdout_buffer = ""
            self._stderr_buffer = ""

        return output

    def clear_output(self) -> None:
        """Clear the accumulated output buffers."""
        self._stdout_buffer = ""
        self._stderr_buffer = ""

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


class MayaQtClient(BaseMayaClient):
    """Async client for communicating with our custom Maya Qt Command Server."""

    def __post_init__(self):
        super().__post_init__()
        self._request_counter: int = 0

    async def connect(self) -> None:
        """Connect to the Qt server with retry logic."""
        max_retries = 3
        retry_delay = 0.5  # Start with 0.5 seconds

        for attempt in range(max_retries):
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port),
                    timeout=self.timeout,
                )
                logger.info(f"Connected to Qt server at {self.host}:{self.port}")
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Failed to connect to Qt server (attempt {attempt + 1}/{max_retries}): {e}")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    raise MayaConnectionError(
                        f"Failed to connect to Qt server after {max_retries} attempts: {e}"
                    ) from e

    async def session_info(self) -> SessionInfo:
        """
        Get information about the connected Maya session.

        Returns:
            SessionInfo with pid, user, maya version, current scene, etc.
        """
        # Use Qt server JSON protocol
        info = await self._send_receive("get_session_info")

        # Add connection info
        info["host"] = self.host
        info["port"] = self.port
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
        # Use Qt server JSON protocol
        result = await self._send_receive("create_module", {
            "name": name,
            "code": code,
            "overwrite": overwrite
        })
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
        # Use Qt server JSON protocol
        # Don't raise on execution errors - return them in the result
        result: ExecutionResult = await self._send_receive("execute", {
            "code": code,
            "result_type": result_type.value
        }, raise_on_error=False)

        # Decode JSON result if needed (same as commandPort path)
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
        await self._send_receive("install_stream_capture")
        logger.debug(f"Stream capture installed for {self.host}:{self.port}")

    async def uninstall_stream_capture(self) -> None:
        """
        Remove stream capture and restore original stdout/stderr in Maya.
        """
        await self._send_receive("uninstall_stream_capture")
        logger.debug(f"Stream capture uninstalled for {self.host}:{self.port}")

    async def get_buffered_output(self) -> dict[str, str]:
        """
        Get buffered stdout/stderr content and clear the buffers.

        Returns:
            Dict with "stdout" and "stderr" keys containing captured output.
        """
        return await self._send_receive("get_buffered_output")

    async def _send_receive(self, method: str, params: dict | None = None, raise_on_error: bool = True) -> dict:
        """Send JSON request to Qt server and receive response.

        Args:
            method: Method name to call
            params: Parameters for the method
            raise_on_error: If True, raise exception on error. If False, return full response with error.
        """
        if not self._writer or not self._reader:
            raise MayaConnectionError("Not connected to Qt server")

        async with self._lock:
            # Generate request ID
            self._request_counter += 1
            request_id = f"req-{self._request_counter}"

            # Build request
            request = {
                "id": request_id,
                "method": method,
                "params": params or {}
            }

            try:
                # Send request
                request_line = json.dumps(request) + "\n"
                self._writer.write(request_line.encode('utf-8'))
                await self._writer.drain()

                # Read response (line-delimited JSON)
                response_line = await asyncio.wait_for(
                    self._reader.readline(),
                    timeout=self.timeout
                )

                if not response_line:
                    raise MayaConnectionError("Connection closed by Qt server")

                response = json.loads(response_line.decode('utf-8'))

                # Validate response ID
                if response.get("id") != request_id:
                    raise MayaExecutionError(
                        f"Response ID mismatch: expected {request_id}, got {response.get('id')}"
                    )

                # Check for error
                if raise_on_error and response.get("error"):
                    error = response["error"]
                    raise MayaExecutionError(f"{error.get('message', 'Unknown error')}")

                # Return full response if not raising on error, otherwise just the result
                if not raise_on_error:
                    return {"result": response.get("result"), "error": response.get("error")}
                return response.get("result")

            except asyncio.TimeoutError as e:
                raise MayaExecutionError("Timeout waiting for Qt server response") from e
            except json.JSONDecodeError as e:
                raise MayaExecutionError(f"Invalid JSON response from Qt server: {e}") from e
            except Exception as e:
                if not isinstance(e, (MayaConnectionError, MayaExecutionError)):
                    raise MayaExecutionError(f"Error communicating with Qt server: {e}") from e
                raise

    async def ping(self) -> bool:
        """
        Check if the Maya connection is alive.

        Returns:
            True if Maya responds, False otherwise
        """
        try:
            response = await self._send_receive("ping")
            return response == "pong"
        except Exception:
            return False


if __name__ == "__main__":
    cmd = """
maya.cmds.ls(cameras=True)
"""
    async def run():
        client = MayaClient(port=7001)
        await client.connect()
        result = await client._send_receive(cmd)
        print(result)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
