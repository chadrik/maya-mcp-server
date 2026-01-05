"""Maya client for communicating with Maya command ports."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from typing_extensions import Self

from maya_mcp_server.bootstrap import (
    get_bootstrap_code,
    get_helper_module_code,
)
from maya_mcp_server.types import (
    COMMUNICATION_PORT_MAX,
    COMMUNICATION_PORT_MIN,
    CommandResponse,
    OutputBuffer,
    PortType,
    ResultType,
    SessionInfo,
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
class BaseMayaClient(ABC):
    """Abstract base class for Maya clients."""

    GET_SESSION_INFO: ClassVar[str]
    EXECUTE_TEMPLATE: ClassVar[str]
    CREATE_MODULE_TEMPLATE: ClassVar[str]
    INSTALL_STREAM_CAPTURE: ClassVar[str]
    UNINSTALL_STREAM_CAPTURE: ClassVar[str]
    GET_BUFFERED_OUTPUT: ClassVar[str]

    host: str = "127.0.0.1"
    port: int = 7001
    timeout: float = 30.0
    buffer_size: int = 65536

    def __post_init__(self) -> None:
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

    def get_accumulated_output(self, clear: bool = True) -> OutputBuffer:
        """
        Get accumulated stdout/stderr output.

        Args:
            clear: If True, clear the buffers after reading

        Returns:
            OutputBuffer with stdout and stderr fields
        """
        output = OutputBuffer(stdout=self._stdout_buffer, stderr=self._stderr_buffer)

        if clear:
            self._stdout_buffer = ""
            self._stderr_buffer = ""

        return output

    def clear_output(self) -> None:
        """Clear the accumulated output buffers."""
        self._stdout_buffer = ""
        self._stderr_buffer = ""

    async def install_stream_capture(self) -> None:
        """
        Install stream capture for stdout/stderr in Maya.

        This redirects stdout/stderr through custom writers that buffer
        output for retrieval via get_buffered_output().
        """
        await self._send_receive(self.INSTALL_STREAM_CAPTURE)
        logger.debug(f"Stream capture installed for {self.host}:{self.port}")

    async def uninstall_stream_capture(self) -> None:
        """
        Remove stream capture and restore original stdout/stderr in Maya.
        """
        await self._send_receive(self.UNINSTALL_STREAM_CAPTURE)
        logger.debug(f"Stream capture uninstalled for {self.host}:{self.port}")

    async def get_buffered_output(self) -> OutputBuffer:
        """
        Get buffered stdout/stderr content and clear the buffers.

        Returns:
            OutputBuffer with stdout and stderr fields containing captured output.
        """
        response = await self._send_receive(self.GET_BUFFERED_OUTPUT)
        result = response.result if response.result is not None else {}
        return OutputBuffer(
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", ""),
        )

    async def session_info(self) -> SessionInfo:
        """
        Get information about the connected Maya session.

        Returns:
            SessionInfo with pid, user, maya version, current scene, etc.
        """
        response = await self._send_receive(self.GET_SESSION_INFO)
        info = response.result if response.result is not None else {}

        return SessionInfo(
            session_key=self.key,
            host=self.host,
            port=self.port,
            pid=info.get("pid", 0),
            user=info.get("user", ""),
            maya_version=info.get("maya_version", ""),
            scene_name=info.get("scene_name", ""),
            scene_path=info.get("scene_path", ""),
        )

    async def execute_code(
        self,
        code: str,
        result_type: ResultType = ResultType.NONE,
    ) -> CommandResponse:
        """
        Execute Python code in Maya and return the result.

        Args:
            code: Python code to execute
            result_type: How to handle the result
                - NONE: Execute statements, don't capture result
                - JSON: Evaluate expression, JSON encode result
                - RAW: Evaluate expression, return string representation

        Returns:
            CommandResponse with result and error info.
            Note: stdout/stderr are delivered via MCP Resources, not returned here.
        """
        # Use Qt server JSON protocol
        # Don't raise on execution errors - return them in the result
        response = await self._send_receive(
            self.EXECUTE_TEMPLATE,
            {"code": code, "result_type": result_type.value},
            raise_on_error=False,
        )

        # Decode JSON result if needed (same as commandPort path)
        if result_type == ResultType.JSON and response.result is not None:
            try:
                decoded_result = json.loads(response.result)
                # Create new CommandResponse with decoded result
                return CommandResponse(result=decoded_result, error=response.error)
            except json.JSONDecodeError:
                pass  # Keep as string if not valid JSON

        return response

    # Abstract methods that must be implemented by subclasses

    @abstractmethod
    async def _send_receive(
        self, method: str, params: dict[str, Any] | None = None, raise_on_error: bool = True
    ) -> CommandResponse:
        """
        Send command to Maya and receive response.

        Args:
            method: Command string or method name (may contain {param} placeholders)
            params: Parameters to format into the command or pass to the method
            raise_on_error: If True, raise exception on error. If False, return full response with error.

        Returns:
            CommandResponse with result and error attributes

        Raises:
            MayaConnectionError: If not connected
            MayaExecutionError: If communication fails or raise_on_error is True and command errors
        """
        ...

    @abstractmethod
    async def write_module(self, name: str, code: str, overwrite: bool = False) -> str:
        """Create a virtual Python module in the Maya session."""
        ...

    @abstractmethod
    async def ping(self) -> bool:
        """Check if the Maya session is still responsive."""
        ...


class MayaClient(BaseMayaClient):
    """Async client for communicating with a Maya command port."""

    # Access the helper via __import__ (works in single expressions)
    _MCP_HELPER = "__import__('maya_mcp')"

    # Command templates that use __import__ to access the persistent _mcp module
    GET_SESSION_INFO = f"{_MCP_HELPER}.get_session_info()"
    EXECUTE_TEMPLATE = f"{_MCP_HELPER}.execute({{code!r}}, {{result_type!r}})"
    CREATE_MODULE_TEMPLATE = f"{_MCP_HELPER}.create_module({{name!r}}, {{code!r}}, {{overwrite!r}})"
    INSTALL_STREAM_CAPTURE = f"{_MCP_HELPER}.install_stream_capture()"
    UNINSTALL_STREAM_CAPTURE = f"{_MCP_HELPER}.uninstall_stream_capture()"
    GET_BUFFERED_OUTPUT = f"{_MCP_HELPER}.get_buffered_output()"
    START_COMMAND_PORT = f"{_MCP_HELPER}.start_command_port({{port!r}})"

    # Qt server command templates
    START_QT_SERVER = f"{_MCP_HELPER}.start_qt_server({{port!r}})"
    STOP_QT_SERVER = f"{_MCP_HELPER}.stop_qt_server()"
    GET_QT_SERVER_PORT = f"{_MCP_HELPER}.get_qt_server_port()"

    # Check if bootstrap has been done
    CHECK_BOOTSTRAP = "'maya_mcp' in __import__('sys').modules"

    def __post_init__(self) -> None:
        super().__post_init__()
        self._port_type: PortType = PortType.UNKNOWN

    async def _send_receive(
        self, method: str, params: dict[str, Any] | None = None, raise_on_error: bool = True
    ) -> CommandResponse:
        """
        Send command to Maya commandPort and receive response.

        Args:
            method: Command template string (may contain {param} placeholders)
            params: Parameters to format into the template
            raise_on_error: If True, raise exception on error. If False, return full response with error.

        Returns:
            CommandResponse with result and error attributes

        Raises:
            MayaConnectionError: If not connected
            MayaExecutionError: If communication fails or raise_on_error is True and command errors
        """
        if not self._writer or not self._reader:
            raise MayaConnectionError("Not connected to Maya")

        # Format the command template with params
        if params:
            command = method.format(**params)
        else:
            command = method

        async with self._lock:
            try:
                # Send command
                self._writer.write(command.encode("utf-8"))
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
                response_str = response_bytes.decode("utf-8").rstrip("\x00").rstrip("\n")

                # Parse JSON response if the command returns JSON
                # Most helper functions return JSON with {"result": ..., "error": ...}
                try:
                    response = json.loads(response_str)
                    # Check if it's a structured response
                    if isinstance(response, dict) and ("result" in response or "error" in response):
                        if raise_on_error and response.get("error"):
                            error = response["error"]
                            if isinstance(error, dict):
                                raise MayaExecutionError(f"{error.get('message', 'Unknown error')}")
                            else:
                                raise MayaExecutionError(str(error))
                        return CommandResponse(
                            result=response.get("result"), error=response.get("error")
                        )
                    else:
                        # It's JSON but not our structured format, treat as raw result
                        return CommandResponse(result=response, error=None)
                except json.JSONDecodeError:
                    # Not JSON, treat as raw string result
                    return CommandResponse(result=response_str, error=None)

            except asyncio.TimeoutError as e:
                raise MayaExecutionError("Timeout waiting for Maya response") from e
            except MayaExecutionError:
                raise
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
            result_str = str(response.result if response.result is not None else "").strip()
            if result_str == "2":
                self._port_type = PortType.PYTHON
            else:
                # Likely MEL - would return an error or different format
                self._port_type = PortType.MEL

        except Exception:
            self._port_type = PortType.UNKNOWN

        logger.info(f"Detected port type: {self._port_type.value}")
        return self._port_type

    async def _bootstrap(self, overwrite: bool = False) -> None:
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

        if not overwrite:
            # Check if already bootstrapped (e.g., from previous connection)
            check_result = await self._send_receive(self.CHECK_BOOTSTRAP)
            if (
                str(check_result.result if check_result.result is not None else "").strip()
                == "True"
            ):
                logger.info("Maya session already bootstrapped, updating module...")
                # Module exists, but update it to ensure it has latest functions
                helper_code = get_helper_module_code()
                await self._send_receive(
                    self.CREATE_MODULE_TEMPLATE,
                    {"name": "maya_mcp", "code": helper_code, "overwrite": True},
                )
                logger.info("Maya mcp module updated")
                return

        # Execute bootstrap code using exec() with globals() to persist definitions
        # Maya command port runs each command in isolated scope, so we must use
        # exec(..., globals()) to make the code affect the global namespace
        bootstrap_code = get_bootstrap_code()
        bootstrap_cmd = f"exec({bootstrap_code!r}, globals())"
        await self._send_receive(bootstrap_cmd)
        # We've now bootstrapped the create_module function, which we use to create
        # the helper module:
        helper_code = get_helper_module_code()
        # Remove the module name prefix since create_module doesn't exist yet
        cmd = "create_module({name!r}, {code!r}, {overwrite!r})"
        await self._send_receive(
            cmd, {"name": "maya_mcp", "code": helper_code, "overwrite": overwrite}
        )
        logger.info("Maya session bootstrapped")

    async def bootstrap(self, client_type: Literal["native", "qt"] = "native") -> BaseMayaClient:
        """
        Boostrap remote session and return a new client
        """
        await self._bootstrap()

        # Create a dedicated communication port for this client
        new_port = random.randint(COMMUNICATION_PORT_MIN, COMMUNICATION_PORT_MAX)
        new_client: BaseMayaClient

        if client_type == "native":
            logger.info(f"Creating dedicated commandPort on port {new_port}")
            result = await self._send_receive(self.START_COMMAND_PORT, {"port": new_port})
            logger.info(f"Dedicated commandPort created: {result}")

            # Wait a moment for the port to start listening
            await asyncio.sleep(0.5)

            logger.info(f"Connecting to dedicated port {new_port}...")
            new_client = MayaClient(
                host=self.host, port=new_port, timeout=self.timeout, buffer_size=self.buffer_size
            )
        elif client_type == "qt":
            # Unlike the commandPort, the qt server can handle multiple clients on the same port.
            # Therefore, the port returned by _send_receive might be different than requested.
            logger.info(f"Starting Qt server on port {new_port}")
            result = await self._send_receive(self.START_QT_SERVER, {"port": new_port})
            # Extract the actual port from the response (may differ if server was already running)
            if result.result and isinstance(result.result, dict):
                new_port = result.result.get("port", new_port)
            logger.info(f"Qt server started on port {new_port}")

            # Wait a moment for the port to start listening
            await asyncio.sleep(0.5)

            logger.info(f"Connecting to dedicated port {new_port}...")
            new_client = MayaQtClient(
                host=self.host, port=new_port, timeout=self.timeout, buffer_size=self.buffer_size
            )
        else:
            raise TypeError(client_type)
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

        if not self._writer:
            raise MayaConnectionError("Not connected to Maya")

        # Phase 1: Execute bootstrap code to create create_module function
        bootstrap_code = get_bootstrap_code()
        bootstrap_cmd = f"exec({bootstrap_code!r}, globals())"
        self._writer.write(bootstrap_cmd.encode("utf-8") + b"\n")
        await self._writer.drain()
        await asyncio.sleep(0.1)  # Give Maya time to execute

        # Phase 2: Create the helper module
        helper_code = get_helper_module_code()
        cmd = self.CREATE_MODULE_TEMPLATE.format(name="maya_mcp", code=helper_code, overwrite=False)
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
        start_cmd = f"{self.START_QT_SERVER}"
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
                raise MayaConnectionError(
                    "Failed to detect Qt server port - no new ports opened by Maya"
                )

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
                logger.info(
                    f"Disconnected from commandPort {old_port}, now using Qt server on port {qt_port}"
                )

        except Exception as e:
            raise MayaConnectionError(f"Qt server bootstrap failed: {e}") from e

        logger.info("Maya session bootstrapped with Qt server")
        return qt_client

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
        response = await self._send_receive(
            self.CREATE_MODULE_TEMPLATE, {"name": name, "code": code, "overwrite": overwrite}
        )

        result = response.result if response.result is not None else {}
        if isinstance(result, dict):
            return str(result.get("message", f"Module '{name}' created"))
        return f"Module '{name}' created"

    async def ping(self) -> bool:
        """
        Check if the Maya connection is alive.

        Returns:
            True if Maya responds, False otherwise
        """
        try:
            response = await self._send_receive("1+1")
            return str(response.result if response.result is not None else "").strip() == "2"
        except Exception:
            return False


class MayaQtClient(BaseMayaClient):
    """Async client for communicating with our custom Maya Qt Command Server."""

    GET_SESSION_INFO = "get_session_info"
    EXECUTE_TEMPLATE = "execute"
    CREATE_MODULE_TEMPLATE = "create_module"
    INSTALL_STREAM_CAPTURE = "install_stream_capture"
    UNINSTALL_STREAM_CAPTURE = "uninstall_stream_capture"
    GET_BUFFERED_OUTPUT = "get_buffered_output"

    def __post_init__(self) -> None:
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
                    logger.warning(
                        f"Failed to connect to Qt server (attempt {attempt + 1}/{max_retries}): {e}"
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    raise MayaConnectionError(
                        f"Failed to connect to Qt server after {max_retries} attempts: {e}"
                    ) from e

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
        response = await self._send_receive(
            self.CREATE_MODULE_TEMPLATE, {"name": name, "code": code, "overwrite": overwrite}
        )
        result = response.result if response.result is not None else {}
        if isinstance(result, dict):
            return str(result.get("message", f"Module '{name}' created"))
        return f"Module '{name}' created"

    async def _send_receive(
        self, method: str, params: dict[str, Any] | None = None, raise_on_error: bool = True
    ) -> CommandResponse:
        """Send JSON request to Qt server and receive response.

        Args:
            method: Method name to call
            params: Parameters for the method
            raise_on_error: If True, raise exception on error. If False, return full response with error.

        Returns:
            CommandResponse with result and error attributes
        """
        if not self._writer or not self._reader:
            raise MayaConnectionError("Not connected to Qt server")

        async with self._lock:
            # Generate request ID
            self._request_counter += 1
            request_id = f"req-{self._request_counter}"

            # Build request
            request = {"id": request_id, "method": method, "params": params or {}}

            try:
                # Send request
                request_line = json.dumps(request) + "\n"
                self._writer.write(request_line.encode("utf-8"))
                await self._writer.drain()

                # Read response (line-delimited JSON)
                response_line = await asyncio.wait_for(
                    self._reader.readline(), timeout=self.timeout
                )

                if not response_line:
                    raise MayaConnectionError("Connection closed by Qt server")

                response = json.loads(response_line.decode("utf-8"))

                # Validate response ID
                if response.get("id") != request_id:
                    raise MayaExecutionError(
                        f"Response ID mismatch: expected {request_id}, got {response.get('id')}"
                    )

                # Check for error
                if raise_on_error and response.get("error"):
                    error = response["error"]
                    raise MayaExecutionError(f"{error.get('message', 'Unknown error')}")

                # Return CommandResponse
                return CommandResponse(result=response.get("result"), error=response.get("error"))

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
            return bool(response.result == "pong")
        except Exception:
            return False


if __name__ == "__main__":
    cmd = """
import maya.cmds
maya.cmds.ls(cameras=True)
"""

    port = 7001

    # Native
    import socket

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("127.0.0.1", port))

    client.send(cmd.encode("utf-8"))

    result = data = client.recv(1024)
    while len(data) == 1024:
        data = client.recv(1024)
        result += data
    client.close()

    output: str | None
    if result:
        output = result.decode("utf-8")
    else:
        output = None
    if output:
        print(output.strip())

    # Ours

    async def run() -> None:
        client = MayaClient(port=port)
        await client.connect()
        result = await client._send_receive(cmd)
        print(result)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass

    async def run2() -> None:
        client = MayaClient(port=port)
        await client.connect()
        await client._bootstrap(overwrite=True)
        result = await client.execute_code(cmd)
        print(result)

    try:
        asyncio.run(run2())
    except KeyboardInterrupt:
        pass
