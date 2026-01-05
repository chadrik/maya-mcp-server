"""FastMCP server for Maya integration."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastmcp import FastMCP

from maya_mcp_server.session_manager import SessionManager
from maya_mcp_server.types import ClientType, ResultType, SessionInfo


logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP(
    "Maya MCP Server",
)

# Global session manager - initialized when server starts
_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    """Get the global session manager."""
    if _session_manager is None:
        raise RuntimeError("Session manager not initialized. Server not started.")
    return _session_manager


# MCP Tools
# Note: For testing, access the underlying function via tool.fn
# Example: list_sessions.fn() calls the actual implementation


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
    manager = get_session_manager()
    return await manager.list_sessions()


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
    manager = get_session_manager()
    client = await manager.use_session(host, port)

    return await client.session_info()


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
    manager = get_session_manager()

    if manager.active_session is None:
        return "No active session to deactivate"

    session_key = manager.active_session.key
    await manager.unuse_session()

    return f"Session {session_key} deactivated and resources released"


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
    manager = get_session_manager()
    client = manager.active_session

    if client is None:
        raise RuntimeError("No active session. Use use_session first.")

    return await client.session_info()


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
    manager = get_session_manager()
    client = manager.active_session

    if client is None:
        raise RuntimeError("No active session. Use use_session first.")

    return await client.write_module(name, code, overwrite)


@mcp.tool
async def execute_code(
    code: str,
    result_type: str = "NONE",
) -> Any:
    """
    Execute Python code in the active Maya session.

    Args:
        code: Python code to execute.
        result_type: How to handle the result:
            - "NONE": Execute statements, don't capture result
            - "JSON": Evaluate expression, JSON encode result
            - "RAW": Evaluate expression, return string representation

    Returns:
        Captured result (None if result_type is NONE)

    Note: stdout and stderr are delivered in real-time via MCP Resource
    subscriptions (maya://sessions/{host}:{port}/stdout and /stderr).
    Call get_output() to retrieve buffered output.

    Example:
        # Execute statements
        execute_code("import maya.cmds as cmds; cmds.polyCube()")

        # Get JSON result
        execute_code("cmds.ls(type='mesh')", result_type="JSON")
    """
    manager = get_session_manager()
    client = manager.active_session

    if client is None:
        raise RuntimeError("No active session. Use use_session first.")

    rt = ResultType(result_type)
    result = await client.execute_code(code, rt)

    # Fetch any buffered output and store it in the client
    try:
        output = await client.get_buffered_output()
        client.append_output(output.get("stdout", ""), output.get("stderr", ""))
    except Exception as e:
        logger.debug(f"Failed to get buffered output: {e}")

    return result.result


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
    manager = get_session_manager()
    client = manager.active_session

    if client is None:
        raise RuntimeError("No active session. Use use_session first.")

    return client.get_accumulated_output(clear=clear)


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
    manager = get_session_manager()
    session_key = f"{host}:{port}"

    # Get the client for this session
    client = manager._sessions.get(session_key)
    if client is None:
        return ""

    # Get stdout and clear it
    output = client.get_accumulated_output(clear=True)

    # Put stderr back since we only want stdout
    client.append_output(stderr=output["stderr"])

    return output["stdout"]


@mcp.resource("maya://sessions/{host}:{port}/stderr")
async def session_stderr(host: str, port: str) -> str:
    """
    MCP Resource for stderr output from a Maya session.

    Returns buffered stderr content since last read.
    """
    manager = get_session_manager()
    session_key = f"{host}:{port}"

    # Get the client for this session
    client = manager._sessions.get(session_key)
    if client is None:
        return ""

    # Get stderr and clear it
    output = client.get_accumulated_output(clear=True)

    # Put stdout back since we only want stderr
    client.append_output(stdout=output["stdout"])

    return output["stderr"]


async def initialize_session_manager(
    scan_interval: float = 10.0,
    client_type: str = "qt",
) -> SessionManager:
    """
    Initialize the global session manager.

    Args:
        scan_interval: Seconds between background scans
        client_type: Type of client to use ("native" or "qt")

    Returns:
        The initialized SessionManager
    """
    global _session_manager

    _session_manager = SessionManager(
        scan_interval=scan_interval,
        client_type=ClientType(client_type),
    )
    await _session_manager.start()

    return _session_manager


async def shutdown_session_manager() -> None:
    """Shutdown the global session manager."""
    global _session_manager

    if _session_manager is not None:
        await _session_manager.stop()
        _session_manager = None
