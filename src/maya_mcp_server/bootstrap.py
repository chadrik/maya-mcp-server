"""Bootstrap code management for Maya sessions.

Maya's command port has specific behavior:
- Each command runs in a fresh local namespace
- Statements with `;` return the result of the FIRST statement, not the last
- Modules stored in sys.modules persist between commands
- Use `__import__('module')` to access persistent modules in single expressions

This module provides functions to load bootstrap code and templates for
accessing the persistent `_mcp` module in Maya sessions.
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path


def _get_code(module_name: str) -> str:
    """
    Get the bootstrap code that creates the _mcp module in Maya.

    The code is loaded from maya_bootstrap.py and must be executed via
    exec(code, globals()) to persist definitions in Maya's global namespace.

    Returns:
        Python source code as a string
    """
    # Try modern importlib.resources API first (Python 3.9+)
    try:
        if hasattr(importlib.resources, "files"):
            # Python 3.9+
            bootstrap_file = importlib.resources.files("maya_mcp_server") / f"{module_name}.py"
            return bootstrap_file.read_text(encoding="utf-8")
    except (AttributeError, TypeError):
        pass

    # Fallback: use __file__ to locate maya_bootstrap.py
    bootstrap_path = Path(__file__).parent / f"{module_name}.py"
    return bootstrap_path.read_text(encoding="utf-8")


def get_bootstrap_code() -> str:
    """
    Get the bootstrap code that creates the _mcp module in Maya.

    The code is loaded from maya_bootstrap.py and must be executed via
    exec(code, globals()) to persist definitions in Maya's global namespace.

    Returns:
        Python source code as a string
    """
    # FIXME: instead of storing create_module in a seprate file we should be able to extract
    #  just the necessary lines of code using inspect
    return _get_code("maya_bootstrap")


def get_helper_module_code() -> str:
    """
    Get the helper code that becomes the maya_mcp module in Maya.

    Returns:
        Python source code as a string
    """
    return _get_code("maya_mcp_helper") + _get_code("maya_bootstrap")


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
START_QT_SERVER = f"{_MCP_HELPER}.start_qt_server()"
STOP_QT_SERVER = f"{_MCP_HELPER}.stop_qt_server()"
GET_QT_SERVER_PORT = f"{_MCP_HELPER}.get_qt_server_port()"

# Check if bootstrap has been done
CHECK_BOOTSTRAP = "'maya_mcp' in __import__('sys').modules"
