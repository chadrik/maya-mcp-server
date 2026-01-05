"""FastMCP server for Maya integration."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from maya_mcp_server.session_manager import SessionManager
from maya_mcp_server.types import ClientType, OutputBuffer, ResultType, SessionInfo


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
    - session_key: Session key used to interact with tools and resources
    - host: Session host address
    - port: Session port number
    - pid: Maya process ID
    - user: Logged-in user
    - maya_version: Maya version string
    - scene_name: Current scene filename
    - scene_path: Full path to current scene

    Note: To detect new or removed sessions, clients should call this tool
    periodically (e.g., every 10-30 seconds) and compare results. The SessionManager
    automatically scans for new Maya sessions in the background.
    """
    manager = get_session_manager()
    return await manager.list_sessions()


@mcp.tool
async def write_module(
    name: str,
    code: str,
    overwrite: bool = False,
    session_key: str | None = None,
) -> str:
    """
    Create a virtual Python module in a Maya session.

    Args:
        name: Module name. Can be a dotted path (e.g., 'mypackage.utils')
              in which case parent packages are created automatically.
        code: Python source code for the module.
        overwrite: If True, replace existing module. If False, raise error
                   if module already exists.
        session_key: Session key (optional if only one session exists)

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
    client = await manager.get_client(session_key)
    return await client.write_module(name, code, overwrite)


@mcp.tool
async def execute_code(
    code: str,
    result_type: str = "NONE",
    session_key: str | None = None,
) -> Any:
    """
    Execute Python code in a Maya session.

    Args:
        code: Python code to execute.
        result_type: How to handle the result:
            - "NONE": Execute statements, don't capture result
            - "JSON": Evaluate expression, JSON encode result
            - "RAW": Evaluate expression, return string representation
        session_key: Session key (optional if only one session exists)

    Returns:
        Captured result (None if result_type is NONE)

    Note: stdout and stderr are delivered in real-time via MCP Resource
    subscriptions (maya://sessions/{session_key}/stdout and /stderr).
    Call get_output() to retrieve buffered output.

    Example:
        # Execute statements
        execute_code("import maya.cmds as cmds; cmds.polyCube()")

        # Get JSON result
        execute_code("cmds.ls(type='mesh')", result_type="JSON")
    """
    manager = get_session_manager()
    client = await manager.get_client(session_key)

    rt = ResultType(result_type)
    result = await client.execute_code(code, rt)

    # Fetch any buffered output and store it in the client
    try:
        output = await client.get_buffered_output()
        client.append_output(output.stdout, output.stderr)
    except Exception as e:
        logger.debug(f"Failed to get buffered output: {e}")

    return result.result


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


# MCP Resources


@mcp.resource("maya://sessions/{session_key}/info")
async def session_info(session_key: str) -> SessionInfo:
    """
    Get information about a Maya session.

    Args:
        session_key: Session key

    Returns:
        SessionInfo with:
        - session_key: Session key used to interact with tools and resources
        - host: Session host address
        - port: Session port number
        - pid: Maya process ID
        - user: Logged-in user
        - maya_version: Maya version string
        - scene_name: Current scene filename
        - scene_path: Full path to current scene
    """
    manager = get_session_manager()
    client = await manager.get_client(session_key)
    return await client.session_info()


@mcp.resource("maya://sessions/{session_key}/output")
async def session_output(session_key: str, clear: bool = True) -> OutputBuffer:
    """
    Get captured stdout/stderr output from a Maya session.

    Args:
        clear: If True (default), clear the buffer after reading.
               If False, keep the buffer contents.
        session_key: Session key

    Returns:
        OutputBuffer with stdout and stderr fields containing captured output
        since the last call (or since stream capture was installed).

    This provides access to stdout/stderr that was captured during
    execute_code calls. For real-time streaming, subscribe to the
    MCP Resources instead.
    """
    manager = get_session_manager()
    client = await manager.get_client(session_key)
    return client.get_accumulated_output(clear=clear)


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
