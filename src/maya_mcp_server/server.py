"""FastMCP server for Maya integration."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from maya_mcp_server.session_manager import SessionManager
from maya_mcp_server.types import ResultType, SessionInfo

logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP(
    "Maya MCP Server",
)

# Global session manager - initialized when server starts
_session_manager: SessionManager | None = None

# Storage for stdout/stderr content per session
_session_output_buffers: dict[str, dict[str, str]] = {}


def get_session_manager() -> SessionManager:
    """Get the global session manager."""
    if _session_manager is None:
        raise RuntimeError("Session manager not initialized. Server not started.")
    return _session_manager


# Implementation functions (can be called directly in tests)


async def _list_sessions() -> list[SessionInfo]:
    """List all active Maya sessions."""
    manager = get_session_manager()
    return await manager.list_sessions()


async def _use_session(host: str, port: int) -> SessionInfo:
    """Activate a Maya session for subsequent operations."""
    manager = get_session_manager()
    client = await manager.use_session(host, port)

    # Initialize output buffer for this session
    session_key = f"{host}:{port}"
    _session_output_buffers[session_key] = {"stdout": "", "stderr": ""}

    return await client.session_info()


async def _unuse_session() -> str:
    """Deactivate the current Maya session and release all resources."""
    manager = get_session_manager()

    if manager.active_session is None:
        return "No active session to deactivate"

    session_key = manager.active_session.key
    await manager.unuse_session()

    # Clean up output buffer
    if session_key and session_key in _session_output_buffers:
        del _session_output_buffers[session_key]

    return f"Session {session_key} deactivated and resources released"


async def _get_session_info() -> SessionInfo:
    """Get updated information about the currently active Maya session."""
    manager = get_session_manager()
    client = manager.active_session

    if client is None:
        raise RuntimeError("No active session. Use use_session first.")

    return await client.session_info()


async def _write_module(
    name: str,
    code: str,
    overwrite: bool = False,
) -> str:
    """Create a virtual Python module in the active Maya session."""
    manager = get_session_manager()
    client = manager.active_session

    if client is None:
        raise RuntimeError("No active session. Use use_session first.")

    return await client.write_module(name, code, overwrite)


async def _execute_code(
    code: str,
    result_type: str = "NONE",
) -> dict[str, Any]:
    """Execute Python code in the active Maya session."""
    manager = get_session_manager()
    client = manager.active_session

    if client is None:
        raise RuntimeError("No active session. Use use_session first.")

    rt = ResultType(result_type)
    result = await client.execute_code(code, rt)

    # Fetch any buffered output and store it
    session_key = manager.active_session.key
    if session_key:
        try:
            output = await client.get_buffered_output()
            if session_key not in _session_output_buffers:
                _session_output_buffers[session_key] = {"stdout": "", "stderr": ""}
            _session_output_buffers[session_key]["stdout"] += output.get("stdout", "")
            _session_output_buffers[session_key]["stderr"] += output.get("stderr", "")
        except Exception as e:
            logger.debug(f"Failed to get buffered output: {e}")

    return dict(result)


async def _get_output(clear: bool = True) -> dict[str, str]:
    """Get captured stdout/stderr output from the active session."""
    manager = get_session_manager()

    if manager.active_session is None:
        raise RuntimeError("No active session. Use use_session first.")

    session_key = manager.active_session.key
    if not session_key or session_key not in _session_output_buffers:
        return {"stdout": "", "stderr": ""}

    output = _session_output_buffers[session_key].copy()

    if clear:
        _session_output_buffers[session_key] = {"stdout": "", "stderr": ""}

    return output


# MCP Tool decorators


@mcp.tool
async def list_sessions() -> list[SessionInfo]:
    """
    List all active Maya sessions.

    Returns a list of session information including:
    - host: Session host address
    - port: Session port number
    - pid: Maya process ID
    - user: Logged-in user
    - maya_version: Maya version string
    - scene_name: Current scene filename
    - scene_path: Full path to current scene
    """
    return await _list_sessions()


@mcp.tool
async def use_session(host: str, port: int) -> SessionInfo:
    """
    Activate a Maya session for subsequent operations.

    Args:
        host: The session host (usually "127.0.0.1" for local)
        port: The session port number

    Returns:
        Session information for the activated session

    All subsequent write_module and execute_code calls will
    target this session until a different one is selected.

    This tool also sets up stream capture for stdout/stderr.
    Subscribe to the MCP Resources for real-time output:
    - maya://sessions/{host}:{port}/stdout
    - maya://sessions/{host}:{port}/stderr
    """
    return await _use_session(host, port)


@mcp.tool
async def unuse_session() -> str:
    """
    Deactivate the current Maya session and release all resources.

    Returns:
        Confirmation message

    This tool:
    - Unsubscribes from stdout/stderr resource streams
    - Releases any held resources for the session
    - Clears the active session, requiring use_session to be called
      again before execute_code or write_module can be used
    """
    return await _unuse_session()


@mcp.tool
async def get_session_info() -> SessionInfo:
    """
    Get updated information about the currently active Maya session.

    Returns:
        SessionInfo with the same keys as list_sessions provides:
        - host: Session host address
        - port: Session port number
        - pid: Maya process ID
        - user: Logged-in user
        - maya_version: Maya version string
        - scene_name: Current scene filename
        - scene_path: Full path to current scene

    Raises:
        RuntimeError: If no session is currently active
    """
    return await _get_session_info()


@mcp.tool
async def write_module(
    name: str,
    code: str,
    overwrite: bool = False,
) -> str:
    """
    Create a virtual Python module in the active Maya session.

    Args:
        name: Module name. Can be a dotted path (e.g., 'mypackage.utils')
              in which case parent packages are created automatically.
        code: Python source code for the module.
        overwrite: If True, replace existing module. If False, raise error
                   if module already exists.

    Returns:
        Success message

    Example:
        write_module("mytools", '''
        import maya.cmds as cmds

        def create_cube(name="cube1"):
            return cmds.polyCube(name=name)[0]
        ''')

        # Then use it:
        execute_code("import mytools; mytools.create_cube('myCube')")
    """
    return await _write_module(name, code, overwrite)


@mcp.tool
async def execute_code(
    code: str,
    result_type: str = "NONE",
) -> dict[str, Any]:
    """
    Execute Python code in the active Maya session.

    Args:
        code: Python code to execute. For result_type NONE, can be
              multiple statements. For JSON or RAW, should be a single
              expression whose value will be captured.
        result_type: How to handle the result:
            - "NONE": Execute statements, don't capture result
            - "JSON": Evaluate expression, JSON encode result
            - "RAW": Evaluate expression, return string representation

    Returns:
        ExecutionResult containing:
        - result: Captured result (None if result_type is NONE)
        - error: Exception info if an error occurred, else None

    Note: stdout and stderr are delivered in real-time via MCP Resource
    subscriptions (maya://sessions/{host}:{port}/stdout and /stderr).
    Call get_output() to retrieve buffered output.

    Example:
        # Execute statements
        execute_code("import maya.cmds as cmds; cmds.polyCube()")

        # Get JSON result
        execute_code("cmds.ls(type='mesh')", result_type="JSON")
    """
    return await _execute_code(code, result_type)


@mcp.tool
async def get_output(clear: bool = True) -> dict[str, str]:
    """
    Get captured stdout/stderr output from the active session.

    Args:
        clear: If True (default), clear the buffer after reading.
               If False, keep the buffer contents.

    Returns:
        Dict with "stdout" and "stderr" keys containing captured output
        since the last call (or since session activation).

    This provides access to stdout/stderr that was captured during
    execute_code calls. For real-time streaming, subscribe to the
    MCP Resources instead.
    """
    return await _get_output(clear)


@mcp.tool
async def add_session(host: str = "127.0.0.1", port: int = 7001) -> SessionInfo:
    """
    Manually add a Maya session at a specific host and port.

    Use this when auto-discovery doesn't find your Maya session,
    or to connect to a Maya instance on a specific port.

    Args:
        host: The session host (default: "127.0.0.1")
        port: The session port number (default: 7001)

    Returns:
        Session information for the added session

    Before using this, ensure Maya has a Python command port open.
    In Maya's Script Editor (Python), run:
        import maya.cmds as cmds
        cmds.commandPort(name=':7001', sourceType='python')
    """
    manager = get_session_manager()
    client = await manager.add_session(host, port)
    return await client.session_info()


# MCP Resources for stdout/stderr streaming


@mcp.resource("maya://sessions/{host}:{port}/stdout")
async def session_stdout(host: str, port: str) -> str:
    """
    MCP Resource for stdout output from a Maya session.

    Returns buffered stdout content since last read.
    """
    session_key = f"{host}:{port}"

    if session_key not in _session_output_buffers:
        return ""

    stdout = _session_output_buffers[session_key].get("stdout", "")

    # Clear the stdout buffer after reading
    _session_output_buffers[session_key]["stdout"] = ""

    return stdout


@mcp.resource("maya://sessions/{host}:{port}/stderr")
async def session_stderr(host: str, port: str) -> str:
    """
    MCP Resource for stderr output from a Maya session.

    Returns buffered stderr content since last read.
    """
    session_key = f"{host}:{port}"

    if session_key not in _session_output_buffers:
        return ""

    stderr = _session_output_buffers[session_key].get("stderr", "")

    # Clear the stderr buffer after reading
    _session_output_buffers[session_key]["stderr"] = ""

    return stderr


async def initialize_session_manager(
    scan_interval: float = 10.0,
) -> SessionManager:
    """
    Initialize the global session manager.

    Args:
        scan_interval: Seconds between background scans

    Returns:
        The initialized SessionManager
    """
    global _session_manager

    _session_manager = SessionManager(
        scan_interval=scan_interval,
    )
    await _session_manager.start()

    return _session_manager


async def shutdown_session_manager() -> None:
    """Shutdown the global session manager."""
    global _session_manager

    if _session_manager is not None:
        await _session_manager.stop()
        _session_manager = None
