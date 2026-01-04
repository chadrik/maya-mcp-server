"""Type definitions for maya-mcp-server."""

from enum import Enum
from typing import Any, TypedDict


class ResultType(str, Enum):
    """How to interpret execution results."""

    NONE = "NONE"  # Don't capture result
    JSON = "JSON"  # JSON encode/decode result
    RAW = "RAW"  # Return raw string result


class PortType(str, Enum):
    """Type of Maya command port."""

    MEL = "mel"
    PYTHON = "python"
    UNKNOWN = "unknown"


class ErrorInfo(TypedDict):
    """Exception information from remote execution."""

    type: str  # Full dotted path of exception type
    message: str  # Exception message
    traceback: str  # Full traceback string


class ExecutionResult(TypedDict):
    """Result of remote code execution.

    Note: stdout/stderr are delivered via MCP Resource subscriptions,
    not in this result. Subscribe to:
    - maya://sessions/{host}:{port}/stdout
    - maya://sessions/{host}:{port}/stderr
    """

    result: Any | None  # Captured result (None if ResultType.NONE)
    error: ErrorInfo | None  # Exception info if error occurred


class SessionInfo(TypedDict, total=False):
    """Information about a Maya session."""

    host: str
    port: int
    pid: int
    user: str
    maya_version: str
    scene_name: str
    scene_path: str
